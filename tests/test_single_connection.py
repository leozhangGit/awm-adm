"""Single-connection activation through the real private gateway, with simulated HTTPS."""

# ruff: noqa: F811

import base64
import sqlite3
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from awm_adm.gateway.store import LABEL
from awm_adm.runtime.protocol import RuntimeFault, dumps, loads
from awm_adm.runtime.storage import migrate

from .test_application import app_runtime, client  # noqa: F401
from .test_learning_service import rig  # noqa: F401


def enable_input(gateway, identity="enable-one", **extra):
    body = {"idempotency_key": identity, "provider": "openai", "model": "owner-selected-model", **extra}
    public = serialization.load_der_public_key(base64.b64decode(gateway.store.public["spki"]))
    ciphertext = public.encrypt(
        dumps(
            {"credential": "synthetic-test-secret", "provider": body["provider"], "idempotency_key": identity}
        ),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=LABEL),
    )
    body.update(
        sealed_credential=base64.b64encode(ciphertext).decode(), sealing_key_id=gateway.store.public["key_id"]
    )
    return body


def success(_provider, _wire, credential, _timeout):
    assert credential == "synthetic-test-secret"
    return 200, dumps(
        {
            "id": "synthetic-response",
            "model": "owner-selected-model",
            "status": "completed",
            "usage": {"input_tokens": 12, "output_tokens": 4},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": '{"ok":true}'}],
                }
            ],
        }
    )


def queued(rt, gateway, body=None):
    manager = rt.learning.connection_manager
    gateway.synchronize()
    op = manager.enable(body or enable_input(gateway))
    gateway.synchronize()
    gateway.synchronize()
    assert manager.tick()
    job = rt.learning.claim()
    assert job
    return op, job


def test_enable_runs_once_without_prices_or_finance_and_disable_preserves_key(rig):
    rt, gateway = rig
    gateway.transport = success
    body = enable_input(gateway)
    op, job = queued(rt, gateway, body)
    assert rt.learning.connection_manager.view()["state"] == "testing"
    gateway.dispatch(job["grant_id"], job["lease"])
    rt.learning.connection_manager.tick()
    manager = rt.learning.connection_manager
    assert manager.view()["state"] == "enabled"
    assert manager.enable(body)["id"] == op["id"]
    assert gateway.dispatch(job["grant_id"], job["lease"])["replayed"]
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == 1
        for table in ("prices", "allowances", "charges", "budget_children"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert manager.active("acquisition")["provider"] == "openai"
    manager.disable({"idempotency_key": "disable-one"})
    view = manager.view()
    assert view["state"] == "disabled" and view["has_saved_key"]
    assert view["provider"] == "openai" and view["model"] == "owner-selected-model"
    assert "synthetic-test-secret" not in dumps(view).decode()
    with pytest.raises(RuntimeFault, match="Enable"):
        manager.active("ask_interpretation")
    # A new explicit Enable can reuse the encrypted saved key and change model.
    op, job = queued(
        rt, gateway, {"idempotency_key": "enable-two", "provider": "openai", "model": "another-model"}
    )
    gateway.dispatch(job["grant_id"], job["lease"])
    manager.tick()
    assert manager.view()["state"] == "enabled"


def test_failed_test_keeps_disabled_and_counts_missing_usage(rig):
    rt, gateway = rig
    gateway.transport = lambda *_: (401, dumps({"error": {"code": "invalid_api_key"}}))
    op, job = queued(rt, gateway)
    gateway.dispatch(job["grant_id"], job["lease"])
    manager = rt.learning.connection_manager
    manager.tick()
    assert manager.view()["state"] == "disabled"
    assert manager.operation(op["id"])["status"] == "failed"
    charts = manager.usage()
    assert sum(h["failed"] for h in charts["hours"]) == 1
    assert sum(d["missing_usage"] for d in charts["days"]) == 1


def test_provider_step_identity_deduplicates_without_an_allowance(rig):
    rt, gateway = rig
    gateway.transport = success
    _, job = queued(rt, gateway)
    gateway.dispatch(job["grant_id"], job["lease"])
    rt.learning.connection_manager.tick()
    with rt.store.db() as db:
        source = loads(db.execute("SELECT body FROM grants WHERE id=?", (job["grant_id"],)).fetchone()[0])
    source["operation_id"] = "stable-step"
    first = rt.learning.reserve(source)
    assert rt.learning.reserve(source) == first
    with pytest.raises(RuntimeFault, match="different content"):
        rt.learning.reserve({**source, "wire": "different-wire"})
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM allowances").fetchone()[0] == 0


def test_disable_wins_over_late_success_and_provider_change_needs_new_key(rig):
    rt, gateway = rig
    gateway.transport = success
    op, job = queued(rt, gateway)
    rt.learning.authorize(job["grant_id"], job["lease"])
    manager = rt.learning.connection_manager
    manager.disable({"idempotency_key": "disable-testing"})
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {
            "status": "succeeded",
            "text": '{"ok":true}',
            "usage": {"input_tokens": 10, "output_tokens": 4},
        },
    )
    assert not manager.tick()
    assert manager.view()["state"] == "disabled"
    assert manager.operation(op["id"])["status"] == "cancelled"
    with pytest.raises(RuntimeFault, match="Enter a key"):
        manager.enable(
            {"idempotency_key": "wrong-provider", "provider": "anthropic", "model": "another-model"}
        )


