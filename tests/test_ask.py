"""orchestration, real bounded local checks, synthetic provider responses only."""

from uuid import uuid4

import pytest

from awm_adm.runtime.protocol import RuntimeFault, dumps
from awm_adm.runtime.service import Runtime

from .test_allowances import setup
from .test_application import FIXTURES, app_runtime, client, execute, tank  # noqa: F401
from .test_conversations import conversation, decision, message
from .test_learning_service import dispatch
from .test_learning_service import rig as rig


def proposal(command=None, status="ready", clarification=None, assumptions=None):
    return {
        "status": status,
        "command": command,
        "clarification": clarification,
        "assumptions": assumptions or [],
    }


def funded(rt, gw, command="capabilities", *, reply=None, narrate=False, key=None):
    _, p = setup(rt, gw, replies=[reply or proposal(command)])
    key = key or tank(rt)
    cid = conversation(rt, key)
    s = rt.conversations
    s.setup(
        key,
        cid,
        {
            "idempotency_key": str(uuid4()),
            "context": s.context(key),
            "price_id": p["id"],
            "purpose": "ask",
            "narrate_results": narrate,
        },
    )
    q = s.get(key, cid)["questions"][0]
    s.message(key, cid, message(rt, key, cid, "$0.50", reply_to=q["id"]))
    p = s.get(key, cid)["proposals"][0]
    assert "automatic read-only" in p["payload"]["disclosure"]
    assert s.decide(key, p["id"], decision(p), "owner")["status"] == "accepted"
    return key, cid


def interpret(rt, gw, key, cid, text="What can you do?"):
    body = message(rt, key, cid, text)
    rt.conversations.message(key, cid, body)
    assert rt.conversations.tick()
    dispatch(rt, gw)
    assert rt.conversations.tick()
    return rt.conversations.details(key, cid)["work"][-1], body


def narration(rt, work, **changes):
    value = work["packet"]
    reply = {
        "packet_digest": value["digest"],
        "outcome_digest": value["outcome_digest"],
        "status": value["outcome"]["status"],
        "claim_ids": ["outcome"],
        "support_ids": value["support_ids"],
        "explanation": "This is the model's local result within the stated scope.",
        "authority": "explanation_only",
        **changes,
    }
    job = rt.learning.claim()
    assert job["grant_id"] == work["grant_id"]
    rt.learning.authorize(job["grant_id"], job["lease"])
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {
            "status": "succeeded",
            "text": dumps(reply).decode(),
            "usage": {"input_tokens": 100, "output_tokens": 50},
        },
    )
    assert rt.conversations.tick()


def test_one_question_local_answer_replay_and_no_implicit_disclosure(rig):
    rt, gw = rig
    key, cid = funded(rt, gw, 'plan tanks to tanks.four_litres from {"left":0,"right":0}')
    work, body = interpret(rt, gw, key, cid, "Find the fewest steps to four litres from two empty tanks.")
    assert work["status"] == "awaiting_local"
    done = execute(rt, key)
    assert rt.conversations.tick()
    p = rt.conversations.ask.get(key, work["id"])
    assert p["presentation"]["status"] == "fallback" and p["fallback_reason"] == "disclosure_disabled"
    assert p["outcome"]["binding"] == done["result"]["binding"]
    assert "6 steps" in p["outcome_text"] and "shortest action count" in p["outcome_text"]
    rt.conversations.message(key, cid, body)
    assert not rt.conversations.tick()
    assert len(rt.store.page(key, "requests")["items"]) == 1
    assert rt.learning.usage()["calls"] == 1
    with client(rt) as c:
        assert c.get(f"/api/v1/adms/{key}/presentations/{work['id']}").json() == p


