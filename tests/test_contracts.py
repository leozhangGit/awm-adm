import copy
import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from awm_adm.contracts import (
    SCHEMAS,
    CallLimits,
    ContextBinding,
    DispatchGrant,
    DispatchOutcome,
    FactClaim,
    FindPlan,
    IntentDraft,
    Request,
    RequestRecord,
    TemporalScope,
)
from awm_adm.schemas import documents, export_schemas
from awm_adm.wire import canonical, decode

ROOT = Path(__file__).resolve().parents[1]
DIGEST = "sha256:" + "0" * 64
CONTEXT = {"adm_id": "adm-a", "theory_root": DIGEST, "policy_epoch": 0}


def example(name):
    return json.loads((ROOT / "contracts/examples" / (name + ".json")).read_text())


@pytest.mark.parametrize(
    "model_name,filename",
    [
        ("Request", "capabilities-request"),
        ("Request", "plan-request"),
        ("RequestRecord", "successful-request"),
        ("RequestRecord", "pending-request"),
        ("RequestRecord", "exhausted-request"),
        ("IntentDraft", "clarification"),
        ("ErrorEnvelope", "provider-unavailable"),
        ("FactClaim", "historical-fact"),
        ("SourceRecord", "source-record"),
        ("WorkerLease", "worker-lease"),
        ("DispatchGrant", "dispatch-grant"),
        ("DispatchOutcome", "unknown-dispatch"),
        ("Event", "pending-event"),
    ],
)
def test_published_examples_validate_as_schema_and_models(model_name, filename):
    value = example(filename)
    schema = json.loads(documents()[model_name + ".schema.json"])
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(value)
    model = SCHEMAS[model_name].model_validate(value)
    assert SCHEMAS[model_name].model_validate(decode(canonical(model.model_dump(mode="json")))) == model


def test_schema_exports_are_current_and_closed():
    export_schemas(ROOT / "contracts/schemas", check=True)
    for raw in documents().values():
        schema = json.loads(raw)
        assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b"\xff", b"{", b'"' + b"a" * 2_097_152 + b'"']
)
def test_reject_ambiguous_or_oversized_json(raw):
    with pytest.raises(ValueError):
        decode(raw)


def test_bounded_nested_payload():
    with pytest.raises(ValueError):
        decode(b"[" * 40 + b"0" + b"]" * 40)
    with pytest.raises(ValueError):
        canonical({"data": float("nan")})


@pytest.mark.parametrize("bad", [True, 0, -1, "5000", 1.2, None, 3_600_001])
def test_request_limits_are_strict(bad):
    value = example("capabilities-request")
    value["limits"]["max_duration_ms"] = bad
    with pytest.raises(ValidationError):
        Request.model_validate(value)


def test_selection_intent_preserves_empty_list_vs_module_all():
    value = example("plan-request")["query"]
    all_actions = FindPlan.model_validate(value)
    no_actions = FindPlan.model_validate({**value, "transitions": []})
    assert all_actions.transitions is None
    assert no_actions.transitions == []
    assert canonical(all_actions.model_dump()) != canonical(no_actions.model_dump())
    with pytest.raises(ValidationError):
        FindPlan.model_validate({**value, "transitions": ["fixture.step", "fixture.step"]})


def test_envelopes_cannot_smuggle_authority():
    value = example("capabilities-request")
    for field in ("mode", "api_key", "approved", "provider", "budget_override"):
        with pytest.raises(ValidationError):
            Request.model_validate({**value, field: "untrusted"})
    with pytest.raises(ValidationError):
        Request.model_validate({**value, "query": {"op": "set_mode", "mode": "forward"}})


def test_result_binding_and_status_are_coherent():
    value = example("successful-request")
    for field, bad in (
        ("adm_id", "other"),
        ("request_id", "other"),
        ("attempt_id", "other"),
        ("status", "waiting_for_learning"),
    ):
        with pytest.raises(ValidationError):
            RequestRecord.model_validate({**value, field: bad})
    with pytest.raises(ValidationError):
        RequestRecord.model_validate({"adm_id": "a", "request_id": "r", "status": "succeeded"})