def test_unknown_call_is_not_repeated_by_polling_or_new_app_recovery(rig):
    rt, gateway = rig
    op, job = queued(rt, gateway)
    rt.learning.authorize(job["grant_id"], job["lease"])
    rt.learning.recover()
    manager = rt.learning.connection_manager
    manager.tick()
    for _ in range(3):
        manager.view()
        manager.usage()
        manager.tick()
    assert manager.operation(op["id"])["status"] == "failed"
    assert rt.learning.claim() is None
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == 1
    assert sum(h["unknown"] for h in manager.usage()["hours"]) == 1


def test_reading_state_does_not_dispatch_and_obsolete_activation_paths_are_gone(rig):
    rt, _ = rig
    http = client(rt)
    assert http.get("/api/v1/connection").json()["state"] == "disabled"
    assert http.get("/api/v1/connection/usage").status_code == 200
    for path in ("/connections", "/connections/old/test", "/prices", "/allowances"):
        assert http.post("/api/v1" + path, json={}).status_code in (404, 405)
    assert http.put("/api/v1/learning", json={}).status_code == 405
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == 0


def test_usage_counts_real_tokens_once_and_dst_hours_are_unambiguous(rig):
    rt, gateway = rig
    gateway.transport = success
    _, job = queued(rt, gateway)
    gateway.dispatch(job["grant_id"], job["lease"])
    manager = rt.learning.connection_manager
    manager.tick()
    stamp = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc).timestamp()
    with rt.store.db() as db:
        # The creation date may be outside the chart window; dispatch owns the bucket.
        db.execute("UPDATE grants SET created=?,dispatched_at=?", (stamp - 9 * 86400, stamp))
    chart = manager.usage("America/New_York", now=stamp + 3600)
    assert len(chart["days"]) == 7 and len(chart["hours"]) == 24
    starts = [h["start"] for h in chart["hours"]]
    assert "2026-11-01T01:00:00-04:00" in starts
    assert "2026-11-01T01:00:00-05:00" in starts
    assert sum(h["succeeded"] for h in chart["hours"]) == 1
    assert sum(d["input_tokens"] for d in chart["days"]) == 12
    assert sum(d["output_tokens"] for d in chart["days"]) == 4
    with pytest.raises(RuntimeFault):
        manager.usage("not-a-timezone")


def test_usage_excludes_ready_and_leased_work_until_dispatch(rig):
    rt, gateway = rig
    manager = rt.learning.connection_manager
    gateway.synchronize()
    op = manager.enable(enable_input(gateway))
    gateway.synchronize()
    gateway.synchronize()
    assert manager.tick()

    def counts():
        chart = manager.usage()
        return (
            sum(sum(h[k] for k in ("active", "succeeded", "failed", "unknown")) for h in chart["hours"]),
            sum(d["missing_usage"] for d in chart["days"]),
        )

    assert counts() == (0, 0)
    job = rt.learning.claim()
    assert job["grant_id"] == manager.operation(op["id"])["grant_id"]
    assert counts() == (0, 0)
    rt.learning.authorize(job["grant_id"], job["lease"])
    assert counts() == (1, 1)


def test_enable_expires_without_a_worker_and_does_not_dispatch(rig, monkeypatch):
    rt, gateway = rig
    manager = rt.learning.connection_manager
    gateway.synchronize()
    op = manager.enable(enable_input(gateway))
    gateway.synchronize()
    gateway.synchronize()
    assert manager.tick()
    grant_id = manager.operation(op["id"])["grant_id"]
    with rt.store.db() as db:
        grant = loads(db.execute("SELECT body FROM grants WHERE id=?", (grant_id,)).fetchone()[0])
    monkeypatch.setattr(rt.learning, "now", lambda: grant["queue_deadline"] + 1)
    for _ in range(3):
        rt.learning.tick()
    assert manager.operation(op["id"])["status"] == "failed"
    assert manager.operation(op["id"])["error"] == "queue_timeout"
    assert manager.view()["state"] == "disabled"
    retained = rt.learning.grant_view(grant_id)
    assert retained["status"] == "not_dispatched"
    assert retained["calls"] == retained["input_tokens"] == retained["output_tokens"] == 0
    assert not retained["unresolved"]
    assert rt.learning.claim() is None
    with gateway.store.db() as db:
        assert db.execute("SELECT count(*) FROM dispatches").fetchone()[0] == 0


@pytest.mark.parametrize("count", [0, 1, 2])
def test_owned_15_migration_preserves_configurations_and_disables_without_dispatch(count):
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    migrate(db, "registry")
    db.execute("DROP TABLE connection_control")
    db.execute("DROP TABLE connection_operations")
    db.execute("ALTER TABLE grants DROP COLUMN dispatched_at")
    db.execute("DROP TABLE IF EXISTS local_workspace")
    db.execute("DROP TABLE service_settings")
    db.execute("PRAGMA user_version=15")
    for n in range(count):
        db.execute(
            "INSERT INTO connections(id,version,idem,digest,config,status) VALUES(?,1,?,?,?,'ready')",
            (f"saved-{n}", f"key-{n}", f"digest-{n}", dumps({"provider": "openai", "model": "retained"})),
        )
    db.execute("UPDATE learning_control SET enabled=1 WHERE id=1")
    originals = [tuple(r) for r in db.execute("SELECT * FROM connections")]
    migrate(db, "registry")
    assert db.execute("PRAGMA user_version").fetchone()[0] == 19
    assert [tuple(r) for r in db.execute("SELECT * FROM connections")] == originals
    control = db.execute("SELECT * FROM connection_control").fetchone()
    assert control["state"] == "disabled"
    assert control["connection_id"] == ("saved-0" if count == 1 else None)
    assert db.execute("SELECT enabled FROM learning_control").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM connection_operations").fetchone()[0] == 0
    assert all(loads(r["config"])["model"] == "retained" for r in db.execute("SELECT * FROM connections"))
