from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest

from awm_adm.engine import Budget, Instance, build_candidate, build_certificate, validate_snapshot
from awm_adm.engine import instance as coordination
from awm_adm.engine.artifacts import digest
from awm_adm.engine.data import encode, read_json
from awm_adm.engine.errors import Conflict, Rejected, ResourceLimit, StorageError

from .ported.helpers import UNIT, call, fixture, function, integer, literal, operator, variable


def evidence(label="authored fixture"):
    return {
        "artifact_kind": "evidence",
        "evidence_kind": "synthetic_fixture",
        "origin": label,
        "scope": "Development test only",
        "content": {"basis": label},
    }


def constant(value):
    return function({}, integer(0, 100), literal(value))


def capacity_policy(value=10):
    return {
        "profile": "adm-conformance/0.1",
        "contracts": [
            {
                "contract_id": "owner-capacity",
                "origin": "Independent authored requirement",
                "required_symbols": ["site.capacity"],
                "checks": [
                    {
                        "id": "value",
                        "kind": "value",
                        "params": {},
                        "expression": call("site.capacity"),
                        "expected": literal(value),
                    }
                ],
            }
        ],
    }


def publish(instance, declarations, key="candidate", *, records=None, support=None, base=None):
    package = build_candidate(
        base or instance.model,
        declarations,
        candidate_id=key,
        evidence=records or [evidence()],
        evidence_by_symbol=support,
    )
    instance.receive(package, review_required=False)
    return instance.decide_next()


def value_query(symbol="site.capacity"):
    return {"op": "evaluate", "module": symbol.split(".")[0], "expression": call(symbol)}


def invariant_policy():
    return {
        "profile": "adm-conformance/0.2",
        "contracts": [
            {
                "contract_id": "owner-safe",
                "origin": "Owner's independent carrier and predicate",
                "required_symbols": ["site.anchor"],
                "checks": [
                    {
                        "id": "closed",
                        "kind": "invariant",
                        "module": "site",
                        "state_type": integer(0, 2),
                        "predicate": operator("le", variable("state"), literal(1)),
                        "initial_states": [0],
                        "selection": {"kind": "module_all"},
                    }
                ],
            }
        ],
    }


def action(next_value):
    return {
        "kind": "transition",
        "state": integer(0, 2),
        "parameters": UNIT,
        "legal": literal(True),
        "next": literal(next_value),
    }


@pytest.mark.parametrize("mode,expected,status", [("forward", 12, "accepted"), ("backward", 10, "rejected")])
def test_receipt_order_decides_conflicts_from_parallel_base(mode, expected, status):
    instance = Instance(mode=mode)
    base = instance.model
    packages = [
        build_candidate(base, {"site.capacity": constant(n)}, candidate_id=f"c-{n}", evidence=[evidence()])
        for n in (10, 12)
    ]
    for package in packages:
        instance.receive(package, review_required=False)
    assert instance.candidate("c-10")["receipt_sequence"] == 1
    assert instance.candidate("c-12")["receipt_sequence"] == 2
    assert instance.decide_next()["status"] == "accepted"
    assert instance.decide_next()["status"] == status
    assert instance.query(value_query())["value"] == expected


def test_future_only_switch_does_not_replay_rejected_history():
    instance = Instance()
    publish(instance, {"site.capacity": constant(10)}, "first")
    assert publish(instance, {"site.capacity": constant(12)}, "second")["status"] == "rejected"
    historical = instance.candidate("second")
    instance.set_mode("forward")
    assert instance.candidate("second") == historical
    assert instance.query(value_query())["value"] == 10
    assert publish(instance, {"site.capacity": constant(14)}, "third")["status"] == "accepted"
    instance.set_mode("backward")
    assert publish(instance, {"site.capacity": constant(15)}, "fourth")["status"] == "rejected"
    assert instance.query(value_query())["value"] == 14


def test_default_review_hold_preserves_head_and_stale_approval_never_publishes():
    instance = Instance(mode="forward")
    base = instance.model
    for name, value in (("first", 10), ("second", 12)):
        instance.receive(
            build_candidate(
                base, {"site.capacity": constant(value)}, candidate_id=name, evidence=[evidence()]
            )
        )
    original = instance.context()
    instance.review("second", approve=True, expected_context=original)
    assert instance.decide_next()["candidate_id"] == "first"
    assert instance.model.index == {}
    instance.review("first", approve=True, expected_context=original)
    instance.set_mode("backward")
    with pytest.raises(Conflict):
        instance.review("first", approve=True, expected_context=original)
    assert instance.decide_next()["status"] == "awaiting_review"
    instance.review("first", approve=True, expected_context=instance.context())
    assert instance.decide_next()["status"] == "accepted"
    assert instance.decide_next()["status"] == "awaiting_review"  # earlier approval pinned the empty theory
    instance.review("second", approve=True, expected_context=instance.context())
    assert instance.decide_next()["status"] == "rejected"