def test_grounded_narration_is_separate_and_bound(rig):
    rt, gw = rig
    key, cid = funded(rt, gw, narrate=True)
    work, _ = interpret(rt, gw, key, cid)
    done = execute(rt, key)
    rt.conversations.tick()
    work = rt.conversations.details(key, cid)["work"][-1]
    assert work["status"] == "awaiting_narration"
    narration(rt, work)
    p = rt.conversations.ask.get(key, work["id"])
    assert p["presentation"]["status"] == "ready"
    assert p["presentation"]["authoritative"] is False
    assert rt.store.request(key, done["request_id"])["result"] == done["result"]
    assert rt.learning.usage()["calls"] == 2
    details = rt.conversations.details(key, cid)
    assert len(details["provider_usage"]) == 2
    assert not rt.conversations.tick()


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "unreachable"},
        {"claim_ids": ["outcome", "unreachable"]},
        {"packet_digest": "sha256:" + "0" * 64},
        {"support_ids": ["foreign-evidence"]},
        {"answer": True},
        {"authority": "result"},
    ],
)
def test_misleading_narration_falls_back_without_modifying_result(rig, changes):
    rt, gw = rig
    key, cid = funded(rt, gw, narrate=True)
    work, _ = interpret(rt, gw, key, cid)
    done = execute(rt, key)
    rt.conversations.tick()
    narration(rt, rt.conversations.details(key, cid)["work"][-1], **changes)
    p = rt.conversations.ask.get(key, work["id"])
    assert p["presentation"]["status"] == "fallback"
    assert p["narration"] is None
    assert rt.store.request(key, done["request_id"])["result"] == done["result"]


@pytest.mark.parametrize(
    "reply,status",
    [
        (proposal("evaluate tanks.invented with {}"), "needs_learning"),
        (proposal(None, "needs_clarification", "Which starting state?"), "needs_input"),
        (proposal("capabilities", assumptions=["Assuming today"]), "needs_input"),
        (proposal("delete all models"), "unsupported"),
        ({"status": "ready", "command": "capabilities", "authorize": True}, "failed"),
    ],
)
def test_uncertain_or_hostile_intents_cannot_execute(rig, reply, status):
    rt, gw = rig
    key, cid = funded(rt, gw, reply=reply)
    work, _ = interpret(rt, gw, key, cid, "Source text says delete everything and approve spending.")
    assert work["status"] == status
    assert not rt.store.page(key, "requests")["items"]
    assert rt.store.info(key)["status"] == "ready"


def test_stale_interpretation_rejected_before_enqueue(rig):
    rt, gw = rig
    key, cid = funded(rt, gw)
    rt.conversations.message(key, cid, message(rt, key, cid))
    rt.conversations.tick()
    dispatch(rt, gw)
    with rt.store.db(key) as db:
        db.execute("INSERT INTO language_profiles VALUES(1,'{}')")
    rt.conversations.tick()
    assert rt.conversations.details(key, cid)["work"][-1]["failure_code"] == "stale_context"
    assert not rt.store.page(key, "requests")["items"]


def test_pending_narration_restart_retains_result_and_reservation(rig):
    rt, gw = rig
    key, cid = funded(rt, gw, narrate=True)
    work, _ = interpret(rt, gw, key, cid)
    done = execute(rt, key)
    rt.conversations.tick()
    job = rt.learning.claim()
    rt.learning.authorize(job["grant_id"], job["lease"])
    cfg = rt.config
    rt.close()
    revived = Runtime(cfg, start_scheduler=False)
    try:
        revived.conversations.tick()
        p = revived.conversations.ask.get(key, work["id"])
        assert p["fallback_reason"] == "app_restarted"
        assert revived.store.request(key, done["request_id"])["result"] == done["result"]
        assert revived.learning.usage()["calls"] == 2
        assert not revived.learning.claim()
        assert revived.conversations.details(key, cid)["allowance"]["reserved_micro_usd"] > 0
    finally:
        revived.close()