@pytest.mark.parametrize(
    "claims,lean,finite",
    [
        (["shortest_action_count"], "not_requested", "not_checked"),
        (["unreachable", "valid_witness"], "checked", "checked"),
        (["unreachable"], "not_requested", "not_checked"),
        (["value"], "checked", "failed"),
    ],
)
def test_result_cannot_combine_incompatible_assurance_claims(claims, lean, finite):
    value = example("successful-request")
    value["result"].update(claims=claims, lean_kernel=lean, exhaustive_finite=finite)
    with pytest.raises(ValidationError):
        RequestRecord.model_validate(value)


def test_result_cannot_drop_explicit_action_selection():
    value = example("successful-request")
    value["result"]["binding"]["selection"] = {"kind": "explicit", "actions": ["fixture.advance"]}
    with pytest.raises(ValidationError):
        RequestRecord.model_validate(value)


def test_translation_is_not_execution_authority():
    value = example("clarification")
    with pytest.raises(ValidationError):
        IntentDraft.model_validate({**value, "status": "ready"})
    with pytest.raises(ValidationError):
        IntentDraft.model_validate({**value, "translator": "external"})
    with pytest.raises(ValidationError):
        IntentDraft.model_validate({**value, "approved": True})
    ready = {**value, "status": "ready", "query": {"op": "capabilities"}, "clarification": None}
    assert IntentDraft.model_validate(ready).status == "ready"


def test_unknown_call_cannot_claim_settled_usage_or_response():
    for extra in ({"usage": {"input_tokens": 0, "output_tokens": 0}}, {"response_digest": DIGEST}):
        with pytest.raises(ValidationError):
            DispatchOutcome.model_validate({**example("unknown-dispatch"), **extra})
    with pytest.raises(ValidationError):
        CallLimits(max_calls=True)


def test_grant_binds_configuration_and_lease_scope():
    value = example("dispatch-grant")
    with pytest.raises(ValidationError):
        DispatchGrant.model_validate({**value, "model": "override"})
    value["lease"]["expires_at_ms"] = value["lease"]["issued_at_ms"]
    with pytest.raises(ValidationError):
        DispatchGrant.model_validate(value)
    value = example("dispatch-grant")
    value["lease"].update(purpose="connection_test", context=None, control_scope_id="installation-a")
    assert DispatchGrant.model_validate(value).lease.context is None
    value["lease"]["purpose"] = "acquisition"
    with pytest.raises(ValidationError):
        DispatchGrant.model_validate(value)


@pytest.mark.parametrize(
    "changes",
    [
        {"effective_to": "2019-01-01T00:00:00Z"},
        {"effective_from": "2020-02-30T00:00:00Z"},
        {"effective_from": "2020-01-01"},
        {"kind": "unknown"},
        {"effective_from": None},
    ],
)
def test_temporal_scope_does_not_invent_valid_dates(changes):
    value = example("historical-fact")["temporal_scope"]
    with pytest.raises(ValidationError):
        TemporalScope.model_validate({**value, **changes})


def test_history_and_receipt_are_distinct():
    old = FactClaim.model_validate(example("historical-fact"))
    newer = copy.deepcopy(old.model_dump())
    newer.update(
        claim_id="claim-2024",
        value={"kind": "integer", "value": 12},
        temporal_scope={
            "kind": "interval",
            "granularity": "year",
            "effective_from": "2024-01-01T00:00:00Z",
            "effective_to": None,
        },
    )
    new = FactClaim.model_validate(newer)
    assert old.temporal_scope != new.temporal_scope
    assert "received_at_ms" not in old.temporal_scope.model_dump()
    with pytest.raises(ValidationError):
        FactClaim.model_validate({**newer, "status": "accepted"})


def test_fact_boolean_is_not_an_integer_and_source_span_is_nonempty():
    value = example("historical-fact")
    value["value"]["value"] = True
    with pytest.raises(ValidationError):
        FactClaim.model_validate(value)
    value = example("historical-fact")
    value["source"]["end_byte"] = value["source"]["start_byte"]
    with pytest.raises(ValidationError):
        FactClaim.model_validate(value)


def test_context_identifiers_cannot_be_filesystem_paths():
    with pytest.raises(ValidationError):
        ContextBinding.model_validate({**CONTEXT, "adm_id": "../../v1"})
