"""Ordinary Enable → Teach → Ask journey through simulated provider transport."""

import runpy
from pathlib import Path
from uuid import uuid4

from awm_adm.engine import Instance
from awm_adm.runtime.protocol import dumps, loads, pack

from .test_application import app_runtime as app_runtime
from .test_application import execute
from .test_equipment_trial import fixture
from .test_learning_service import rig as rig
from .test_provider_transports import raw, response
from .test_single_connection import queued, success

ROOT = Path(__file__).parents[1] / "examples/teaching"
recorded_reply = runpy.run_path(str(ROOT.parents[1] / "scripts/equipment_provider.py"))["recorded_reply"]


def run_trial(rt, gw, tmp_path):
    gw.transport = success
    _, test = queued(rt, gw)
    gw.dispatch(test["grant_id"], test["lease"])
    rt.learning.connection_manager.tick()
    assert rt.learning.connection_manager.view()["state"] == "enabled"
    calls = []

    def transport(provider, wire, credential, timeout):
        assert provider == "openai" and credential == "synthetic-test-secret"
        calls.append(loads(wire)["text"]["format"]["name"])
        result = response("openai", model="owner-selected-model")
        result["output"][0]["content"][0]["text"] = dumps(recorded_reply(wire)).decode()
        return 200, raw(result)

    gw.transport = transport
    key = rt.create(
        "Equipment teaching rehearsal",
        snapshot=pack(Instance(policy=fixture("requirements.json")).export_snapshot()),
    )["id"]
    s = rt.conversations
    attachment = s.intake.upload(
        key,
        {
            "idempotency_key": str(uuid4()),
            "name": "history.md",
            "media_type": "text/markdown",
            "content": (ROOT / "history.md").read_text(),
        },
    )
    submitted = rt.interactions.submit(
        key, "teach", {"text": (ROOT / "teach.txt").read_text(), "attachments": [attachment["id"]]}
    )
    uid = submitted["id"]

    def tick():
        s.tick()
        rt.learning.tick()
        rt.sources.tick()
        job = rt.learning.claim()
        if job:
            gw.dispatch(job["grant_id"], job["lease"])

    for _ in range(100):
        tick()
        task = s.teaching.get(key, uid)
        assert task["status"] != "awaiting_decision"
        if task["status"] == "succeeded":
            break
    assert task["status"] == "succeeded", task
    assert len(task["execution"]["summary"]["accepted"]) == 2
    assert len(calls) == 4
    feed = rt.sources.feeds.overview(key)["feeds"][0]
    assert feed["body"]["budget"]["max_input_tokens"] > 0
    for case in fixture("expected.json")["truth_table"]:
        query = {
            "op": "evaluate",
            "module": "equipment",
            "expression": {
                "op": "call",
                "function": "equipment.can_borrow",
                "args": {n: {"op": "literal", "value": case[n]} for n in ("borrowed", "available")},
            },
        }
        assert rt.query(key, query)["result"]["value"] is case["expected"]
    outcomes = []
    for text, expected in (
        ("Can I borrow one more item if I have one and one is available?", True),
        ("What was camera-kit capacity at 2026-01-01 midnight UTC?", 1),
        ("What was camera-kit capacity at 2027-01-01 midnight UTC?", None),
    ):
        item = rt.interactions.submit(key, "ask", {"text": text})
        for _ in range(20):
            tick()
            with rt.store.db(key) as db:
                work = loads(db.execute("SELECT body FROM chat_work WHERE id=?", (item["id"],)).fetchone()[0])
            if work["status"] == "awaiting_local":
                execute(rt, key)
            if work["status"] == "completed":
                break
        assert work["status"] == "completed", work
        saved = rt.store.request(key, work["request_id"])
        if expected is None:
            assert saved["status"] == "needs_input"
        else:
            assert saved["result"]["value"]["value"] == expected
        presentation = s.ask.get(key, work["id"])
        if saved["result"]:
            assert presentation["outcome"]["binding"] == saved["result"]["binding"]
        else:
            assert presentation["outcome"]["binding"] == saved["pinned_context"]
        assert presentation["outcome"]["request_id"] == saved["request_id"]
        assert presentation["presentation"]["status"] == "ready"
        assert presentation["presentation"]["authoritative"] is False
        outcomes.append(saved)
    return {
        "status": "passed",
        "calls": calls,
        "remote_calls": 0,
        "task": task,
        "requests": outcomes,
        "model_id": key,
        "usage": rt.learning.usage(),
    }


def test_equipment_enable_mixed_teaching_and_ask_without_setup(rig, tmp_path):
    rt, gw = rig
    result = run_trial(rt, gw, tmp_path)
    assert len(result["calls"]) == 10
