"""Real transactions and simulated dispatches; all dollar rates are synthetic."""

import base64
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from awm_adm.allowances.pricing import PURPOSES
from awm_adm.contracts import CallLimits
from awm_adm.providers.wire import make_wire, provenance, specification
from awm_adm.runtime.protocol import RuntimeFault, dumps, loads
from awm_adm.runtime.service import Runtime

from .test_application import app_runtime as app_runtime
from .test_application import client as client
from .test_learning_service import rig as rig


def setup(rt, gateway, *, learning=1_000_000, interaction=1_000_000, replies=None):
    c = rt.learning.save_connection(
        {
            "idempotency_key": str(uuid4()),
            "name": "Synthetic finance fixture",
            "provider": "recorded",
            "model": "synthetic",
            "enabled": True,
            "purposes": sorted(PURPOSES),
            "recorded_responses": replies if replies is not None else [{"ok": True}],
        }
    )
    gateway.synchronize()
    gateway.synchronize()
    c = rt.learning.connection(c["id"])
    svc = rt.learning.allowances
    svc.configure(
        {
            "expected_generation": svc.settings()["generation"],
            "enabled": True,
            "total_micro_usd": learning + interaction,
            "interaction_micro_usd": interaction,
            "learning_micro_usd": learning,
        }
    )
    p = svc.save_price(
        {
            "idempotency_key": str(uuid4()),
            "connection_id": c["id"],
            "connection_version": c["version"],
            "configuration_digest": c["configuration_digest"],
            "bound_profile": "recorded-test/1",
            "input_micro_usd_per_million": 2_000_000,
            "output_micro_usd_per_million": 4_000_000,
            "valid_until_ms": svc.now() + 86400000,
        }
    )
    return c, p


def fund(rt, price, key=None, scope="control", cap=200_000, **extra):
    return rt.learning.allowances.create(
        {
            "idempotency_key": str(uuid4()),
            "price_id": price["id"],
            "adm_id": key,
            "scope": scope,
            "scope_id": str(uuid4()),
            "cap_micro_usd": cap,
            "expires_at_ms": rt.learning.allowances.now() + 600000,
            **extra,
        }
    )


def reserve(rt, c, a, key=None, purpose="connection_test", output=8192):
    spec = specification(connection_test=True)
    raw, estimate = make_wire(c, spec, output)
    operation = str(uuid4())
    if purpose not in {"connection_test", "acquisition", "interpretation", "extraction"}:
        rt.learning.allowances.child(
            a["id"],
            {
                "operation_id": operation,
                "kind": "narration" if "narration" in purpose else "preparation",
                "max_work": 1,
                "payload_digest": provenance(spec, raw)["request_hash"],
            },
        )
    return rt.learning.reserve(
        {
            "purpose": purpose,
            "allowance_id": a["id"],
            "operation_id": operation,
            "base_revision": rt.store.info(key)["revision_id"] if key else None,
            "connection_id": c["id"],
            "connection_version": c["version"],
            "configuration_digest": c["configuration_digest"],
            "wire": base64.b64encode(raw).decode(),
            "input_estimate": estimate,
            "limits": CallLimits(max_output_tokens=output).model_dump(),
            "provenance": provenance(spec, raw),
            "recorded_index": 0,
            "deadline": rt.learning.now() + 60,
        },
        adm=key,
    )


def settle(rt, gid, usage=None, status="failed"):
    job = rt.learning.claim()
    assert job and job["grant_id"] == gid
    rt.learning.authorize(gid, job["lease"])
    rt.learning.outcome(gid, job["lease"], {"status": status, "error": "authored_failure", "usage": usage})
    return job


