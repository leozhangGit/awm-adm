"""Boundary regressions from the shared-policy review; no provider network."""

import pytest

from awm_adm.runtime.protocol import RuntimeFault, dumps, loads

from .test_application import app_runtime as app_runtime
from .test_application import client
from .test_direct_ask import recorded, work
from .test_learning_service import advance, connection, episode
from .test_learning_service import rig as rig
from .test_shared_llm_limits import grant_body
from .test_single_connection import enable_input
from .test_sources import install


@pytest.mark.parametrize("existing_test", [False, True])
def test_retained_enable_uses_existing_grant_or_stops_without_defaulting(rig, existing_test):
    rt, gw = rig
    state = rt.settings.get()
    rt.settings.update(
        {
            "expected_revision": state["revision"],
            "values": state["values"]
            | {"llm_call": {"max_input_tokens": 256000, "max_output_tokens": 1000, "max_duration_ms": 2000}},
        }
    )
    manager = rt.learning.connection_manager
    gw.synchronize()
    source = enable_input(gw)
    saved = manager.enable(source)
    gw.synchronize()
    gw.synchronize()
    gid, original = None, None
    if existing_test:
        assert manager.tick()
        gid = manager.operation(saved["id"])["grant_id"]
        original = grant_body(rt, gid)
    with rt.store.db() as db:
        body = loads(
            db.execute("SELECT body FROM connection_operations WHERE id=?", (saved["id"],)).fetchone()[0]
        )
        body.pop("call_limits")
        db.execute(
            "UPDATE connection_operations SET body=?,grant_id=NULL WHERE id=?", (dumps(body), saved["id"])
        )
    assert manager.tick()
    result = manager.operation(saved["id"])
    if existing_test:
        assert result["status"] == "testing" and result["grant_id"] == gid
        assert grant_body(rt, gid) == original
    else:
        assert result["status"] == "failed" and result["error"] == "stale_context"
        assert result["grant_id"] is None and manager.view()["state"] == "disabled"
    assert manager.view()["has_saved_key"]
    assert manager.enable(source) == result
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == int(existing_test)
        assert db.execute("SELECT count(*) FROM grants WHERE dispatched_at IS NOT NULL").fetchone()[0] == 0
    assert rt.learning.usage()["calls"] == int(existing_test)  # Only the original reservation, if any.


@pytest.mark.parametrize("channel", ["ask", "teach"])
def test_retained_exchange_without_policy_stops_without_using_current_defaults(rig, channel):
    rt, gw = rig
    recorded(rt, gw, {})
    key = rt.create("Retained policy provenance")["id"]
    revision = rt.store.info(key)["revision_id"]
    request = {"text": "Use the accepted model", "idempotency_key": "retained-exchange"}
    submitted = rt.interactions.submit(key, channel, request)
    saved = work(rt, key, submitted["id"])
    saved.pop("llm_limits")
    with rt.store.db(key) as db:
        db.execute("UPDATE chat_work SET body=? WHERE id=?", (dumps(saved), submitted["id"]))
    assert rt.conversations.tick()
    result = rt.interactions.get(key, submitted["id"])
    assert result["status"] == "failed"
    assert result["failure_code"] == "stale_context"
    if channel == "teach":
        assert "no captured shared call policy" in result["reply"]
    else:
        assert "Please restate your question" in result["reply"]
    assert rt.store.info(key)["revision_id"] == revision
    assert rt.learning.usage()["calls"] == 0
    assert rt.learning.claim() is None
    replay = rt.interactions.submit(key, channel, request)
    assert replay["id"] == submitted["id"] and replay["status"] == "failed"
    assert "llm_limits" not in work(rt, key, submitted["id"])


def test_derived_feed_budget_overflow_is_a_safe_public_limit_error(rig):
    rt, _ = rig
    key = rt.create("Bounded feed budget")["id"]
    install(rt, key)
    with client(rt) as api:
        response = api.post(
            f"/api/v1/adms/{key}/feeds",
            json={
                "idempotency_key": "large-derived-feed",
                "name": "Finite feed",
                "expected_revision": rt.store.info(key)["revision_id"],
                "expected_source_generation": 1,
                "source_ids": ["records"],
                "budget": {"max_calls": 10000},
            },
        )
    assert response.status_code == 422
    details = response.json()["details"]
    assert details["code"] == "aggregate_exhausted"
    assert details["limit"] == "max_input_tokens"
    assert details["required"] == 2560000000
    assert details["available"] == 100000000
    assert details["provider_call_dispatched"] is False
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM feeds").fetchone()[0] == 0
    assert rt.learning.usage()["calls"] == 0


