"""Capture ordinary public API contracts from isolated, synthetic service state."""

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from awm_adm.application.http import Change, Create
from awm_adm.application.models import Operation, RequestView
from awm_adm.contracts import ErrorEnvelope
from awm_adm.interaction.models import DirectMessage

from .interaction_support import definition, narration, proposal, reply
from .test_application import app_runtime as app_runtime
from .test_application import client, execute, tank
from .test_direct_ask import interpreted, recorded, work
from .test_direct_teach import has_ready, preparation, pump
from .test_learning_service import rig as rig


def retain(name, value):
    """Opt-in evidence outside release sources, never inspect normal service data."""
    if destination := os.environ.get("ADM_PLUGIN_CONTRACT_OUTPUT"):
        path = Path(destination)
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{name}.json").write_text(json.dumps(value, indent=2) + "\n")


def validate(kind, value):
    schema = json.loads((Path(__file__).parents[1] / "contracts/project-plugin-api.schema.json").read_text())
    Draft202012Validator({**schema, "$ref": f"#/$defs/{kind}"}).validate(value)


def test_subset_reuses_existing_typed_contracts_exactly():
    schema = json.loads((Path(__file__).parents[1] / "contracts/project-plugin-api.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    for model in (Create, Change, DirectMessage, Operation, RequestView, ErrorEnvelope):
        expected = model.model_json_schema(ref_template="#/$defs/{model}")
        for key, value in expected.pop("$defs", {}).items():
            assert schema["$defs"][key] == value
        assert schema["$defs"][model.__name__] == expected


def test_create_settings_reads_and_local_boundary(app_runtime):
    rt = app_runtime
    with client(rt) as c:
        body = {"idempotency_key": "fixture-create", "name": "Synthetic project", "mode": "backward"}
        received = c.post("/api/v1/adms", json=body)
        assert received.status_code == 202
        operation = received.json()
        validate("Create", body)
        validate("Operation", operation)
        assert operation["status"] == "received" and operation["adm_id"] is None
        assert rt.coordinator.run_operation()
        done = c.get(f"/api/v1/operations/{operation['operation_id']}").json()
        assert done["status"] == "succeeded"
        key = done["adm_id"]
        before = c.get(f"/api/v1/adms/{key}").json()
        assert before["mode"] == "backward"
        settings = {"expected_epoch": before["policy_epoch"], "mode": "forward"}
        changed = c.patch(f"/api/v1/adms/{key}/settings", json=settings)
        assert changed.status_code == 200
        validate("ModelInfo", before)
        validate("Change", settings)
        validate("ModelInfo", changed.json())
        validate("Operation", done)
        stale = c.patch(f"/api/v1/adms/{key}/settings", json={**settings, "mode": "backward"})
        assert stale.status_code == 409
        knowledge = c.get(f"/api/v1/adms/{key}/knowledge").json()
        assert knowledge["items"] == [] and knowledge["next_cursor"] is None
        disabled = c.post(f"/api/v1/adms/{key}/ask", json={"text": "What do we know?"})
        assert disabled.status_code == 403
        validate("KnowledgePage", knowledge)
        validate("ErrorEnvelope", stale.json())
        validate("ErrorEnvelope", disabled.json())
        unauthenticated = c.get(f"/api/v1/adms/{key}", headers={"Authorization": ""})
        assert unauthenticated.status_code == 200
        hostile = c.get(f"/api/v1/adms/{key}", headers={"Origin": "https://other.example"})
        assert hostile.status_code == 403
        retain(
            "management",
            {
                "create_request": body,
                "create_received": operation,
                "create_completed": done,
                "model": before,
                "settings_request": settings,
                "settings_response": changed.json(),
                "stale_error": stale.json(),
                "knowledge_empty": knowledge,
                "disabled_error": disabled.json(),
                "local_model_read": unauthenticated.json(),
            },
        )


def test_actual_ask_envelope_contains_bound_local_result(rig):
    rt, gateway = rig
    key = tank(rt)
    recorded(rt, gateway, proposal('plan tanks to tanks.four_litres from {"left":0,"right":0}'))
    message = {"text": "How can I get four litres?", "idempotency_key": "fixture-ask"}
    item = interpreted(rt, gateway, key, **message)
    local_pending = rt.interactions.get(key, item["id"])
    request = execute(rt, key)
    rt.conversations.ask.tick()
    narration(rt, work(rt, key, item["id"]))
    with client(rt) as c:
        answer = c.get(f"/api/v1/adms/{key}/interactions/{item['id']}").json()
        assert answer["status"] == "completed"
        assert answer["outcome"]["status"] == "succeeded"
        assert answer["request_id"] == request["request_id"]
        checked = c.get(f"/api/v1/adms/{key}/requests/{answer['request_id']}").json()
        assert answer["result_id"] == checked["result"]["result_id"]
        validate("DirectMessage", message)
        for value in (item, local_pending, answer):
            validate("Interaction", value)
        validate("RequestView", checked)
        retain(
            "ask",
            {
                "request": message,
                "received": item,
                "pending": local_pending,
                "completed": answer,
                "bound_request": checked,
            },
        )


def test_teach_completion_has_receipt_steps_but_not_a_normalized_conflict_outcome(rig):
    rt, gateway = rig
    key, uid = preparation(rt, gateway)
    pump(rt, key, uid, lambda _: has_ready(rt))
    reply(rt, definition())
    task = pump(rt, key, uid, lambda t: t["execution"]["phase"] == "narration")
    run = task["execution"]
    reply(
        rt,
        {
            "packet_digest": run["packet_digest"],
            "accepted_ids": run["summary"]["accepted_ids"],
            "unresolved_ids": [],
            "explanation": "The rule is ready.",
            "authority": "explanation_only",
        },
    )
    pump(rt, key, uid, lambda t: t["status"] == "succeeded")
    with client(rt) as c:
        result = c.get(f"/api/v1/adms/{key}/interactions/{uid}").json()
        assert result["teaching"]["steps"][0]["status"] == "accepted"
        assert result["teaching"]["summary"]["accepted_ids"]
        assert result["outcome"] is None  # Teach is not an Ask result envelope.
        knowledge = c.get(f"/api/v1/adms/{key}/knowledge").json()
        assert knowledge["items"]
        validate("Interaction", result)
        validate("KnowledgePage", knowledge)
        retain("teach", {"completed": result, "knowledge": knowledge})


@pytest.mark.parametrize("status", ["needs_clarification", "unsupported", "needs_learning"])
def test_no_executable_meaning_creates_no_local_request_or_learning(rig, status):
    rt, gateway = rig
    key = tank(rt)
    recorded(rt, gateway, proposal(status=status, clarification="Please specify the intended scope."))
    item = interpreted(rt, gateway, key, "An underspecified synthetic question")
    result = rt.interactions.get(key, item["id"])
    validate("Interaction", result)
    assert result["status"] == ("needs_input" if status == "needs_clarification" else status)
    assert result["request_id"] is None and result["outcome"] is None
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM episodes").fetchone()[0] == 0
    retain(status, result)


def test_partial_teach_keeps_success_and_does_not_claim_failed_objective(rig):
    rt, gateway = rig

    def two_children(plan):
        second = deepcopy(plan["children"][0])
        second["objective"] = "A second bounded function"
        second["interfaces"] = {"math.other": second["interfaces"]["math.double"]}
        plan["children"].append(second)

    key, uid = preparation(rt, gateway, mutate=two_children)
    pump(rt, key, uid, lambda _: has_ready(rt))
    reply(rt, definition())
    pump(rt, key, uid, lambda _: has_ready(rt))
    for attempt in range(2):
        bad = definition()
        item = bad["result"]["definitions"].pop("math.double")
        item["body"] = {"op": "literal", "value": 9999}
        bad["result"]["definitions"]["math.other"] = item
        reply(rt, bad)
        current = pump(rt, key, uid, lambda _: has_ready(rt))
    run = current["execution"]
    assert run["phase"] == "narration"
    assert run["summary"]["status"] == "partially_succeeded"
    reply(
        rt,
        {
            "packet_digest": run["packet_digest"],
            "accepted_ids": run["summary"]["accepted_ids"],
            "unresolved_ids": run["summary"]["unresolved_ids"],
            "explanation": "The first rule was learned; the second is unresolved.",
            "authority": "explanation_only",
        },
    )
    pump(rt, key, uid, lambda t: bool(t["execution"].get("delivered")))
    result = rt.interactions.get(key, uid)
    validate("Interaction", result)
    assert result["status"] == "partially_succeeded"
    assert len(result["teaching"]["summary"]["accepted_ids"]) == 1
    assert len(result["teaching"]["summary"]["unresolved_ids"]) == 1
    assert (
        rt.query(
            key,
            {
                "op": "evaluate",
                "module": "math",
                "expression": {
                    "op": "call",
                    "function": "math.double",
                    "args": {"n": {"op": "literal", "value": 3}},
                },
            },
        )["result"]["value"]
        == 6
    )
    retain("partial_teach", result)