def test_concurrent_allocation_and_dispatch_cannot_overspend(rig):
    rt, gw = rig
    c, p = setup(rt, gw, learning=200_000)

    def allocate(_):
        try:
            return fund(rt, p)
        except RuntimeFault as e:
            assert e.code == "quota_exceeded"
            return None

    with ThreadPoolExecutor(8) as pool:
        awards = [a for a in pool.map(allocate, range(8)) if a]
    assert len(awards) == 1
    a = awards[0]

    def call(_):
        try:
            return reserve(rt, c, a)
        except RuntimeFault as e:
            assert e.code == "quota_exceeded"
            return None

    with ThreadPoolExecutor(8) as pool:
        grants = [g for g in pool.map(call, range(8)) if g]
    assert len(grants) == 2
    assert rt.learning.allowances.view(a["id"])["reserved_micro_usd"] == 193536
    assert rt.learning.usage()["calls"] == 2


def test_known_usage_rounds_settles_once_and_retains_reported_tokens(rig):
    rt, gw = rig
    c, p = setup(rt, gw)
    a = fund(rt, p)
    gid = reserve(rt, c, a)
    assert rt.learning.allowances.view(a["id"])["reserved_micro_usd"] == 96768
    job = settle(rt, gid, {"input_tokens": 1000, "output_tokens": 200})
    rt.learning.outcome(
        gid, job["lease"], {"status": "failed", "usage": {"input_tokens": 1, "output_tokens": 1}}
    )
    view = rt.learning.allowances.view(a["id"])
    assert view["settled_micro_usd"] == 2800 and view["reserved_micro_usd"] == 0
    assert view["valuation"] == "synthetic_test_estimate"
    assert rt.learning.grant_view(gid)["input_tokens"] == 1000


def test_unknown_restart_expiry_and_new_window_do_not_refund(rig):
    rt, gw = rig
    c, p = setup(rt, gw, learning=200_000)
    a = fund(rt, p)
    gid = reserve(rt, c, a)
    settle(rt, gid, status="outcome_unknown")
    rt.learning.allowances.close(a["id"], "active")
    rt.learning.now = lambda: time.time() + 90000
    assert rt.learning.allowances.view(a["id"])["reserved_micro_usd"] == 96768
    assert rt.learning.usage()["input_tokens"] == 32000
    rt.learning.recover()
    assert rt.learning.allowances.view(a["id"])["reserved_micro_usd"] == 96768
    with rt.store.db() as db:
        assert rt.learning.allowances.installation_usage(db)["learning"] == 96768


def test_completion_protected_learning_exhaustion_leaves_interaction(rig):
    rt, gw = rig
    c, p = setup(rt, gw)
    key = rt.create("parallel")["id"]
    learning = fund(rt, p, key, "task", 177152)  # exactly 8192 + 4096 at synthetic rates
    ask = fund(rt, p, key, "interaction")
    first = reserve(rt, c, learning, key, "task_preparation")
    with pytest.raises(RuntimeFault, match="dollar allowance"):
        reserve(rt, c, learning, key, "repair")
    job = rt.learning.claim()
    assert job["grant_id"] == first
    # Same ADM, background remains in flight; protected Ask slot still dispatches.
    other = reserve(rt, c, ask, key, "ask_interpretation")
    assert rt.learning.claim()["grant_id"] == other
    assert rt.learning.claim() is None
    # Summary failure never creates a retry of preparation or local computation.
    rt.learning.outcome(first, job["lease"], {"status": "outcome_unknown"})
    summary = reserve(rt, c, learning, key, "task_narration", output=4096)
    settle(rt, summary, status="outcome_unknown")
    with pytest.raises(RuntimeFault, match="already reserved"):
        reserve(rt, c, learning, key, "task_narration", output=4096)
    assert rt.learning.usage()["calls"] == 3


def test_overrun_suspends_only_affected_lane_and_charges_actual(rig):
    rt, gw = rig
    c, p = setup(rt, gw)
    key = rt.create("overrun")["id"]
    a = fund(rt, p)
    gid = reserve(rt, c, a)
    settle(rt, gid, {"input_tokens": 50000, "output_tokens": 9000})
    assert rt.learning.allowances.view(a["id"])["settled_micro_usd"] == 136000
    assert rt.learning.allowances.view(a["id"])["state"] == "suspended"
    ask = fund(rt, p, key, "interaction")
    next_id = reserve(rt, c, ask, key, "ask_narration")
    assert rt.learning.claim()["grant_id"] == next_id