def test_decline_releases_head_but_cannot_reconsider_a_completed_decision():
    instance = Instance()
    package = build_candidate(
        instance.model, {"site.capacity": constant(10)}, candidate_id="c", evidence=[evidence()]
    )
    instance.receive(package)
    instance.review("c", approve=False, expected_context=instance.context())
    assert instance.decide_next() is None
    with pytest.raises(Conflict):
        instance.review("c", approve=True, expected_context=instance.context())


def test_idempotent_receipt_exact_bytes_and_defensive_copy():
    instance = Instance()
    package = build_candidate(
        instance.model, {"site.capacity": constant(10)}, candidate_id="c", evidence=[evidence()]
    )
    first = instance.receive(package, review_required=False)
    first["envelope"]["proposals"].clear()
    assert instance.receive(package, review_required=False)["receipt_sequence"] == 1
    with pytest.raises(Conflict):
        instance.receive(package, review_required=True)
    changed = build_candidate(
        instance.model, {"site.capacity": constant(11)}, candidate_id="c", evidence=[evidence()]
    )
    with pytest.raises(Conflict):
        instance.receive(changed, review_required=False)
    package.attachments.clear()
    assert instance.decide_next()["status"] == "accepted"
    assert instance.query(value_query())["value"] == 10


def test_replacement_retires_dependents_and_preserves_exact_support_and_old_model():
    instance = Instance(mode="forward")
    records = [evidence("a"), evidence("b")]
    keys = [digest(encode(x)) for x in records]
    support = {"site.capacity": [keys[0]], "site.other": [keys[1]], "site.derived": [keys[0]]}
    first = publish(
        instance,
        {
            "site.capacity": constant(10),
            "site.other": constant(20),
            "site.derived": function({}, integer(0, 100), call("site.capacity")),
        },
        records=records,
        support=support,
    )
    assert set(first["decision"]["report"]["evidence"]) == set(keys)
    old = instance.model
    checked = validate_snapshot(instance.export_snapshot())
    assert {
        s: list(read_json(checked["blobs"][h])["evidence"]) for s, h in checked["support"].items()
    } == support
    publish(instance, {"site.capacity": constant(12)}, "replacement", records=[evidence("new")])
    assert "site.derived" not in instance.model.index
    assert old.call("site.derived", {})["value"] == 10
    checked = validate_snapshot(instance.export_snapshot())
    assert keys[0] not in checked["blobs"]
    assert keys[1] in checked["blobs"]


def test_stale_external_dependency_rejected_without_partial_publication():
    instance = Instance(mode="forward")
    publish(instance, {"site.capacity": constant(10)}, "first")
    base = instance.model
    publish(instance, {"site.capacity": constant(12)}, "replace")
    result = publish(
        instance, {"site.derived": function({}, integer(0, 100), call("site.capacity"))}, "stale", base=base
    )
    assert result["status"] == "rejected"
    assert "site.derived" not in instance.model.index


@pytest.mark.parametrize("mode", ["forward", "backward"])
def test_owner_policy_is_independent_of_candidate_and_mode(mode):
    instance = Instance(mode=mode, policy=capacity_policy())
    assert publish(instance, {"site.capacity": constant(12)})["status"] == "rejected"
    assert instance.model.index == {}
    assert publish(instance, {"site.capacity": constant(10)}, "good")["status"] == "accepted"
    before = instance.context()
    with pytest.raises(Rejected):
        instance.set_conformance(capacity_policy(11))
    assert instance.context() == before
    assert instance.conformance()["policy"] == capacity_policy()


@pytest.mark.parametrize("mode", ["forward", "backward"])
def test_owner_invariant_checks_future_actions_with_independent_carrier(mode):
    instance = Instance(mode=mode, policy=invariant_policy())
    assert (
        publish(instance, {"site.anchor": constant(0), "site.safe": action(1)}, "safe")["status"]
        == "accepted"
    )
    previous = instance.context()
    assert publish(instance, {"site.bad": action(2)}, "bad")["status"] == "rejected"
    assert instance.context() == previous
    assert "site.bad" not in instance.model.index
    assert publish(instance, {"site.safe2": action(0)}, "safe2")["status"] == "accepted"


