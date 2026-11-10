"""Executable workflow specification checks, separate from service integration tests."""

import copy
import importlib.util
from pathlib import Path

import pytest
from jsonschema import ValidationError

PATH = Path(__file__).resolve().parents[1] / "scripts/verify_workflow_contracts.py"
SPEC = importlib.util.spec_from_file_location("v3_contract_oracle", PATH)
oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oracle)


def example(name):
    return copy.deepcopy(oracle.load("examples.json")[name])


def test_closed_contracts_bound_defaults_authored_traces_and_fixture_hashes():
    report = oracle.verify_contracts()
    assert report == {"schemas": 18, "examples": 15, "traces": 8}


def test_independent_domain_oracles_empty_learning_snapshot_and_wrong_proposals():
    report = oracle.verify_engine_fixtures()
    assert report["equipment"]["truth_cases"] == 9
    assert report["access"]["truth_cases"] == 6
    assert all(r["incorrect_definition_rejected"] for r in report.values())


def test_source_oracles_preserve_spans_dates_and_fact_rule_distinction():
    assert oracle.verify_source_oracles() == {
        "authored_claims_validated": 2,
        "span_checks": 2,
        "extraction_performed": False,
    }


def test_attachment_only_message_and_actual_utf8_byte_limit():
    value = example("MessageInput")
    value.update(text="", attachment_ids=["attachment-1"])
    oracle.validate("MessageInput", value)
    value["attachment_ids"] = []
    with pytest.raises(ValueError, match="Empty message"):
        oracle.validate("MessageInput", value)
    value["text"] = "\u8bed" * 21846
    with pytest.raises(ValueError, match="byte limit"):
        oracle.validate("MessageInput", value)


@pytest.mark.parametrize("name", list(oracle.load("examples.json")))
def test_no_resource_can_smuggle_an_extra_authority_field(name):
    value = example(name)
    value["approved_by_owner"] = True
    with pytest.raises(ValidationError):
        oracle.validate(name, value)


@pytest.mark.parametrize("amount", [True, -1, 0, 2.0, "2000000", 1_000_000_001])
def test_currency_is_strict_bounded_positive_integer(amount):
    value = example("Allowance")
    value["cap_micro_usd"] = amount
    with pytest.raises(ValidationError):
        oracle.validate("Allowance", value)


def test_automatic_admission_cannot_omit_independent_requirements():
    value = example("TaskSpec")
    value["publication"] = "checked_auto"
    with pytest.raises(ValueError, match="requirements"):
        oracle.validate("TaskSpec", value)


@pytest.mark.parametrize("actor", ["assistant", "source", "append_client", "worker", "scoped_client"])
def test_data_or_worker_cannot_approve_a_proposal(actor):
    decision, proposal = example("DecisionInput"), example("Proposal")
    with pytest.raises(ValueError, match="authenticated owner"):
        oracle.decision_allowed(decision, proposal, actor=actor, context=proposal["context"], now_ms=1)


@pytest.mark.parametrize("field", ["proposal_id", "proposal_digest", "context", "expired"])
def test_decision_binds_exact_proposal_context_and_expiry(field):
    decision, proposal = example("DecisionInput"), example("Proposal")
    if field == "context":
        decision[field]["adm_id"] = "another-adm"
    elif field == "proposal_digest":
        decision[field] = "sha256:" + "d" * 64
    elif field != "expired":
        decision[field] = "other-proposal"
    with pytest.raises(ValueError):
        oracle.decision_allowed(
            decision,
            proposal,
            actor="owner",
            context=proposal["context"],
            now_ms=proposal["expires_at_ms"] if field == "expired" else 1,
        )


def test_current_explicit_decision_is_allowed_without_repeated_permission():
    decision, proposal = example("DecisionInput"), example("Proposal")
    assert oracle.decision_allowed(decision, proposal, actor="owner", context=proposal["context"], now_ms=1)


def test_learning_cannot_spend_reserved_interactive_quota_or_only_per_adm_slot():
    defaults = oracle.load("defaults.json")
    for scope, expected_remaining in (("installation", 40), ("per_adm", 8)):
        total = defaults["quota_totals"][scope]["calls"]
        learning = defaults["quota_lanes"][scope]["learning"]["calls"]
        assert total - learning == expected_remaining
    assert defaults["provider_slots_per_adm"] > defaults["background_per_adm"]


def test_price_rounding_reservation_and_no_cross_lane_borrowing():
    price = example("PriceRecord")
    assert oracle.reserve_micro(price, 1, 1, now_ms=1) == 6
    amount = oracle.reserve_micro(price, 32000, 8192, now_ms=1)
    assert amount == 96768
    allowance = example("Allowance")
    allowance.update(cap_micro_usd=90000, reserved_micro_usd=0)
    assert not oracle.can_reserve(allowance, amount, "learning", price["id"])
    allowance.update(cap_micro_usd=2000000)
    assert oracle.can_reserve(allowance, amount, "learning", price["id"])
    assert not oracle.can_reserve(
        allowance, amount, "learning", price["id"], now_ms=allowance["expires_at_ms"]
    )
    assert not oracle.can_reserve(allowance, amount, "interaction", price["id"])
    assert not oracle.can_reserve(allowance, amount, "learning", "other-price")
    allowance.update(reserved_micro_usd=1950000)  # Includes an unsettled earlier call.
    assert not oracle.can_reserve(allowance, amount, "learning", price["id"])