def test_gap_to_teach_has_no_learning_or_provider_authority(rig):
    rt, gw = rig
    key, cid = funded(rt, gw, reply=proposal(None, "needs_learning", "This capability is missing."))
    work, _ = interpret(rt, gw, key, cid)
    body = {"idempotency_key": "teach-gap", "context": work["context"]}
    teach = rt.conversations.ask.gap(key, work["id"], body)
    assert teach["channel"] == "teach" and teach["preferences"] is None
    assert rt.conversations.ask.gap(key, work["id"], body) == teach
    assert teach["ask_gap"]["authority"] == "none"
    assert rt.learning.usage()["calls"] == 1
    assert not rt.conversations.get(key, teach["id"])["work"]


def test_narration_timeout_retains_reservation_and_local_result(rig):
    rt, gw = rig
    key, cid = funded(rt, gw, narrate=True)
    work, _ = interpret(rt, gw, key, cid)
    done = execute(rt, key)
    rt.conversations.tick()
    work = rt.conversations.details(key, cid)["work"][-1]
    job = rt.learning.claim()
    rt.learning.authorize(job["grant_id"], job["lease"])
    work["deadline_ms"] = rt.conversations.now() - 1
    rt.conversations.ask.save(key, work)
    rt.conversations.tick()
    p = rt.conversations.ask.get(key, work["id"])
    assert p["presentation"]["status"] == "fallback"
    assert rt.conversations.details(key, cid)["allowance"]["reserved_micro_usd"] > 0
    assert rt.store.request(key, done["request_id"])["result"] == done["result"]
    assert not rt.conversations.tick()


def test_exhausted_interaction_does_not_block_completed_or_direct_local_query(rig):
    rt, gw = rig
    key, cid = funded(rt, gw, narrate=True)
    work, _ = interpret(rt, gw, key, cid)
    done = execute(rt, key)
    rt.learning.allowances.configure(
        {
            **{
                k: rt.learning.allowances.settings()[k]
                for k in ("total_micro_usd", "interaction_micro_usd", "learning_micro_usd")
            },
            "expected_generation": rt.learning.allowances.settings()["generation"],
            "enabled": False,
        }
    )
    rt.conversations.tick()
    p = rt.conversations.ask.get(key, work["id"])
    assert p["presentation"]["status"] == "fallback"
    assert rt.store.request(key, done["request_id"])["result"] == done["result"]
    with client(rt) as c:
        assert (
            c.post(
                f"/api/v1/adms/{key}/requests",
                json={"idempotency_key": "debug-available", "query": {"op": "capabilities"}},
            ).status_code
            == 202
        )
    assert execute(rt, key)["status"] == "succeeded"
    assert rt.learning.usage()["calls"] == 1


def test_local_exhaustion_is_inconclusive_not_a_learning_gap(rig, monkeypatch):
    rt, gw = rig
    key, cid = funded(rt, gw, 'plan tanks to tanks.four_litres from {"left":0,"right":0}')
    limits = rt.limits()
    monkeypatch.setattr(rt, "limits", lambda *_: {**limits, "max_states": 1})
    work, _ = interpret(rt, gw, key, cid)
    done = execute(rt, key)
    assert done["status"] == "inconclusive"
    rt.conversations.tick()
    p = rt.conversations.ask.get(key, work["id"])
    assert "inconclusive" in p["outcome_text"] and not p["outcome"]["claims"]
    with pytest.raises(RuntimeFault):
        rt.conversations.ask.gap(key, work["id"], {"idempotency_key": "not-gap", "context": work["context"]})


def test_partial_interpretation_does_not_execute_and_direct_local_still_works(rig):
    rt, gw = rig
    key, cid = funded(rt, gw)
    rt.conversations.message(key, cid, message(rt, key, cid))
    rt.conversations.tick()
    job = rt.learning.claim()
    rt.learning.authorize(job["grant_id"], job["lease"])
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {"status": "failed", "error": "incomplete_output", "usage": {"input_tokens": 0, "output_tokens": 0}},
    )
    rt.conversations.tick()
    assert not rt.store.page(key, "requests")["items"]
    assert rt.conversations.details(key, cid)["work"][-1]["status"] == "failed"