def test_conformance_retraction_and_empty_carrier_cannot_weaken_requirements():
    instance = Instance(policy=capacity_policy(), mode="forward")
    publish(instance, {"site.capacity": constant(10)})
    package = build_candidate(
        instance.model, {}, candidate_id="retract", evidence=[evidence()], retractions=["site.capacity"]
    )
    instance.receive(package, review_required=False)
    assert instance.decide_next()["status"] == "rejected"
    bad = capacity_policy()
    bad["contracts"][0]["checks"][0]["params"] = {"x": {"kind": "enum", "values": []}}
    with pytest.raises(Exception) as caught:
        instance.set_conformance(bad)
    assert caught.value.code == "invalid_ir"


def test_concurrent_serving_policy_fence_and_only_one_validator():
    instance = Instance()
    package = build_candidate(
        instance.model, {"site.capacity": constant(12)}, candidate_id="c", evidence=[evidence()]
    )
    instance.receive(package, review_required=False)
    entered, release = Event(), Event()
    original = coordination.reconcile

    def delayed(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        patch.object(coordination, "reconcile", side_effect=delayed),
    ):
        future = pool.submit(instance.decide_next)
        try:
            assert entered.wait(5)
            assert (
                instance.query({"op": "evaluate", "module": "site", "expression": literal(7)})["value"] == 7
            )
            assert instance.decide_next() is None
            instance.set_conformance(capacity_policy())
        finally:
            release.set()
        assert future.result(timeout=5)["status"] == "received"
    assert instance.model.index == {}
    assert instance.decide_next()["status"] == "rejected"


def test_interruption_and_publication_failure_do_not_change_accepted_state():
    instance = Instance()
    instance.receive(
        build_candidate(
            instance.model, {"site.capacity": constant(10)}, candidate_id="c", evidence=[evidence()]
        ),
        review_required=False,
    )
    before = instance.context()
    with (
        patch.object(coordination, "reconcile", side_effect=KeyboardInterrupt),
        pytest.raises(KeyboardInterrupt),
    ):
        instance.decide_next()
    assert instance.context() == before
    assert instance.candidate("c")["status"] == "received"
    with patch.object(instance, "_publication", side_effect=ResourceLimit("test limit")):
        assert instance.decide_next()["status"] == "inconclusive"
    assert instance.context() == before


def test_exhausted_admission_query_and_retention_are_not_knowledge_gaps():
    instance = Instance(fixture("tanks"))
    result = instance.query(
        {
            "op": "find_plan",
            "module": "tanks",
            "initial_state": {"left": 0, "right": 0},
            "goal": "tanks.four_litres",
        },
        limits={"max_work": 1},
    )
    assert result["status"] == "inconclusive" and "gaps" not in result
    root = instance.context()
    assert publish(instance, {"site.capacity": constant(10)}, "extra")["status"] == "accepted"
    package = build_candidate(
        instance.model, {"site.other": constant(1)}, candidate_id="limited", evidence=[evidence()]
    )
    instance.receive(package, review_required=False)
    before = instance.context()
    assert instance.decide_next(budget=Budget(max_work=1))["status"] == "inconclusive"
    assert instance.context() == before and root != before
    limited = Instance(max_versions=1)
    assert publish(limited, {"site.capacity": constant(10)})["status"] == "inconclusive"
    assert limited.model.index == {}


@pytest.mark.parametrize(
    "decision,limit", [("owner_decline", 1800), ("policy_reject", 2000), ("publication_full", 2000)]
)
def test_full_retention_cannot_publish_an_unrecordable_decision(decision, limit):
    # Each allowance fits the immutable receipt but not its terminal audit record.
    instance = Instance(
        policy=capacity_policy() if decision == "policy_reject" else None,
        max_retained_bytes=limit,
    )
    package = build_candidate(
        instance.model, {"site.capacity": constant(12)}, candidate_id="c", evidence=[evidence()]
    )
    received = instance.receive(package, review_required=decision == "owner_decline")
    before = instance.context()
    for _ in range(2):
        with pytest.raises(ResourceLimit):
            if decision == "owner_decline":
                instance.review("c", approve=False, expected_context=instance.context())
            else:
                instance.decide_next()
        assert instance.context() == before
        assert instance.candidate("c")["status"] == received["status"]
        assert instance.candidate("c")["decision"] is None
        assert instance.info()["receipt_sequence"] == 1