@pytest.mark.parametrize("delay", [0.025, 2.9, 3.1])
@pytest.mark.parametrize("sweep_first", [False, True])
def test_delivery_grace_never_extends_provider_or_accepts_late_results(rig, monkeypatch, delay, sweep_first):
    rt, gw = rig
    conn = connection(rt, gw)
    key = rt.create("Provider delivery boundary")["id"]
    saved = episode(rt, key, conn)
    advance(rt, key, saved["id"], "acquiring")
    clock = [rt.learning.now()]
    monkeypatch.setattr(rt.learning, "now", lambda: clock[0])
    claimed = rt.learning.claim()
    body = grant_body(rt, claimed["grant_id"])
    assert body["expires"] == clock[0] + 360
    assert body["delivery_deadline"] == body["expires"] + 3
    # The gateway returns a completed response; its callback is briefly delayed.
    deliver = gw.deliver
    monkeypatch.setattr(gw, "deliver", lambda _: None)
    gw.dispatch(claimed["grant_id"], claimed["lease"])
    clock[0] = body["expires"] + delay
    if sweep_first:
        rt.learning.tick()
    view = rt.learning.grant_view(claimed["grant_id"])
    if delay < 3 or not sweep_first:
        assert view["status"] == "dispatched"
        assert rt.learning.episode(key, saved["id"])["status"] == "acquiring"
    else:
        assert view["status"] == "outcome_unknown"
    # Expired execution cannot authorize another call, even within delivery grace.
    with pytest.raises(RuntimeFault) as rejected:
        rt.learning.authorize(claimed["grant_id"], claimed["lease"])
    assert getattr(rejected.value, "code", None) == "stale_context"
    deliver(gw.store.lookup(claimed["grant_id"]))
    if delay < 3:
        ready = advance(rt, key, saved["id"], "awaiting_review")
        assert len(ready["receipts"]) == 1
    else:
        stopped = advance(rt, key, saved["id"], "stopped")
        assert stopped["status"] == "stopped" and stopped["receipts"] == []
        assert rt.learning.grant_view(claimed["grant_id"])["outcome"]["error"] == "dispatch_expired"
    assert rt.learning.claim() is None
    assert rt.learning.usage()["calls"] == 1
    assert rt.learning.usage()["unresolved"] == 0
    with rt.store.db() as db:
        current = loads(
            db.execute("SELECT body FROM grants WHERE id=?", (claimed["grant_id"],)).fetchone()[0]
        )
    assert current["expires"] == body["expires"]
    assert current["delivery_deadline"] == body["delivery_deadline"]


def test_retained_lease_without_delivery_deadline_keeps_original_expiry(rig, monkeypatch):
    rt, gw = rig
    conn = connection(rt, gw)
    key = rt.create("Retained provider lease")["id"]
    saved = episode(rt, key, conn)
    advance(rt, key, saved["id"], "acquiring")
    claimed = rt.learning.claim()
    body = grant_body(rt, claimed["grant_id"])
    body.pop("delivery_deadline")
    with rt.store.db() as db:
        db.execute("UPDATE grants SET body=? WHERE id=?", (dumps(body), claimed["grant_id"]))
    rt.learning.authorize(claimed["grant_id"], claimed["lease"])
    monkeypatch.setattr(rt.learning, "now", lambda: body["expires"] + 0.025)
    rt.learning.tick()
    assert rt.learning.grant_view(claimed["grant_id"])["status"] == "outcome_unknown"
    assert rt.learning.episode(key, saved["id"])["status"] == "stopped"
    assert "delivery_deadline" not in grant_body(rt, claimed["grant_id"])


def test_explicit_smaller_feed_lifetime_budget_does_not_expand_to_call_count(rig):
    rt, _ = rig
    key = rt.create("Explicit feed envelope")["id"]
    install(rt, key)
    feed = rt.sources.feeds.create(
        key,
        {
            "idempotency_key": "smaller-feed-envelope",
            "name": "Finite feed",
            "expected_revision": rt.store.info(key)["revision_id"],
            "expected_source_generation": 1,
            "source_ids": ["records"],
            "budget": {
                "max_calls": 10000,
                "max_input_tokens": 256000,
                "max_output_tokens": 32768,
            },
        },
    )
    assert feed["body"]["budget"]["max_calls"] == 10000
    assert feed["body"]["budget"]["max_input_tokens"] == 256000
    assert feed["body"]["budget"]["max_output_tokens"] == 32768
    assert rt.learning.usage()["calls"] == 0
