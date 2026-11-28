"""Information gaps are resumable; capability limits are distinct. No live provider."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from awm_adm.engine import Budget
from awm_adm.runtime.protocol import dumps
from awm_adm.runtime.service import Runtime
from awm_adm.teaching.compute import compute
from awm_adm.teaching.prompt import specification
from awm_adm.teaching.provider_format import response_schema
from awm_adm.teaching.readiness import LEGACY_PROFILE, TEMPORAL_PROFILE

from .interaction_support import plan, respond, uploaded
from .teaching_wire import assessed_reply, native_reply, temporal_reply
from .test_application import app_runtime as app_runtime
from .test_direct_ask import recorded, work
from .test_learning_service import rig as rig
from .test_teaching_format import check, proposed, task


def gap(input_id="turn-one", kind="temporal_scope", **changes):
    return {
        "profile": TEMPORAL_PROFILE,
        "message": "The request is unsupported without the missing information.",
        "missing_information": [
            {
                "kind": kind,
                "input_ids": [input_id],
                "subject": "The requested reporting period",
                "detail": "Its start is absent.",
            }
        ],
        "unsupported_capabilities": [],
        "question": "When does that reporting period begin?",
        "plan": None,
        **changes,
    }


def unsupported(input_id="turn-one", **changes):
    return gap(
        input_id,
        missing_information=[],
        question=None,
        unsupported_capabilities=[
            {
                "kind": "unbounded_domain",
                "input_ids": [input_id],
                "requested_capability": "A decision procedure over all integers",
                "limitation": "This contract requires a bounded finite carrier.",
            }
        ],
        **changes,
    )


def evaluate(reply):
    request = task(reply)
    request["reply_format"] = reply["profile"]
    return compute(request, Budget(1000000, 5))


@pytest.mark.parametrize("profile", [TEMPORAL_PROFILE, LEGACY_PROFILE])
@pytest.mark.parametrize(
    "kind,subject,detail,question",
    [
        ("temporal_scope", "Reporting period", "Missing start", "When does the period begin?"),
        ("entity", "Machine identifier", "Two machines match", "Which machine does this refer to?"),
        ("unit", "Distance measurement", "No unit supplied", "What unit is this distance in?"),
        (
            "representation_bounds",
            "Queue size",
            "No maximum supplied",
            "What maximum queue size should this cover?",
        ),
        (
            "source_material",
            "Inspection result",
            "Referenced report absent",
            "Can you provide the inspection report?",
        ),
        (
            "adoption_intent",
            "Suggested rule",
            "Only a tentative example",
            "Should this become a rule of this model?",
        ),
    ],
)
def test_gap_routes_by_structure_not_explanatory_prose(profile, kind, subject, detail, question):
    value = gap(kind=kind, profile=profile, question=question)
    value["missing_information"][0].update(subject=subject, detail=detail)
    result = evaluate(value)
    assert result["reply"]["status"] == "needs_clarification"
    assert result["reply"]["message"] == question
    assert result["reply"]["assessment"]["classification_authority"] == "provider_proposed"
    assert "plan" not in result and "contracts" not in result


@pytest.mark.parametrize(
    "kind", ["unsupported_operation", "unsupported_representation", "unbounded_domain", "resource_limit"]
)
def test_capability_limit_is_distinct_and_does_not_create_a_question(kind):
    value = unsupported()
    value["unsupported_capabilities"][0]["kind"] = kind
    result = evaluate(value)["reply"]
    assert result["status"] == "unsupported"
    assert result["assessment"]["kind"] == "unsupported_capability"
    assert result["assessment"]["question"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"question": None},
        {"question": "   "},
        {"missing_information": []},
        {"unsupported_capabilities": unsupported()["unsupported_capabilities"]},
        {"status": "unsupported"},
        {"allow_external": True},
        {"plan": proposed()["plan"]},
    ],
)
def test_inconsistent_assessment_stops_without_learning(change):
    value = gap(profile=LEGACY_PROFILE, **change)
    result = evaluate(value)
    assert "failure" in result and "reply" not in result and "plan" not in result
    assert result["failure"]["stage"] == "assessment"


@pytest.mark.parametrize("ids", [["not-an-input"], ["turn-one", "turn-one"]])
def test_gaps_cannot_refer_to_unknown_or_duplicate_inputs(ids):
    value = gap()
    value["missing_information"][0]["input_ids"] = ids
    assert evaluate(value)["failure"]["code"] == "unknown_assessment_input"


def test_ready_plan_has_identical_validation_and_never_uses_a_relaxed_checker():
    old = proposed()
    new = assessed_reply(old, ["turn-one"], temporal=False)
    before, after = check(old), evaluate(new)
    assert before["plan"] == after["plan"] and before["contracts"] == after["contracts"]
    for mutate in (
        lambda p: p["types"][0].update(minimum=100, maximum=0),
        lambda p: p["children"][0].update(input_ids=["foreign-input"]),
        lambda p: p["children"][0]["interfaces"][0].update(returns_id="missing-type"),
        lambda p: p.update(requirements_json='{"arbitrary":"invalid"}'),
    ):
        left, right = deepcopy(old), deepcopy(new)
        mutate(left["plan"])
        mutate(right["plan"])
        assert check(left)["failure"] == evaluate(right)["failure"]
    new["question"] = "Proceed?"
    assert evaluate(new)["failure"]["code"] == "ready_requires_plan"


def test_historical_unsupported_reply_is_not_reinterpreted_or_retried():
    value = {
        "profile": "awm-adm-teaching-reply/2",
        "status": "unsupported",
        "message": "Missing a date",
        "plan": None,
    }
    assert check(value)["reply"]["status"] == "unsupported"
    value["profile"] = LEGACY_PROFILE
    assert evaluate(value)["failure"]["stage"] == "assessment"


@pytest.mark.parametrize("temporal", [False, True])
def test_published_schema_preserves_ready_plan_and_is_model_neutral(temporal):
    old = response_schema(temporal_evidence=temporal)
    current = response_schema(temporal_evidence=temporal, assessed=True)

    def grammar(node):
        if isinstance(node, dict):
            return {k: grammar(v) for k, v in node.items() if k != "description"}
        if isinstance(node, list):
            return [grammar(v) for v in node]
        return node

    assert grammar(current["properties"]["plan"]) == grammar(old["properties"]["plan"])
    assert "status" not in current["properties"]
    Draft202012Validator.check_schema(current)
    filename = (
        "teaching-readiness-reply.schema.json" if temporal else "teaching-legacy-readiness-reply.schema.json"
    )
    assert current == json.loads((Path(__file__).parents[1] / "contracts" / filename).read_text())
    task = {"objective": "A bounded objective", "inputs": [], "temporal_context": {}}
    if temporal:
        task["material_manifest"] = {"entries": []}
    a = specification(task, {}, {}, None)
    b = specification({**task, "provider_model": "different-model"}, {}, {}, None)
    a["context"]["temporal_context"] = b["context"]["temporal_context"]
    assert a == b and a["schema"] == response_schema(
        temporal_evidence=temporal, assessed=True, reaffirmation=True
    )
    assert "Missing meaning requires clarification or unsupported" not in a["instructions"]
    assert "Missing meaning requires clarification or unsupported" not in dumps(current).decode()
    for term in ("nvidia", "parcel", "equipment", "gpt-", "claude"):
        assert term not in a["instructions"].lower()


def test_gap_survives_restart_and_continues_original_material_without_premature_work(rig):
    rt, gw = rig
    key = rt.create("Clarification persistence")["id"]
    recorded(rt, gw, {})
    attachment = uploaded(rt, key, content="Adopt a bounded doubling rule. Its domain is not yet specified.")
    submitted = {
        "text": "Use the attached rule.",
        "attachments": [attachment["id"]],
        "idempotency_key": "first",
    }
    first = rt.interactions.submit(key, "teach", submitted)
    before = rt.store.info(key)
    assert rt.conversations.teaching.tick()
    value = gap(
        work(rt, key, first["id"])["turn_id"],
        kind="representation_bounds",
        question="What whole-number range should the doubling rule cover?",
    )
    respond(rt, value)
    result = rt.interactions.get(key, first["id"])
    assert result["status"] == "needs_input" and result["reply"] == value["question"]
    assert result["preparation_assessment"]["kind"] == "missing_information"
    assert rt.store.info(key) == before
    assert rt.interactions.submit(key, "teach", submitted)["id"] == first["id"]
    assert not rt.conversations.tick() and rt.learning.claim() is None
    assert rt.learning.usage()["calls"] == 1
    with rt.store.db(key) as db:
        for table in ("episodes", "requests", "learning_receipts"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert rt.sources.versions(key) == []
    rt.close()
    restored = Runtime(rt.config, start_scheduler=False)
    try:
        assert (
            restored.interactions.get(key, first["id"])["preparation_assessment"]
            == result["preparation_assessment"]
        )
        second = restored.interactions.submit(
            key,
            "teach",
            {"text": "Inputs zero through five; outputs zero through ten.", "reply_to": first["id"]},
        )
        task = restored.conversations.teaching.get(key, second["id"])
        assert len(task["inputs"]) == 2 and task["question"] == value["question"]
        assert any(e["kind"] == "upload" for e in task["material_manifest"]["entries"])
        assert restored.conversations.teaching.tick()
        old = native_reply(
            {
                "status": "ready",
                "message": "The range is now explicit.",
                "plan_json": dumps(plan([i["id"] for i in task["inputs"]])).decode(),
            }
        )
        ready = assessed_reply(
            temporal_reply(old, task["material_manifest"]), [i["id"] for i in task["inputs"]]
        )
        respond(restored, ready)
        prepared = restored.conversations.teaching.get(key, second["id"])
        assert prepared["status"] == "queued", prepared
        assert prepared["preparation_assessment"]["kind"] == "ready"
        assert restored.learning.usage()["calls"] == 2
        assert restored.store.info(key) == before  # Preparation has not admitted a definition.
    finally:
        restored.close()


@pytest.mark.parametrize("invalid", [False, True])
def test_limit_or_invalid_assessment_does_not_create_a_clarification_or_retry(rig, invalid):
    rt, gw = rig
    key = rt.create("Terminal assessment")["id"]
    recorded(rt, gw, {})
    first = rt.interactions.submit(key, "teach", {"text": "Decide a rule over every integer."})
    before = rt.store.info(key)
    assert rt.conversations.teaching.tick()
    value = unsupported(work(rt, key, first["id"])["turn_id"])
    if invalid:
        value["question"] = "Missing date?"
    respond(rt, value)
    result = rt.interactions.get(key, first["id"])
    assert result["status"] == ("failed" if invalid else "unsupported")
    assert not result.get("pending_question")
    assert rt.store.info(key) == before and rt.learning.usage()["calls"] == 1
    assert not rt.conversations.tick() and rt.learning.claim() is None