def test_price_replacement_cancels_undispatched_not_unknown(rig):
    rt, gw = rig
    c, p = setup(rt, gw)
    a = fund(rt, p)
    pending = reserve(rt, c, a)
    price = {
        k: p[k]
        for k in (
            "connection_id",
            "connection_version",
            "configuration_digest",
            "bound_profile",
            "input_micro_usd_per_million",
            "output_micro_usd_per_million",
            "valid_until_ms",
        )
    }
    price["idempotency_key"] = str(uuid4())
    price["output_micro_usd_per_million"] *= 2
    rt.learning.allowances.save_price(price)
    assert rt.learning.claim() is None
    assert rt.learning.grant_view(pending)["status"] == "not_dispatched"
    assert rt.learning.allowances.view(a["id"])["reserved_micro_usd"] == 0
    with pytest.raises(RuntimeFault, match="Pinned price"):
        reserve(rt, c, a)


def test_scope_and_exact_purpose_cannot_be_funded_from_wrong_lane(rig):
    rt, gw = rig
    c, p = setup(rt, gw)
    key = rt.create("one")["id"]
    other = rt.create("two")["id"]
    a = fund(rt, p, key, "interaction")
    for target, purpose in [
        (other, "ask_interpretation"),
        (key, "task_preparation"),
        (key, "task_narration"),
    ]:
        with pytest.raises(RuntimeFault, match="outside this allowance"):
            reserve(rt, c, a, target, purpose)
    assert rt.learning.usage()["calls"] == 0


def test_child_work_is_reserved_before_handoff_and_replay_is_exact(rig):
    rt, gw = rig
    _, p = setup(rt, gw)
    key = rt.create("work")["id"]
    a = fund(rt, p, key, "task", max_work=10, max_children=2)
    body = {
        "operation_id": "child",
        "kind": "local_check",
        "max_work": 8,
        "payload_digest": "sha256:" + "a" * 64,
    }
    service = rt.learning.allowances
    assert service.child(a["id"], body) == service.child(a["id"], body)
    with pytest.raises(RuntimeFault, match="different work"):
        service.child(a["id"], {**body, "max_work": 1})
    with pytest.raises(RuntimeFault, match="work allowance"):
        service.child(a["id"], {**body, "operation_id": "second", "max_work": 3})
    service.settle_work(a["id"], "child", 2)
    service.child(a["id"], {**body, "operation_id": "second"})
    with pytest.raises(RuntimeFault):
        service.settle_work(a["id"], "child", 1)


def test_gateway_exact_purpose_and_at_most_once_priced_call(rig):
    rt, gw = rig
    c, p = setup(rt, gw)
    a = fund(rt, p)
    gid = reserve(rt, c, a)
    job = rt.learning.claim()
    assert gw.dispatch(gid, job["lease"])["status"] == "succeeded"
    assert gw.dispatch(gid, job["lease"])["replayed"]
    assert rt.learning.usage()["calls"] == 1
    with gw.store.db() as db:
        assert db.execute("SELECT count(*) FROM dispatches").fetchone()[0] == 1


def test_separate_local_checking_supervisors_and_fair_adm_slots(rig):
    rt, gw = rig
    assert rt.language.supervisor is not rt.learning.supervisor
    assert rt.supervisor is not rt.language.supervisor
    c, p = setup(rt, gw)
    akey, bkey = rt.create("a")["id"], rt.create("b")["id"]
    a, b = fund(rt, p, akey, "interaction"), fund(rt, p, bkey, "interaction")
    first = reserve(rt, c, a, akey, "ask_interpretation")
    second = reserve(rt, c, a, akey, "ask_interpretation")
    third = reserve(rt, c, b, bkey, "ask_interpretation")
    settle(rt, first, {"input_tokens": 10, "output_tokens": 1})
    assert rt.learning.claim()["grant_id"] == third
    assert rt.learning.claim() is None
    assert rt.learning.grant_view(second)["status"] == "ready"