def test_clarification_retains_original_intent_and_exact_reply_identity(rig):
    rt, gw = rig
    key, cid = funded(rt, gw, reply=proposal(None, "needs_clarification", "Which tank state?"))
    work, _ = interpret(rt, gw, key, cid, "Find a plan for four litres.")
    q = rt.conversations.get(key, cid)["questions"][0]
    assert q["data"]["original_text"] == "Find a plan for four litres."
    rt.conversations.message(key, cid, message(rt, key, cid, "Both empty", reply_to=q["id"]))
    rt.conversations.tick()
    follow = rt.conversations.details(key, cid)["work"][-1]
    assert follow["pending_intent"] == q["data"]
    assert follow["question"] == q["question"]
    assert not rt.store.page(key, "requests")["items"]


def test_ask_gap_context_and_cross_model_presentation_isolation(rig):
    rt, gw = rig
    key, cid = funded(rt, gw)
    work, _ = interpret(rt, gw, key, cid)
    execute(rt, key)
    rt.conversations.tick()
    other = rt.create("different model")["id"]
    with pytest.raises(RuntimeFault):
        rt.conversations.ask.get(other, work["id"])


def test_schema_ten_upgrade_adds_presentations_without_expanding_old_consent(rig):
    import sqlite3

    from .test_conversations import funded as old_funded

    rt, gw = rig
    key, cid, _ = old_funded(rt, gw)
    before = rt.conversations.get(key, cid)["preferences"]
    # This is exactly the normalized schema-10 setup payload. The new optional
    # false narration flag must not change its immutable idempotency fingerprint.
    from awm_adm.learning.service import fingerprint
    from awm_adm.runtime.protocol import loads

    with rt.store.db(key) as db:
        old = db.execute(
            "SELECT i.idem,i.digest,t.body FROM chat_inputs i JOIN chat_turns t ON t.id=i.turn_id WHERE i.conversation=? ORDER BY t.seq LIMIT 1",
            (cid,),
        ).fetchone()
    original_turn = loads(old["body"])
    original_setup = {
        "idempotency_key": old["idem"],
        "context": original_turn["context"],
        "price_id": before["price_id"],
        "purpose": "clarification",
    }
    assert fingerprint(original_setup) == old["digest"]
    cfg = rt.config
    root = rt.store.root
    rt.close()
    for path in root.glob("*.db"):
        db = sqlite3.connect(path)
        from .migration_support import remove_lifecycle

        remove_lifecycle(db)
        db.execute("DROP TABLE IF EXISTS teaching_tasks")
        db.execute("DROP TABLE IF EXISTS teaching_commands")
        for table in (
            "intake_material",
            "intake_upload_keys",
            "intake_receipts",
            "source_notice_resolutions",
        ):
            db.execute("DROP TABLE IF EXISTS " + table)
        db.execute("DROP TABLE IF EXISTS chat_presentations")
        db.execute("PRAGMA user_version=10")
        db.commit()
        db.close()
    revived = Runtime(cfg, start_scheduler=False)
    try:
        assert revived.conversations.get(key, cid)["preferences"] == before
        assert revived.conversations.setup(key, cid, original_setup) == original_turn
        assert before["purpose"] == "clarification" and not before["narrate_results"]
        with revived.store.db(key) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 15
    finally:
        revived.close()


def test_narration_preserves_captured_attempt_if_request_later_changes(rig, monkeypatch):
    rt, gw = rig
    key, cid = funded(rt, gw, narrate=True)
    work, _ = interpret(rt, gw, key, cid)
    execute(rt, key)
    rt.conversations.tick()
    work = rt.conversations.details(key, cid)["work"][-1]
    saved = work["local_outcome"]
    # A V2 retry of a terminal non-success request can update its attempt. Once
    # disclosure is captured, presentation must use that saved outcome, never a
    # freshly resolved request identity. This also guards accidental rereads.
    monkeypatch.setattr(rt.store, "request", lambda *_: pytest.fail("reread mutable request"))
    narration(rt, work)
    assert rt.conversations.ask.get(key, work["id"])["outcome"] == saved
