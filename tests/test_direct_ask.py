"""Ordinary messages, independent exchanges and local results; no financial setup."""

# ruff: noqa: F811

from uuid import uuid4

import pytest

from awm_adm.runtime.protocol import RuntimeFault, dumps, loads

from .interaction_support import narration, proposal
from .test_application import app_runtime, client, execute, tank  # noqa: F401
from .test_learning_service import connection, dispatch, rig  # noqa: F401


def recorded(rt, gateway, reply):
    conn = connection(rt, gateway, [reply])
    # Author fixture availability without a remote test; M1 exercises the real activation boundary.
    with rt.store.db() as db:
        db.execute("UPDATE connection_control SET state='enabled',connection_id=? WHERE id=1", (conn["id"],))
    return conn


def work(rt, key, uid):
    with rt.store.db(key) as db:
        return loads(db.execute("SELECT body FROM chat_work WHERE id=?", (uid,)).fetchone()[0])


def interpreted(rt, gateway, key, text, **extra):
    item = rt.interactions.submit(key, "ask", {"text": text, **extra})
    assert rt.conversations.ask.tick()
    dispatch(rt, gateway)
    assert rt.conversations.ask.tick()
    return item


def test_one_message_runs_local_plan_then_explains_without_setup(rig):
    rt, gateway = rig
    key = tank(rt)
    recorded(rt, gateway, proposal('plan tanks to tanks.four_litres from {"left":0,"right":0}'))
    item = interpreted(rt, gateway, key, "How can I get four litres?", idempotency_key="ordinary-plan")
    current = work(rt, key, item["id"])
    assert current["status"] == "awaiting_local"
    execute(rt, key)
    rt.conversations.ask.tick()
    narration(rt, work(rt, key, item["id"]))
    result = rt.interactions.get(key, item["id"])
    assert result["status"] == "completed"
    assert result["outcome"]["status"] == "succeeded"
    assert result["explanation"]
    assert result["request_id"] and result["result_id"]
    assert (
        rt.interactions.submit(
            key, "ask", {"text": "How can I get four litres?", "idempotency_key": "ordinary-plan"}
        )["id"]
        == item["id"]
    )
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM allowances").fetchone()[0] == 0
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM episodes").fetchone()[0] == 0


def test_missing_meaning_is_clarified_without_expiring_the_reply(rig, monkeypatch):
    rt, gateway = rig
    key = tank(rt)
    recorded(rt, gateway, proposal(status="needs_clarification", clarification="How much water do you need?"))
    first = interpreted(rt, gateway, key, "Get some water")
    assert rt.interactions.get(key, first["id"])["status"] == "needs_input"
    before = rt.conversations.now()
    monkeypatch.setattr(rt.conversations, "now", lambda: before + 7_200_000)
    second = rt.interactions.submit(key, "ask", {"text": "Four litres", "reply_to": first["id"]})
    followup = work(rt, key, second["id"])
    assert followup["question"] == "How much water do you need?"
    assert followup["selected_context"][0]["text"] == "Get some water"
    assert second["status"] == "queued"
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 0


def test_independent_messages_are_not_globally_blocked_or_used_as_each_others_context(rig):
    rt, gateway = rig
    key = tank(rt)
    recorded(rt, gateway, proposal("capabilities"))
    one = rt.interactions.submit(key, "ask", {"text": "First independent question"}, origin="console")
    two = rt.interactions.submit(key, "ask", {"text": "Second independent question"})
    assert one["id"] != two["id"]
    assert work(rt, key, one["id"])["selected_context"] == []
    assert work(rt, key, two["id"])["selected_context"] == []
    history = rt.interactions.chat(key, "ask", limit=1)
    assert history["has_more"] and history["items"][0]["origin"] == "console"
    following = rt.interactions.chat(key, "ask", after=history["next_cursor"], limit=1)
    assert [x["id"] for x in following["items"]] == [two["id"]]
    assert following["items"][0]["origin"] == "api"


def test_direct_api_disabled_connection_and_cross_model_reply(rig):
    rt, gateway = rig
    key = tank(rt)
    http = client(rt)
    assert http.post(f"/api/v1/adms/{key}/ask", json={"text": "What can you do?"}).status_code == 403
    recorded(rt, gateway, proposal("capabilities"))
    response = http.post(f"/api/v1/adms/{key}/ask", json={"text": "What can you do?"})
    assert response.status_code == 202
    item = response.json()
    assert item["idempotency_key"]
    other = rt.create("Independent model")["id"]
    with pytest.raises(RuntimeFault, match="reply must refer"):
        rt.interactions.submit(other, "ask", {"text": "What about that?", "reply_to": item["id"]})
    rt.learning.connection_manager.disable({"idempotency_key": str(uuid4())})
    assert rt.query(key, {"op": "capabilities"})["result"]["status"] == "succeeded"
    assert http.get(f"/api/v1/adms/{key}/interactions/{item['id']}").status_code == 200


def test_failed_narration_retains_checked_result(rig):
    rt, gateway = rig
    key = tank(rt)
    recorded(rt, gateway, proposal("capabilities"))
    item = interpreted(rt, gateway, key, "What can this model do?")
    execute(rt, key)
    rt.conversations.ask.tick()
    # The recorded intent is not a valid explanation; reject it without losing the local answer.
    dispatch(rt, gateway)
    rt.conversations.ask.tick()
    result = rt.interactions.get(key, item["id"])
    assert result["status"] == "completed"
    assert result["outcome"]["status"] == "succeeded"
    assert result["outcome_text"] and result["explanation"] is None
    assert "allowance" not in dumps(result).decode()


def test_restart_keeps_completed_local_result_without_repeating_provider_call(rig):
    from awm_adm.runtime.service import Runtime

    rt, gateway = rig
    key = tank(rt)
    recorded(rt, gateway, proposal("capabilities"))
    item = interpreted(rt, gateway, key, "What can you do?")
    execute(rt, key)
    rt.conversations.ask.tick()
    before = rt.interactions.get(key, item["id"])
    with rt.store.db() as db:
        grants = db.execute("SELECT count(*) FROM grants").fetchone()[0]
    rt.close()
    restored = Runtime(rt.config, start_scheduler=False)
    try:
        after = restored.interactions.get(key, item["id"])
        assert after["request_id"] == before["request_id"]
        assert after["result_id"] == before["result_id"]
        assert after["status"] == "completed"
        assert after["outcome"] == before["outcome"]
        with restored.store.db() as db:
            assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == grants
    finally:
        restored.close()