def test_same_content_support_changes_without_changing_theory_and_history_is_fixed():
    instance = Instance()
    publish(instance, {"site.capacity": constant(10)}, "first", records=[evidence("first")])
    original = instance.query(value_query())
    context = instance.context()
    publish(instance, {"site.capacity": constant(10)}, "second", records=[evidence("second")])
    new = instance.context()
    assert new["theory_version"] == context["theory_version"]
    assert new["support_root"] != context["support_root"]
    assert instance.explain(original["result_id"]) == original
    current = instance.query(value_query())
    assert current["execution"]["support_root"] == new["support_root"]
    assert current["execution"]["attempt_id"] != original["execution"]["attempt_id"]


def test_missing_knowledge_and_missing_lean_are_explicit_without_jobs():
    instance = Instance()
    missing = instance.query(value_query())
    assert missing["status"] == "needs_input" and missing["error"]["code"] == "knowledge_gap"
    assert "learning_job_ids" not in missing and not instance.info()["background_learning"]
    instance = Instance(fixture("access"))
    certificate = build_certificate(
        instance.model, "access", {"tag": "closed", "value": {}}, "access.bob_access", transitions=[]
    )
    result = instance.query({"op": "check_certificate", "certificate": certificate, "backend": "lean"})
    assert result["status"] == "needs_input" and result["certificate_status"] == "unavailable"
    assert result["guarantee"] is None


def test_query_remains_pinned_while_new_theory_is_published():
    instance = Instance(mode="forward")
    publish(instance, {"site.capacity": constant(10)}, "first")
    old = instance.context()
    original = coordination.execute

    def concurrent(model, query, limits, **options):
        publish(instance, {"site.capacity": constant(12)}, "second")
        return original(model, query, limits, **options)

    with patch.object(coordination, "execute", side_effect=concurrent):
        result = instance.query(value_query())
    assert result["value"] == 10
    assert result["execution"]["theory_version"] == old["theory_version"]
    assert result["binding"]["theory_version"] == old["theory_version"]
    assert instance.query(value_query())["value"] == 12


@pytest.mark.parametrize("field", ["theory_version", "query", "digest"])
def test_wrong_internal_result_binding_cannot_enter_history(field):
    instance = Instance()
    result = instance.query({"op": "capabilities"})
    result["binding"][field] = {} if field == "query" else "sha256:" + "0" * 64
    with patch.object(coordination, "execute", return_value=result), pytest.raises(StorageError):
        instance.query({"op": "capabilities"})


def test_policy_installation_is_fenced_and_publication_preparation_rolls_back():
    instance = Instance()
    original = coordination.verify_policy

    def change_mode(source, model, **options):
        instance.set_mode("forward")
        return original(source, model, **options)

    with patch.object(coordination, "verify_policy", side_effect=change_mode), pytest.raises(Conflict):
        instance.set_conformance(capacity_policy())
    assert instance.conformance()["policy"]["contracts"] == []
    instance.receive(
        build_candidate(
            instance.model, {"site.capacity": constant(10)}, candidate_id="c", evidence=[evidence()]
        ),
        review_required=False,
    )
    context = instance.context()
    with (
        patch.object(instance, "_publication", side_effect=RuntimeError("injected pre-commit failure")),
        pytest.raises(RuntimeError),
    ):
        instance.decide_next()
    assert instance.context() == context
    assert instance.candidate("c")["status"] == "received"
    assert instance.decide_next()["status"] == "accepted"


def test_complete_reservation_fixture_passes_independent_owner_contract():
    import json
    from pathlib import Path

    from awm_adm.engine.provider_format import decode_proposal

    from .ported.provider_fixtures import reservations_proposal

    policy = json.loads(
        (Path(__file__).parent / "fixtures/v1/learning/reservations.conformance.json").read_text()
    )
    decoded = decode_proposal(reservations_proposal(), Budget())
    declarations = {item["symbol"]: item["body"] for item in decoded["declarations"]}
    instance = Instance(policy=policy)
    decision = publish(instance, declarations)
    assert decision["status"] == "accepted"
    assert (
        sum(
            check["cases"]
            for contract in decision["decision"]["report"]["conformance"]["contracts"]
            for check in contract["checks"]
        )
        == 1608
    )
    checked = validate_snapshot(instance.export_snapshot())
    assert checked["conformance"] == policy
