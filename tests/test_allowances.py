"""Historical financial records stay readable and settle without gating new work."""

import base64
import sqlite3
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
        db.execute("DROP TABLE IF EXISTS local_workspace")
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


def test_historical_unknown_and_late_known_usage_settle_exactly_once(rig):
    from awm_adm.allowances.pricing import amount

    rt, gw = rig
    c, price = setup(rt, gw)
    allowance = fund(rt, price)
    gid = reserve(rt, c, allowance)
    ledger = rt.learning.allowances
    reserved = amount(32000, 8192, price)
    with rt.store.db() as db:
        # Authored record of a previously dispatched priced call, not current authority.
        db.execute(
            "INSERT INTO charges VALUES(?,?,?,NULL,'unknown',?)",
            (gid, allowance["id"], reserved, dumps(price)),
        )
        ledger.settle(db, gid)
    assert ledger.view(allowance["id"])["reserved_micro_usd"] == reserved
    with rt.store.db() as db:
        ledger.settle(db, gid, {"input_tokens": 1000, "output_tokens": 200})
        ledger.settle(db, gid, {"input_tokens": 1, "output_tokens": 1})
    saved = ledger.view(allowance["id"])
    assert saved["settled_micro_usd"] == amount(1000, 200, price)
    assert saved["reserved_micro_usd"] == 0
    assert rt.learning.grant_view(gid)["price_binding"] is None
