"""recovery, retention and fault contracts; no live provider calls."""

import hashlib
import sqlite3
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet, InvalidToken

from awm_adm.application.auth import Authority
from awm_adm.gateway.service import Gateway
from awm_adm.gateway.store import GatewayStore
from awm_adm.operations.backup import backup, restore, verify
from awm_adm.operations.service import diagnostic, retention
from awm_adm.runtime.protocol import RuntimeFault, dumps
from awm_adm.runtime.service import Runtime

from .test_application import OWNER, app_runtime, client, configuration, envelope, execute, tank  # noqa: F401
from .test_feeds import feed, ingest, install, lookup, pump
from .test_learning_service import advance, connection, episode


def closed_pair(tmp_path):
    rt = Runtime(configuration(tmp_path / "app"), start_scheduler=False)
    key = tank(rt)
    vault = GatewayStore(tmp_path / "gateway", Fernet.generate_key())
    rt.close()
    vault.close()
    return key


def test_backup_recovery_preserves_theories_history_and_fences_authority(tmp_path):
    rt = Runtime(configuration(tmp_path / "app"), start_scheduler=False)
    master = Fernet.generate_key()
    vault = GatewayStore(tmp_path / "gateway", master)
    gateway = Gateway(vault, lambda route, body: rt.learning.synchronize(**body))
    key = rt.create("Historical source")["id"]
    install(rt, key)
    f = feed(rt, key)
    ingest(rt, key)
    pump(rt, key)
    result = lookup(rt, key)
    context = rt.store.info(key)
    source = rt.sources.history(key)
    req = rt.coordinator.submit(key, envelope())
    execute(rt, key)
    pending = rt.coordinator.submit(key, envelope("pending"))
    assert rt.store.claim_request(key) is not None
    token = Authority(rt.store, OWNER).issue(adms=[key], permissions=["read"])
    other = rt.create("Acquiring")["id"]
    c = connection(rt, gateway)
    ep = episode(rt, other, c)
    advance(rt, other, ep["id"], "acquiring")
    with rt.store.db() as db:
        grant = dict(db.execute("SELECT * FROM grants").fetchone())
    # Ready at capture may have dispatched in the abandoned post-backup timeline.
    assert grant["status"] == "ready"
    vault.begin("authored-dispatched-id", "authored-digest")
    with pytest.raises(BlockingIOError):
        backup(rt.store.root, vault.root, tmp_path / "live-backup")
    rt.close()
    vault.close()
    artifact = tmp_path / "backup"
    backup(tmp_path / "app", tmp_path / "gateway", artifact)
    assert verify(artifact)["secrets_included"] is False
    assert master not in b"".join(p.read_bytes() for p in artifact.rglob("*") if p.is_file())
    output = tmp_path / "recovered"
    report = restore(artifact, output)
    assert report["feeds_paused"] == 1
    restored = Runtime(configuration(output / "app"), start_scheduler=False)
    recovered_vault = GatewayStore(output / "gateway", master)
    try:
        assert restored.store.info(key) == context
        assert restored.store.run_info(key, result["id"]) == result
        assert lookup(restored, key)["result"]["value"] == result["result"]["value"]
        assert restored.sources.history(key)["versions"] == source["versions"]
        assert restored.coordinator.submit(key, envelope())["request_id"] == req["request_id"]
        assert restored.store.request(key, pending["request_id"])["status"] == "inconclusive"
        assert restored.sources.feeds.get(key, f["id"])["enabled"] is False
        assert restored.learning.settings()["remote_calls_enabled"] is False
        assert restored.learning.claim() is None
        assert restored.learning.usage()["unresolved"] == 1
        assert recovered_vault.lookup("authored-dispatched-id")["status"] == "outcome_unknown"
        assert not recovered_vault.begin("authored-dispatched-id", "authored-digest")
        with client(restored) as http:
            response = http.get("/api/v1/adms", headers={"Authorization": "Bearer " + token["token"]})
            assert response.status_code == 401
        assert restored.learning.episode(other, ep["id"])["status"] == "stopped"
    finally:
        restored.close()
        recovered_vault.close()
    with pytest.raises(InvalidToken):
        GatewayStore(output / "gateway", Fernet.generate_key())


