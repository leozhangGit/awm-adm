"""Direct exchange identity, model isolation and historical readability."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from awm_adm.runtime.protocol import RuntimeFault
from awm_adm.runtime.service import Runtime

from .interaction_support import proposal
from .test_application import app_runtime as app_runtime
from .test_application import client
from .test_direct_ask import recorded, work
from .test_learning_service import rig as rig


def test_concurrent_duplicate_submission_creates_one_exchange(rig):
    rt, gw = rig
    key = rt.create("Concurrent messages")["id"]
    recorded(rt, gw, proposal("capabilities"))
    body = {"text": "What do you know?", "idempotency_key": "one-message"}
    with ThreadPoolExecutor(4) as pool:
        replies = list(pool.map(lambda _: rt.interactions.submit(key, "ask", body), range(4)))
    assert len({r["id"] for r in replies}) == 1
    assert len(rt.interactions.chat(key, "ask")["items"]) == 1
    with rt.store.db() as db:
        assert not db.execute("SELECT 1 FROM grants").fetchone()
    with pytest.raises(RuntimeFault, match="different content"):
        rt.interactions.submit(key, "teach", body)


def test_reply_to_requires_same_model_and_channel(rig):
    rt, gw = rig
    first, second = [rt.create(n)["id"] for n in ("First", "Second")]
    recorded(rt, gw, proposal("capabilities"))
    item = rt.interactions.submit(first, "ask", {"text": "A question"})
    for key, channel in ((second, "ask"), (first, "teach")):
        with pytest.raises(RuntimeFault, match="this model and channel"):
            rt.interactions.submit(key, channel, {"text": "Follow-up", "reply_to": item["id"]})
    with pytest.raises(RuntimeFault, match="still working"):
        rt.interactions.submit(first, "ask", {"text": "Follow-up", "reply_to": item["id"]})


def test_retired_setup_routes_cannot_change_state_and_direct_routes_require_owner(rig):
    rt, gw = rig
    key = rt.create("API boundary")["id"]
    recorded(rt, gw, proposal("capabilities"))
    with client(rt) as c:
        for route in (
            "conversations",
            "conversations/old/setup",
            "conversations/old/messages",
            "decisions/old",
        ):
            assert c.post(f"/api/v1/adms/{key}/{route}", json={}).status_code in (404, 405)
        for route in ("ask", "teach", "source-queues"):
            assert (
                c.post(
                    f"/api/v1/adms/{key}/{route}",
                    json={"text": "Hello"},
                    headers={"Authorization": "Bearer invalid"},
                ).status_code
                == 401
            )
        assert (
            c.post(f"/api/v1/adms/{key}/ask", json={"text": "Hello", "allowance_id": "forged"}).status_code
            == 422
        )
    assert not rt.interactions.chat(key, "ask")["items"]


def test_queued_exchange_survives_restart_without_dispatch_or_replay(rig):
    rt, gw = rig
    key = rt.create("Restarted chat")["id"]
    recorded(rt, gw, proposal("capabilities"))
    item = rt.interactions.submit(key, "ask", {"text": "What do you know?", "idempotency_key": "saved"})
    original = work(rt, key, item["id"])
    rt.close()
    resumed = Runtime(rt.config, start_scheduler=False)
    try:
        saved = resumed.interactions.get(key, item["id"])
        assert saved["status"] == "interrupted"
        assert work(resumed, key, item["id"])["context"] == original["context"]
        assert (
            resumed.interactions.submit(
                key, "ask", {"text": "What do you know?", "idempotency_key": "saved"}
            )["id"]
            == item["id"]
        )
        assert not resumed.learning.claim()
        assert not resumed.conversations.tick()
    finally:
        resumed.close()