@pytest.mark.parametrize("change", ["live_synthetic", "unpriced", "expired", "missing_bound", "negative"])
def test_unverified_or_inapplicable_live_price_never_authorizes_dispatch(change):
    price = example("PriceRecord")
    if change == "live_synthetic":
        price["provider"] = "openai"
    elif change == "unpriced":
        price.update(bound_method="unpriced", bound_evidence=None)
    elif change == "missing_bound":
        price["bound_evidence"] = None
    elif change == "negative":
        price["output_micro_per_million"] = -1
    with pytest.raises((ValueError, ValidationError)):
        oracle.reserve_micro(price, 32000, 8192, now_ms=3600000 if change == "expired" else 1)


def test_acquisition_cannot_be_charged_as_chat_and_unknown_cannot_invent_usage():
    value = example("TaskStep")
    value["lane"] = "interaction"
    with pytest.raises(ValueError, match="Wrong lane"):
        oracle.validate("TaskStep", value)
    value.update(lane="learning", status="unknown", outcome_digest="sha256:" + "c" * 64)
    with pytest.raises(ValueError, match="Unknown"):
        oracle.validate("TaskStep", value)


def test_historic_unpriced_usage_cannot_be_represented_as_free():
    value = example("Allowance")
    value.update(
        status="unpriced_legacy",
        price_id=None,
        cap_micro_usd=None,
        settled_micro_usd=None,
        reserved_micro_usd=None,
        legacy_grant_ids=["original-grant"],
    )
    oracle.validate("Allowance", value)
    assert not oracle.can_reserve(value, 1, "learning", "new-price")
    value["reserved_micro_usd"] = 0
    with pytest.raises(ValueError, match="Unknown dollars"):
        oracle.validate("Allowance", value)


@pytest.mark.parametrize("state", oracle.load("lifecycle.json")["terminal_task"])
def test_terminal_task_cannot_resume_or_acquire_again(state):
    with pytest.raises(ValueError):
        oracle.transition("task", state, "resume", {"authorized": True, "current": True})


def test_uncertain_dispatch_no_retry_refund_or_parent_resume():
    with pytest.raises(ValueError):
        oracle.transition("step", "unknown", "dispatch")
    with pytest.raises(ValueError):
        oracle.transition("step", "reserved", "release_unissued")
    with pytest.raises(ValueError):
        oracle.transition(
            "task", "paused", "resume", {"authorized": True, "current": True, "unknown_dispatch": True}
        )
    assert oracle.transition("step", "unknown", "settle", {"outcome_identified": True}) == "known"


@pytest.mark.parametrize(
    "guards",
    [
        {"authorized": True, "current": False, "parent_running": True},
        {"authorized": True, "current": True, "parent_running": False},
        {"authorized": True, "current": True, "parent_running": True, "deleted": True},
    ],
)
def test_late_publication_is_fenced(guards):
    with pytest.raises(ValueError):
        oracle.transition("step", "checked", "admit", guards)


def test_partial_results_and_delete_completion_need_actual_recorded_outcomes():
    with pytest.raises(ValueError):
        oracle.transition("task", "running", "partial", {"accepted": False, "unresolved": True})
    with pytest.raises(ValueError):
        oracle.transition("task", "running", "complete", {"all_done": True, "unresolved": True})
    with pytest.raises(ValueError):
        oracle.transition("deletion", "purging", "finish")
    assert oracle.transition("deletion", "blocked", "resume", {"resume_stage": "purging"}) == "purging"
    value = example("DeletionOperation")
    value["status"] = "deleted"
    with pytest.raises(ValueError):
        oracle.validate("DeletionOperation", value)


@pytest.mark.parametrize("change", ["value", "digest", "assurance", "support", "authority"])
def test_narration_claims_cannot_upgrade_or_replace_local_outcome(change):
    packet = {
        "subject_id": "result-1",
        "outcome_digest": "sha256:" + "a" * 64,
        "value": True,
        "allowed_claims": ["value"],
        "support_ids": ["result-1"],
    }
    proposed = {
        "subject_id": packet["subject_id"],
        "outcome_digest": packet["outcome_digest"],
        "value": True,
        "claims": ["value"],
        "support_ids": ["result-1"],
    }
    oracle.check_presentation(packet, proposed)
    if change == "value":
        proposed["value"] = 1  # Python equality must not equate this to a Boolean answer.
    elif change == "digest":
        proposed["outcome_digest"] = "sha256:" + "b" * 64
    elif change == "assurance":
        proposed["claims"].append("unreachable")
    elif change == "support":
        proposed["support_ids"].append("invented-evidence")
    else:
        proposed["approved"] = True
    with pytest.raises(ValueError):
        oracle.check_presentation(packet, proposed)


def test_append_scope_cannot_grant_read_admin_or_cross_source_authority():
    scope = example("AppendScope")
    scope["permissions"] = ["append", "read"]
    with pytest.raises(ValidationError):
        oracle.validate("AppendScope", scope)
    scope = example("AppendScope")
    scope["source_ids"].append(scope["source_ids"][0])
    with pytest.raises(ValidationError):
        oracle.validate("AppendScope", scope)