def test_legacy_migration_preserves_rows_requires_hold_and_never_invents_cost(rig):
    rt, gw = rig
    c, _ = setup(rt, gw)
    # Authored prior remote row; no transport exists in this test.
    gid = rt.learning.test_connection(c["id"], {"idempotency_key": "old", "expected_version": 1})["id"]
    with rt.store.db() as db:
        cfg = loads(db.execute("SELECT config FROM connections WHERE id=?", (c["id"],)).fetchone()[0])
        cfg.update(provider="openai", credential_mode="static", recorded_responses=[])
        db.execute("UPDATE connections SET config=? WHERE id=?", (dumps(cfg), c["id"]))
        before = dict(db.execute("SELECT * FROM grants WHERE id=?", (gid,)).fetchone())
    root = rt.store.root
    cfg = rt.config
    rt.close()
    from .migration_support import remove_allowances

    with sqlite3.connect(root / "registry.db") as db:
        remove_allowances(db)
        from tests.migration_support import remove_conversations

        remove_conversations(db)
        db.execute("PRAGMA user_version=8")
    revived = Runtime(cfg, start_scheduler=False)
    try:
        # Restart refunds only ready/provably undispatched work. Legacy valuation
        # remains unavailable even when a grant subsequently becomes not-dispatched.
        service = revived.learning.allowances
        assert service.settings()["legacy_valuation"] == "unpriced_legacy"
        with revived.store.db() as db:
            after = dict(db.execute("SELECT * FROM grants WHERE id=?", (gid,)).fetchone())
            assert after["body"] == before["body"] and after["id"] == before["id"]
        setting = {
            "expected_generation": 0,
            "enabled": True,
            "total_micro_usd": 500000,
            "interaction_micro_usd": 200000,
            "learning_micro_usd": 200000,
        }
        with pytest.raises(RuntimeFault, match="legacy hold"):
            service.configure(setting)
        service.configure({**setting, "legacy_hold_micro_usd": 100000})
        with pytest.raises(RuntimeFault, match="cannot be refunded"):
            service.configure({**setting, "expected_generation": 1, "legacy_hold_micro_usd": 1})
    finally:
        revived.close()


def test_owner_api_and_no_default_spending(app_runtime):
    rt = app_runtime
    c = client(rt)
    assert c.get("/api/v1/spending").json()["enabled"] is False
    assert c.get("/api/v1/allowances?limit=101").status_code == 422
    assert c.post("/api/v1/allowances", json={"cap_micro_usd": 0.01}).status_code == 422
    assert rt.learning.usage()["calls"] == 0


def test_registry_failure_rolls_back_money_and_grant_together(rig, monkeypatch):
    rt, gw = rig
    c, p = setup(rt, gw)
    a = fund(rt, p)

    def disk_full(*args, **kwargs):
        raise RuntimeFault("resource_exhausted", "authored disk failure")

    monkeypatch.setattr(rt.store, "capacity", disk_full)
    with pytest.raises(RuntimeFault, match="disk failure"):
        reserve(rt, c, a)
    assert rt.learning.usage()["calls"] == 0
    assert rt.learning.allowances.view(a["id"])["reserved_micro_usd"] == 0
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM charges").fetchone()[0] == 0


def test_unknown_late_known_settlement_is_idempotent_after_restart(rig):
    rt, gw = rig
    c, p = setup(rt, gw)
    a = fund(rt, p)
    gid = reserve(rt, c, a)
    job = settle(rt, gid, status="outcome_unknown")
    cfg = rt.config
    rt.close()
    again = Runtime(cfg, start_scheduler=False)
    try:
        service = again.learning.allowances
        assert service.view(a["id"])["unknown_micro_usd"] == 96768
        again.learning.outcome(
            gid, job["lease"], {"status": "failed", "usage": {"input_tokens": 1000, "output_tokens": 200}}
        )
        assert service.view(a["id"])["settled_micro_usd"] == 2800
        assert service.view(a["id"])["reserved_micro_usd"] == 0
        assert again.learning.claim() is None
    finally:
        again.close()


