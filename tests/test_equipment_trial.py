"""practical fixture rehearsal, with authored responses and zero remote calls."""

import json
from pathlib import Path
from uuid import uuid4

from awm_adm.engine import Instance
from awm_adm.runtime.protocol import pack

from .test_application import app_runtime, execute  # noqa: F401
from .test_language_service import consent, conversation, finish, interpret
from .test_learning_service import advance, approve, connection, dispatch, rig  # noqa: F401
from .test_sources import project

FIXTURE = Path(__file__).parents[1] / "examples/equipment"


def fixture(name):
    return json.loads((FIXTURE / name).read_text())


def test_empty_equipment_acquisition_checks_all_cases_and_serves_locally(rig):  # noqa: F811
    rt, gateway = rig
    key = rt.create(
        "equipment", snapshot=pack(Instance(policy=fixture("requirements.json")).export_snapshot())
    )["id"]
    expected = fixture("expected.json")
    query = expected["translation_query"]
    assert rt.query(key, query)["result"]["status"] == "needs_input"
    c = connection(rt, gateway, [fixture("recorded-acquisition.json")])
    ep = rt.learning.create(
        key,
        {
            "idempotency_key": str(uuid4()),
            "expected_revision": rt.store.info(key)["revision_id"],
            "connection_id": c["id"],
            "connection_version": c["version"],
            "task": fixture("task.json"),
        },
    )
    advance(rt, key, ep["id"], "acquiring")
    assert rt.query(key, {"op": "capabilities"})["result"]["status"] == "succeeded"
    dispatch(rt, gateway)
    held = advance(rt, key, ep["id"], "awaiting_review")
    assert rt.query(key, query)["result"]["status"] == "needs_input"
    approve(rt, key, held)
    for case in expected["truth_table"]:
        expression = {
            "op": "call",
            "function": "equipment.can_borrow",
            "args": {k: {"op": "literal", "value": case[k]} for k in ("borrowed", "available")},
        }
        result = rt.query(key, {"op": "evaluate", "module": "equipment", "expression": expression})["result"]
        assert result["status"] == "succeeded" and result["value"] is case["expected"]
    turn = finish(rt, key, interpret(rt, key, conversation(rt, key), expected["local_command"])["id"])
    assert turn["draft"]["query"] == query
    consent(rt, key, turn)
    assert execute(rt, key)["status"] == "succeeded"
    unsupported = finish(
        rt, key, interpret(rt, key, conversation(rt, key), "Will more cameras arrive tomorrow?")["id"]
    )
    assert unsupported["status"] != "ready" and (
        not unsupported["draft"] or not unsupported["draft"]["query"]
    )
    assert rt.learning.usage()["calls"] == 1  # One recorded grant, no remote transport.


def test_equipment_history_modes_and_correction_preserve_independent_borrowing(app_runtime):  # noqa: F811
    rt = app_runtime
    key = rt.create("equipment history", snapshot=fixture("authored-snapshot.adm"))["id"]
    rt.sources.set_policy(
        key,
        {
            "expected_revision": rt.store.info(key)["revision_id"],
            "expected_generation": 0,
            **fixture("source-policy.json"),
        },
    )

    def ingest(name, item=None, version="v1", supersedes=None):
        source = {
            "source_id": "equipment-register",
            "item_id": item or str(uuid4()),
            "version_id": version,
            "media_type": "application/json",
            "origin": "Authored equipment fixture",
            "content": (FIXTURE / name).read_text(),
            "supersedes_version": supersedes,
        }
        rt.sources.ingest(key, {"idempotency_key": str(uuid4()), "items": [source]})
        return source

    def lookup(year):
        rt.coordinator.submit(
            key,
            {
                "idempotency_key": str(uuid4()),
                "query": {
                    "op": "lookup_fact",
                    "entity_id": "camera-kit",
                    "predicate": "equipment.capacity",
                    "effective_at": f"{year}-06-01T00:00:00Z",
                },
            },
        )
        return execute(rt, key)

    assert project(rt, key, ingest("history-2026.json"))["status"] == "accepted"
    assert project(rt, key, ingest("history-2025.json"))["status"] == "accepted"
    assert lookup(2025)["result"]["value"]["value"] == 2
    assert lookup(2026)["result"]["value"]["value"] == 1
    assert lookup(2027)["status"] == "needs_input"
    conflict = ingest("history-2026-conflict.json")
    assert project(rt, key, conflict)["status"] == "rejected"
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    assert lookup(2026)["result"]["value"]["value"] == 1
    assert project(rt, key, conflict)["status"] == "accepted"
    historical_result = lookup(2026)
    assert historical_result["result"]["value"]["value"] == 2
    correction = ingest("history-2026-correction.json", conflict["item_id"], "v2", "v1")
    assert lookup(2026)["status"] == "needs_input"
    assert rt.store.request(key, historical_result["request_id"])["result"] == historical_result["result"]
    assert project(rt, key, correction)["status"] == "accepted"
    assert lookup(2026)["result"]["value"]["value"] == 1
    assert rt.query(key, fixture("expected.json")["translation_query"])["result"]["status"] == "succeeded"
    assert rt.learning.usage()["calls"] == 0