def test_backup_lock_gateway_digest_inventory_missing_and_no_overwrite(tmp_path):
    key = closed_pair(tmp_path)
    # Lock the actual owner file without opening/decrypting the gateway.
    from awm_adm.operations.backup import owned

    with owned(tmp_path / "gateway", "gateway"):
        with pytest.raises(BlockingIOError):
            backup(tmp_path / "app", tmp_path / "gateway", tmp_path / "bundle")
    bundle = tmp_path / "bundle"
    backup(tmp_path / "app", tmp_path / "gateway", bundle)
    with pytest.raises(ValueError):
        backup(tmp_path / "app", tmp_path / "gateway", bundle)
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep").write_text("owner data")
    with pytest.raises(ValueError):
        restore(bundle, target)
    assert (target / "keep").read_text() == "owner data"
    original = bundle / "app" / (key + ".db")
    data = original.read_bytes()
    original.write_bytes(data + b"corruption")
    with pytest.raises(ValueError, match="digest"):
        restore(bundle, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()
    original.write_bytes(data)
    (bundle / "unexpected").write_text("extra")
    with pytest.raises(ValueError, match="inventory"):
        verify(bundle)
    (bundle / "unexpected").unlink()
    original.unlink()
    original.symlink_to(tmp_path / "app" / (key + ".db"))
    with pytest.raises(ValueError, match="entry"):
        verify(bundle)
    (tmp_path / "app" / (key + ".db")).unlink()
    with pytest.raises(ValueError, match="missing"):
        backup(tmp_path / "app", tmp_path / "gateway", tmp_path / "missing")


def test_failed_capture_cleans_staging_without_changing_source(tmp_path):
    key = closed_pair(tmp_path)
    path = tmp_path / "app" / (key + ".db")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with patch("awm_adm.operations.backup.sync_tree", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            backup(tmp_path / "app", tmp_path / "gateway", tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()
    assert not list(tmp_path.glob(".awm-recovery-*"))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    backup(tmp_path / "app", tmp_path / "gateway", tmp_path / "bundle")


def test_retention_preserves_sources_results_idempotency_and_reports_resync(app_runtime):  # noqa: F811
    rt = app_runtime
    key = rt.create("retained")["id"]
    install(rt, key)
    feed(rt, key)
    ingest(rt, key)
    pump(rt, key)
    before = rt.store.info(key)
    req = rt.coordinator.submit(key, envelope())
    execute(rt, key)
    sources = rt.sources.history(key)
    with rt.store.db(key) as db:
        db.execute("UPDATE events SET created=0")
    plan = retention(rt)
    bound = plan["instances"][0]["prune_through"]
    assert bound > 0
    rt.store.prune_events(key, bound)
    with pytest.raises(RuntimeFault) as fault:
        rt.store.events(key, 0)
    assert fault.value.code == "cursor_expired"
    assert rt.coordinator.submit(key, envelope())["request_id"] == req["request_id"]
    assert rt.store.info(key) == before
    assert rt.sources.history(key) == sources
    assert lookup(rt, key)["result"]["status"] == "succeeded"
    assert rt.store.events(key, bound)["earliest_cursor"] == bound


def test_diagnostics_owner_only_no_content_and_storage_work_observable(app_runtime):  # noqa: F811
    rt = app_runtime
    key = rt.create("PRIVATE NAME SENTINEL")["id"]
    rt.query(key, {"op": "capabilities"})
    report = diagnostic(rt)
    assert report["compute"]["serving"]["outcomes"]["ok"] >= 2
    assert report["storage"]["bytes"] > 0
    assert b"PRIVATE NAME SENTINEL" not in dumps(report)
    assert len(dumps(report)) < 1_048_576
    token = Authority(rt.store, OWNER).issue(adms=[key], permissions=["read", "submit"])
    with client(rt) as http:
        for url in ("/api/v1/operations/diagnostics", "/api/v1/operations/retention"):
            assert http.get(url).status_code == 200
            assert http.get(url, headers={"Authorization": "Bearer " + token["token"]}).status_code == 403
        assert http.get("/api/v1/operations/diagnostics", headers={"Authorization": ""}).status_code == 401


def test_real_sqlite_full_transaction_rolls_back_source_batch(app_runtime):  # noqa: F811
    rt = app_runtime
    key = rt.create("full")["id"]
    install(rt, key)
    before = rt.store.info(key)
    with rt.store.db(key) as db:
        pages = db.execute("PRAGMA page_count").fetchone()[0]
        db.execute(f"PRAGMA max_page_count={pages}")
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="full"):
            db.execute(
                "INSERT INTO source_batches VALUES(?,?,?)", ("failed-batch", "digest", b"x" * 4_000_000)
            )
        db.rollback()
        assert db.execute("SELECT count(*) FROM source_batches").fetchone()[0] == 0
    assert rt.store.info(key) == before
    assert rt.query(key, {"op": "capabilities"})["result"]["status"] == "succeeded"


def test_committed_wal_is_captured_and_counts_toward_backup_limit(tmp_path, monkeypatch):
    import importlib

    recovery = importlib.import_module("awm_adm.operations.backup")
    key = closed_pair(tmp_path)
    path = tmp_path / "app" / (key + ".db")
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("INSERT INTO source_batches VALUES(?,?,?)", ("wal-only", "digest", b"x" * 2_000_000))
        db.commit()
        assert path.with_name(path.name + "-wal").stat().st_size > 2_000_000
        main_bytes = sum(p.stat().st_size for p in (tmp_path / "app").glob("*.db"))
        main_bytes += (tmp_path / "gateway/gateway.db").stat().st_size
        monkeypatch.setattr(recovery, "MAX_BYTES", main_bytes + 1_000_000)
        with pytest.raises(ValueError, match="envelope"):
            backup(tmp_path / "app", tmp_path / "gateway", tmp_path / "too-large")
        monkeypatch.setattr(recovery, "MAX_BYTES", 6 * 1024**3)
        backup(tmp_path / "app", tmp_path / "gateway", tmp_path / "bundle")
        verify(tmp_path / "bundle")
        with sqlite3.connect(tmp_path / "bundle/app" / (key + ".db")) as copied:
            assert (
                copied.execute("SELECT length(data) FROM source_batches WHERE idem='wal-only'").fetchone()[0]
                == 2_000_000
            )