def test_child_reconciliation_returns_same_grant_never_redispatches(rig):
    rt, gw = rig
    c, p = setup(rt, gw)
    key = rt.create("exact child")["id"]
    a = fund(rt, p, key, "interaction")
    gid = reserve(rt, c, a, key, "ask_narration")
    with rt.store.db() as db:
        body = loads(db.execute("SELECT body FROM grants WHERE id=?", (gid,)).fetchone()[0])
    settle(rt, gid, status="outcome_unknown")
    assert rt.learning.reserve(body, adm=key) == gid
    with pytest.raises(RuntimeFault, match="different content"):
        rt.learning.reserve({**body, "purpose": "ask_interpretation"}, adm=key)
    assert rt.learning.usage()["calls"] == 1
    assert rt.learning.claim() is None


def test_wrong_gateway_purpose_cannot_reach_transport(rig):
    rt, gw = rig
    c, p = setup(rt, gw)
    a = fund(rt, p)
    gid = reserve(rt, c, a)
    job = rt.learning.claim()
    original = gw.exchange

    def altered(route, body):
        value = original(route, body)
        if route == "authorize":
            value["purpose"] = "acquisition"
        return value

    gw.exchange = altered
    with pytest.raises(ValueError, match="purpose"):
        gw.dispatch(gid, job["lease"])
    assert gw.store.lookup(gid) is None
    assert rt.learning.allowances.view(a["id"])["reserved_micro_usd"] == 96768


def test_closed_and_expired_allowances_are_not_authority(rig):
    rt, gw = rig
    c, p = setup(rt, gw)
    a = fund(rt, p)
    gid = reserve(rt, c, a)
    rt.learning.allowances.close(a["id"], "active")
    assert rt.learning.claim() is None
    assert rt.learning.grant_view(gid)["status"] == "not_dispatched"
    with pytest.raises(RuntimeFault, match="closed"):
        reserve(rt, c, a)
    b = fund(rt, p)
    rt.learning.now = lambda: b["expires_at_ms"] / 1000 + 1
    with pytest.raises(RuntimeFault, match="expired"):
        reserve(rt, c, b)
    assert rt.learning.allowances.view(b["id"])["state"] == "expired"


def test_live_price_profile_is_not_a_synthetic_bypass_or_byte_estimate(rig, tmp_path):
    from .test_provider_diagnostics import remote_budget, remote_connection, response

    rt, gw = rig
    c, calls = remote_connection(rt, gw, tmp_path, response("openai"))
    key = rt.create("bound")["id"]
    budget = remote_budget(rt, c, key, "interaction")
    service = rt.learning.allowances
    a = service.view(budget["allowance_id"])
    with pytest.raises(RuntimeFault, match="input bound exceeds"):
        reserve(rt, c, a, key, "ask_narration")  # 32000 < documented 128000
    assert calls == [] and rt.learning.usage()["calls"] == 0
    with pytest.raises(RuntimeFault, match="No verified price"):
        service.save_price(
            {
                "idempotency_key": str(uuid4()),
                "connection_id": c["id"],
                "connection_version": c["version"],
                "configuration_digest": c["configuration_digest"],
                "bound_profile": "recorded-test/1",
                "input_micro_usd_per_million": 1,
                "output_micro_usd_per_million": 1,
                "valid_until_ms": service.now() + 1000,
            }
        )


def test_price_wire_blocks_tools_media_and_hidden_configuration(rig):
    rt, gw = rig
    c, p = setup(rt, gw)
    a = fund(rt, p)
    gid = reserve(rt, c, a)
    with rt.store.db() as db:
        body = loads(db.execute("SELECT body FROM grants WHERE id=?", (gid,)).fetchone()[0])
    wire = loads(base64.b64decode(body["wire"]))
    wire["tools"] = [{"type": "web_search"}]
    body.pop("operation_id", None)
    body["wire"] = base64.b64encode(dumps(wire)).decode()
    with pytest.raises(RuntimeFault, match="without tools"):
        rt.learning.reserve(body)
    assert rt.learning.usage()["calls"] == 1


