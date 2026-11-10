"""Full conversational equipment fixture, simulated Luna transport only."""

from pathlib import Path
from uuid import uuid4

from awm_adm.engine import Instance
from awm_adm.runtime.protocol import dumps, loads, pack

from .teaching_wire import native_reply
from .test_application import app_runtime as app_runtime
from .test_application import execute
from .test_conversations import decision, message
from .test_equipment_trial import fixture
from .test_learning_service import rig as rig
from .test_luna_price import fund_chat, setup_luna
from .test_provider_transports import raw, response
from .test_teaching_execution import command

ROOT = Path(__file__).parents[1] / "examples/teaching"


def recorded_reply(wire):
    body = loads(wire)
    ctx = loads(body["input"][0]["content"].encode())
    name = body["text"]["format"]["name"]
    if name == "adm_teaching_preparation":
        ids = [i["id"] for i in ctx["inputs"]]
        policy = fixture("source-policy.json")
        policy["sources"][0]["source_id"] = "documents"
        plan = {
            "kind": "mixed",
            "summary": "Borrowing advice and two years of camera-kit history",
            "children": [
                {
                    "kind": "capability",
                    "objective": "Advise on one further checkout",
                    "input_ids": ids,
                    "interfaces": fixture("task.json")["acquisition_contract"]["interfaces"],
                },
                {
                    "kind": "facts",
                    "objective": "Retain 2025 and 2026 camera-kit capacity",
                    "input_ids": ids,
                    "material": policy,
                },
            ],
            "vocabulary": {"aliases": {"borrow": ["equipment.can_borrow"]}},
            "requirements": None,
        }
        return native_reply(
            {
                "status": "ready",
                "message": "Review the borrowing rule and dated capacity scope.",
                "plan_json": dumps(plan).decode(),
            }
        )
    if name == "adm_construction_v1":
        return fixture("recorded-acquisition.json")
    if name == "adm_source_claims_v1":
        content = ctx["source"]["content"]
        claims = []
        for year in (2025, 2026):
            line = next(
                line
                for line in content.splitlines()
                if line.startswith("The camera-kit") and f"from {year}-" in line
            )
            start = len(content[: content.index(line)].encode())
            claims.append(
                {
                    **fixture(f"history-{year}.json"),
                    "start_byte": start,
                    "end_byte": start + len(line.encode()),
                }
            )
        return {"claims": claims}
    if name == "adm_teaching_completion":
        return {
            "packet_digest": ctx["packet_digest"],
            "accepted_ids": ctx["packet"]["accepted_ids"],
            "unresolved_ids": ctx["packet"]["unresolved_ids"],
            "explanation": "The advisory borrowing rule and the two dated capacity facts were accepted. No inventory was changed; 2027 remains unknown.",
            "authority": "explanation_only",
        }
    if name == "adm_ask_intent":
        text = ctx["utterance"]
        cmd = fixture("expected.json")["local_command"]
        if "capacity" in text:
            year = 2027 if "2027" in text else 2026
            cmd = (
                "lookup fact with "
                + dumps(
                    {
                        "entity_id": "camera-kit",
                        "predicate": "equipment.capacity",
                        "effective_at": f"{year}-01-01T00:00:00Z",
                    }
                ).decode()
            )
        return {"status": "ready", "command": cmd, "assumptions": [], "clarification": None}
    if name == "adm_ask_explanation":
        return {
            "packet_digest": ctx["digest"],
            "outcome_digest": ctx["outcome_digest"],
            "status": ctx["outcome"]["status"],
            "claim_ids": ["outcome"],
            "support_ids": ctx["support_ids"],
            "explanation": ctx["allowed_claims"][0]["text"],
            "authority": "explanation_only",
        }
    raise AssertionError(name)


def run_trial(rt, gw, tmp_path):
    _, price, _ = setup_luna(rt, gw, tmp_path)
    calls = []

    def transport(provider, wire, credential, timeout):
        assert provider == "openai" and credential == "authored-test-credential"
        calls.append(loads(wire)["text"]["format"]["name"])
        result = response("openai", model="gpt-5.6-luna")
        result["output"][0]["content"][0]["text"] = dumps(recorded_reply(wire)).decode()
        return 200, raw(result)

    gw.transport = transport
    key = rt.create(
        "Equipment teaching rehearsal",
        snapshot=pack(Instance(policy=fixture("requirements.json")).export_snapshot()),
    )["id"]
    s = rt.conversations
    cid = fund_chat(rt, key, price, "teach")
    attachment = s.intake.upload(
        key,
        {
            "idempotency_key": str(uuid4()),
            "name": "history.md",
            "media_type": "text/markdown",
            "content": (ROOT / "history.md").read_text(),
        },
    )
    s.message(
        key,
        cid,
        {
            **message(rt, key, cid, (ROOT / "teach.txt").read_text()),
            "attachment_ids": [attachment["id"]],
            "disclose_attachments": True,
        },
    )

    def tick():
        s.tick()
        rt.learning.tick()
        rt.sources.tick()
        job = rt.learning.claim()
        if job:
            gw.dispatch(job["grant_id"], job["lease"])

    for _ in range(12):
        tick()
        view = s.get(key, cid)
        if view["proposals"]:
            break
    p = view["proposals"][0]
    assert s.decide(key, p["id"], decision(p), "owner")["status"] == "accepted"
    uid = s.get(key, cid)["tasks"][0]["id"]
    command(rt, key, uid, "start", source_consent=True)
    for _ in range(100):
        tick()
        task = s.teaching.get(key, uid)
        if task["status"] == "awaiting_decision":
            assert task["execution"]["review"]["kind"] == "source"
            command(rt, key, uid, "approve")
        if task["status"] == "succeeded":
            break
    assert task["status"] == "succeeded", task
    assert len(task["execution"]["summary"]["accepted"]) == 2
    assert len(calls) == 4
    feed = rt.sources.feeds.overview(key)["feeds"][0]
    assert feed["body"]["budget"]["max_input_tokens"] == 6_300_000
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
    aid = fund_chat(rt, key, price, narrate=True)
    outcomes = []
    for text, expected in (
        ("Can I borrow one more item if I have one and one is available?", True),
        ("What was camera-kit capacity at 2026-01-01 midnight UTC?", 1),
        ("What was camera-kit capacity at 2027-01-01 midnight UTC?", None),
    ):
        s.message(key, aid, message(rt, key, aid, text))
        for _ in range(20):
            tick()
            work = s.details(key, aid)["work"][-1]
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
        "price": price,
        "usage": rt.learning.usage(),
    }


def test_equipment_mixed_teaching_and_ask_under_luna_bound(rig, tmp_path):
    rt, gw = rig
    result = run_trial(rt, gw, tmp_path)
    assert len(result["calls"]) == 10