def test_large_reported_overrun_retained_without_sqlite_overflow(rig):
    rt, gw = rig
    c, p = setup(rt, gw)
    service = rt.learning.allowances
    # Large but bounded owner rates plus a hostile valid reported counter must
    # not roll back the accounting transaction or restore dispatch authority.
    body = {
        k: p[k]
        for k in (
            "connection_id",
            "connection_version",
            "configuration_digest",
            "bound_profile",
            "valid_until_ms",
        )
    }
    body.update(
        idempotency_key=str(uuid4()),
        input_micro_usd_per_million=1_000_000_000,
        output_micro_usd_per_million=1_000_000_000,
    )
    p = service.save_price(body)
    service.configure(
        {
            "expected_generation": 1,
            "enabled": True,
            "total_micro_usd": 200_000_000,
            "interaction_micro_usd": 0,
            "learning_micro_usd": 200_000_000,
        }
    )
    a = fund(rt, p, cap=200_000_000)
    gid = reserve(rt, c, a)
    reported = 9_007_199_254_740_991
    settle(rt, gid, {"input_tokens": reported, "output_tokens": reported})
    assert service.view(a["id"])["settled_micro_usd"] == 2 * reported * 1000
    assert service.settings()["suspended_lanes"] == ["learning"]


def test_funded_interpretation_and_local_answer_after_learning_exhaustion(rig):
    from .test_application import execute
    from .test_language_service import consent, conversation, finish, interpret, proposal
    from .test_learning_service import dispatch

    rt, gw = rig
    c, p = setup(rt, gw, replies=[proposal()])
    key = rt.create("Ask remains usable")["id"]
    learning = fund(rt, p, key, "task", 177152)
    gid = reserve(rt, c, learning, key, "task_preparation")
    settle(rt, gid, status="outcome_unknown")
    with pytest.raises(RuntimeFault, match="dollar allowance"):
        reserve(rt, c, learning, key, "repair")
    ask = fund(rt, p, key, "interaction")
    item = interpret(
        rt,
        key,
        conversation(rt, key),
        translator="external",
        disclose_catalog=True,
        connection_id=c["id"],
        connection_version=c["version"],
        allowance_id=ask["id"],
    )
    rt.language.tick()
    dispatch(rt, gw)
    ready = finish(rt, key, item["id"])
    assert ready["status"] == "ready"
    consent(rt, key, ready)
    assert execute(rt, key)["status"] == "succeeded"
    assert rt.learning.usage()["calls"] == 2
    assert rt.learning.allowances.view(learning["id"])["unknown_micro_usd"] == 96768


def test_three_adms_rotate_before_one_adm_uses_its_second_slot(rig):
    rt, gw = rig
    c, p = setup(rt, gw)
    keys = [rt.create(str(i))["id"] for i in range(3)]
    firsts = []
    for key in keys:
        a = fund(rt, p, key, "interaction")
        firsts.append(reserve(rt, c, a, key, "ask_narration"))
        reserve(rt, c, a, key, "ask_interpretation")
    seen = []
    for _ in range(3):
        job = rt.learning.claim()
        seen.append(job["grant_id"])
        rt.learning.outcome(
            job["grant_id"],
            job["lease"],
            {"status": "failed", "usage": {"input_tokens": 1, "output_tokens": 1}},
        )
    assert set(seen) == set(firsts)


def test_price_failure_has_safe_actionable_http_guidance(rig):
    rt, gw = rig
    c, p = setup(rt, gw)
    with client(rt) as http:
        body = {
            k: p[k]
            for k in (
                "connection_id",
                "connection_version",
                "configuration_digest",
                "bound_profile",
                "input_micro_usd_per_million",
                "output_micro_usd_per_million",
                "valid_until_ms",
            )
        }
        body.update(idempotency_key=str(uuid4()), bound_profile="openai-4o-context/2026-11-08")
        result = http.post("/api/v1/prices", json=body)
        assert result.status_code == 422
        assert "No verified price/count bound" in result.json()["message"]
        assert "synthetic" not in result.json()["message"]
    assert rt.learning.usage()["calls"] == 0
