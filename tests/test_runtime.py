import asyncio
import io
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from awm_adm.api import create_app
from awm_adm.config import AppConfig
from awm_adm.engine import Instance, build_certificate, read_snapshot
from awm_adm.runtime import operator
from awm_adm.runtime import supervisor as supervision
from awm_adm.runtime.http import create_internal
from awm_adm.runtime.protocol import RuntimeFault, pack
from awm_adm.runtime.service import Runtime
from awm_adm.runtime.storage import APPLICATION_ID, Store, migrate
from awm_adm.runtime.supervisor import Supervisor

FIXTURES = Path(__file__).parent / "fixtures/v1/reference"


def config(root, **changes):
    return AppConfig.model_validate(
        {"server": {"data_dir": str(root)}, "proof": {"lean_executable": "/nonexistent/lean"}, **changes}
    )


@pytest.fixture
def runtime(tmp_path):
    value = Runtime(config(tmp_path / "runtime"))
    try:
        yield value
    finally:
        value.close()


def test_two_instances_and_bound_results_survive_restart(tmp_path):
    cfg = config(tmp_path / "runtime")
    first = Runtime(cfg)
    empty = first.create("empty")
    tank = first.create("tanks", mode="forward", snapshot=pack(read_snapshot(FIXTURES / "tanks.adm")))
    query = {
        "op": "find_plan",
        "module": "tanks",
        "initial_state": {"left": 0, "right": 0},
        "goal": "tanks.four_litres",
    }
    run = first.query(tank["id"], query)
    assert run["result"]["steps"] == 6
    first.close()
    second = Runtime(cfg)
    try:
        assert second.store.info(tank["id"]) == tank
        assert second.store.info(empty["id"]) == empty
        assert second.store.run_info(tank["id"], run["id"]) == run
        assert second.query(tank["id"], query)["result"]["steps"] == 6
        assert second.query(empty["id"], {"op": "capabilities"})["result"]["status"] == "succeeded"
        with pytest.raises(RuntimeFault, match="Unknown run"):
            second.store.run_info(empty["id"], run["id"])
    finally:
        second.close()


def test_single_owner_and_safe_paths(runtime, tmp_path):
    with pytest.raises(RuntimeFault) as error:
        Store(runtime.store.root, runtime.config.runtime)
    assert error.value.code == "already_owned"
    for key in ("../registry", "/tmp/anything", "not-a-uuid"):
        with pytest.raises(RuntimeFault):
            runtime.store.info(key)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "v1.db").write_bytes(b"do not open")
    with pytest.raises(RuntimeFault) as error:
        Store(foreign, runtime.config.runtime)
    assert error.value.code == "foreign_store"
    assert (foreign / "v1.db").read_bytes() == b"do not open"
    link = tmp_path / "link"
    link.symlink_to(runtime.store.root, target_is_directory=True)
    with pytest.raises(RuntimeFault):
        Store(link, runtime.config.runtime)


def test_creation_intent_and_expired_leases_reconcile(runtime):
    orphan = runtime.store.reserve("interrupted before store creation")
    instance = runtime.create("ready")
    context = runtime.store.info(instance["id"])
    lease = runtime.store.claim(instance["id"], {"op": "capabilities"}, context, -1)
    next_lease = runtime.store.claim(instance["id"], {"op": "capabilities"}, context, 10)
    assert runtime.store.run_info(instance["id"], lease["id"])["status"] == "interrupted"
    with pytest.raises(RuntimeFault) as error:
        runtime.store.finish(instance["id"], lease, {})
    assert error.value.code == "stale_lease"
    component = runtime.store.component_claim("worker")
    cfg = runtime.config
    runtime.close()
    reopened = Runtime(cfg)
    try:
        assert reopened.store.info(orphan)["status"] == "failed"
        assert reopened.store.run_info(instance["id"], next_lease["id"])["status"] == "interrupted"
        with pytest.raises(RuntimeFault):
            reopened.store.finish(instance["id"], next_lease, {})
        with pytest.raises(RuntimeFault):
            reopened.store.component_renew(component)
        assert not any(reopened.store.components().values())
    finally:
        reopened.close()


def test_committed_instance_recovers_unfinished_registry_intent(runtime):
    instance = runtime.create("committed")
    with runtime.store.db() as connection:
        connection.execute("UPDATE instances SET status='creating' WHERE id=?", (instance["id"],))
    cfg = runtime.config
    runtime.close()
    reopened = Runtime(cfg)
    try:
        assert reopened.store.info(instance["id"]) == instance
    finally:
        reopened.close()


def test_registry_completion_failure_keeps_committed_instance_recoverable(runtime):
    original = runtime.store.db

    @contextmanager
    def fail_completion(instance=None, **kwargs):
        instance_files = list(runtime.store.root.glob("????????-????-????-????-????????????.db"))
        if instance is None and instance_files:
            raise sqlite3.OperationalError("authored registry commit failure")
        with original(instance, **kwargs) as connection:
            yield connection

    with patch.object(runtime.store, "db", side_effect=fail_completion):
        with pytest.raises(sqlite3.OperationalError):
            runtime.create("committed before registry failure")
    row = runtime.store.list()[0]
    assert row["status"] == "creating"
    cfg = runtime.config
    runtime.close()
    reopened = Runtime(cfg)
    try:
        assert reopened.store.info(row["id"])["status"] == "ready"
        assert reopened.query(row["id"], {"op": "capabilities"})["result"]["status"] == "succeeded"
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "damage", ["missing_instance", "corrupt_instance", "missing_registry", "changed_payload"]
)
def test_damaged_store_fails_without_reset(runtime, damage):
    instance = runtime.create("persist")
    cfg = runtime.config
    root = runtime.store.root
    runtime.close()
    path = root / (instance["id"] + ".db")
    if damage == "missing_instance":
        path.unlink()
    elif damage == "corrupt_instance":
        path.write_bytes(b"corrupt")
    elif damage == "missing_registry":
        (root / "registry.db").unlink()
    else:
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE versions SET payload=?", (b"{}",))
    with pytest.raises((RuntimeFault, sqlite3.DatabaseError)):
        Runtime(cfg)
    assert path.exists() == (damage != "missing_instance")


def test_owned_schema_migration_and_rollback(tmp_path):
    path = tmp_path / "owned.db"
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
    connection.execute(
        "CREATE TABLE instances (id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL)"
    )
    connection.execute("PRAGMA user_version=1")
    connection.execute("INSERT INTO instances VALUES ('example','preserved','failed')")
    migrate(connection, "registry")
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 15
    assert connection.execute("SELECT name FROM instances").fetchone()[0] == "preserved"
    connection.close()

    class Failing(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.startswith("PRAGMA user_version=15"):
                raise sqlite3.OperationalError("authored migration fault")
            return super().execute(sql, *args)

    connection = sqlite3.connect(":memory:", isolation_level=None, factory=Failing)
    with pytest.raises(sqlite3.OperationalError):
        migrate(connection, "instance")
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
    assert connection.execute("SELECT name FROM sqlite_master").fetchall() == []
    connection.close()


def test_foreign_and_future_schema_rejected():
    for version, application in ((5, 0), (999, APPLICATION_ID)):
        connection = sqlite3.connect(":memory:", isolation_level=None)
        connection.execute(f"PRAGMA application_id={application}")
        connection.execute(f"PRAGMA user_version={version}")
        with pytest.raises(RuntimeFault):
            migrate(connection, "instance")
        assert connection.execute("PRAGMA user_version").fetchone()[0] == version
        connection.close()


def test_failed_import_and_storage_failure_leave_no_ready_model(runtime):
    with pytest.raises(RuntimeFault):
        runtime.create("bad", snapshot={"manifest": "invalid-base64", "files": {}})
    assert runtime.store.list()[0]["status"] == "failed"
    with patch.object(
        runtime.store, "install", side_effect=sqlite3.OperationalError("authored disk failure")
    ):
        with pytest.raises(sqlite3.OperationalError):
            runtime.create("disk-full")
    assert all(row["status"] == "failed" for row in runtime.store.list())


def test_caps_and_cold_admission_exhaustion_are_explicit(tmp_path):
    instance = Runtime(config(tmp_path, runtime={"max_adms": 1, "queue_items_per_adm": 1}))
    try:
        adm = instance.create("one")
        with pytest.raises(RuntimeFault):
            instance.create("two")
        result = instance.query(adm["id"], {"op": "capabilities"}, limits={"max_work": 1})
        assert result["result"]["status"] == "inconclusive"
        assert "gaps" not in result["result"]
        with pytest.raises(RuntimeFault):
            instance.query(adm["id"], {"op": "capabilities"})
        for limits in ({"max_work": True}, {"max_work": 1_000_001}, {"unknown": 1}):
            with pytest.raises(RuntimeFault):
                instance.limits(limits)
    finally:
        instance.close()


def test_corrupt_child_binding_cannot_be_published(runtime):
    adm = runtime.create("check")
    with patch.object(runtime.supervisor, "run", return_value={"status": "succeeded", "binding": {}}):
        with pytest.raises(RuntimeFault) as error:
            runtime.query(adm["id"], {"op": "capabilities"})
    assert error.value.code == "invalid_result"
    with runtime.store.db(adm["id"]) as connection:
        row = connection.execute("SELECT status,result FROM runs").fetchone()
        assert tuple(row) == ("interrupted", None)


def test_component_expiry_and_new_claim_fence_old_token(runtime):
    original = runtime.store.component_claim("worker")
    assert runtime.store.component_renew(original)["status"] == "idle"
    newer = runtime.store.component_claim("worker")
    with pytest.raises(RuntimeFault):
        runtime.store.component_renew(original)
    with runtime.store.db() as connection:
        connection.execute("UPDATE components SET expires=0")
    assert not runtime.store.components()["worker"]
    with pytest.raises(RuntimeFault):
        runtime.store.component_renew(newer)


def test_private_roles_and_public_listener_separation(runtime):
    tokens = {role: role * 48 for role in ("owner", "worker", "gateway")}

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_internal(runtime, tokens)), base_url="http://test"
        ) as client:
            assert (await client.get("/internal/m2/adms")).status_code == 401
            worker = {"Authorization": "Bearer " + tokens["worker"]}
            owner = {"Authorization": "Bearer " + tokens["owner"]}
            gateway = {"Authorization": "Bearer " + tokens["gateway"]}
            assert (
                await client.post("/internal/m2/adms", headers=worker, json={"name": "forbidden"})
            ).status_code == 403
            created = await client.post("/internal/m2/adms", headers=owner, json={"name": "allowed"})
            assert created.status_code == 200
            invalid = await client.post(
                "/internal/m2/adms", headers=owner, json={"name": "invalid", "secret": "canary-never-echo"}
            )
            assert invalid.status_code == 422 and "canary-never-echo" not in invalid.text
            for raw in (b'{"name":"a","name":"b"}', b'{"name":NaN}', b"[" * 1000):
                rejected = await client.post("/internal/m2/adms", headers=owner, content=raw)
                assert rejected.status_code == 400 and rejected.json() == {"error": "invalid_json"}
            lease = (await client.post("/internal/m2/components/claim", headers=worker, json={})).json()
            assert (
                await client.post("/internal/m2/components/renew", headers=gateway, json=lease)
            ).status_code == 403
            assert (
                await client.post("/internal/m2/components/renew", headers=worker, json=lease)
            ).status_code == 200
            assert (await client.get("/internal/m2/work", headers=worker)).json()["job"] is None
            oversized = await client.post("/internal/m2/adms", headers=owner, content=b" " * 2_097_153)
            assert oversized.status_code == 413
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime.config, runtime=runtime)),
            base_url="http://test",
        ) as public:
            assert (await public.get("/health/ready")).status_code == 200
            assert (await public.get("/internal/m2/adms")).status_code == 404
            assert (await public.post("/api/v1/adms", json={})).status_code == 404
            availability = (await public.get("/api/v1/system")).json()["available"]
            assert availability["local_serving"] and availability["worker"]
            assert availability["learning"] and not availability["providers"]

    asyncio.run(check())


def test_unavailable_lean_does_not_disable_other_local_queries(runtime):
    assert not runtime.status()["lean"]
    adm = runtime.create("offline")
    assert runtime.query(adm["id"], {"op": "capabilities"})["result"]["status"] == "succeeded"
    package = read_snapshot(FIXTURES / "tanks.adm")
    model = Instance.restore(package).model
    tank = runtime.create("tanks", snapshot=pack(package))
    certificate = build_certificate(
        model, "tanks", {"left": 0, "right": 0}, "tanks.four_litres", transitions=[]
    )
    outcome = runtime.query(
        tank["id"], {"op": "check_certificate", "certificate": certificate, "backend": "lean"}
    )["result"]
    assert outcome["certificate_status"] == "unavailable" and outcome["status"] == "needs_input"
    assert outcome["guarantee"] is None


def test_supervisor_shutdown_kills_running_group_and_rejects_new_work(monkeypatch):
    parent = Supervisor(1)
    started = Event()
    original = subprocess.Popen
    captured = []

    def slow(_command, **kwargs):
        assert set(kwargs["env"]) == {"PATH", "LANG", "TMPDIR"}
        process = original([sys.executable, "-I", "-c", "import time; time.sleep(60)"], **kwargs)
        captured.append(process)
        started.set()
        return process

    monkeypatch.setenv("AWM_TEST_SECRET_CANARY", "not-forwarded")
    with patch.object(supervision.subprocess, "Popen", side_effect=slow), ThreadPoolExecutor(1) as pool:
        future = pool.submit(parent.run, {"limits": {"max_duration_ms": 5000}})
        assert started.wait(3)
        with pytest.raises(RuntimeFault) as error:
            parent.run({"limits": {"max_duration_ms": 5000}})
        assert error.value.code == "busy"
        parent.close()
        with pytest.raises(RuntimeFault):
            future.result(timeout=5)
    assert captured[0].poll() is not None
    with pytest.raises(RuntimeFault):
        parent.run({"limits": {"max_duration_ms": 5000}})


def test_supervisor_wall_deadline_terminates_child():
    supervisor = Supervisor(1)
    original = subprocess.Popen
    captured = []

    def slow(_command, **kwargs):
        process = original([sys.executable, "-I", "-c", "import time; time.sleep(60)"], **kwargs)
        captured.append(process)
        return process

    with patch.object(supervision.subprocess, "Popen", side_effect=slow):
        with pytest.raises(RuntimeFault) as error:
            supervisor.run({"limits": {"max_duration_ms": 1}})
        assert error.value.code == "resource_exhausted"
    assert captured[0].poll() is not None
    supervisor.close()


def test_operator_snapshot_stdin_uses_checked_archive(monkeypatch, capsys):
    raw = (FIXTURES / "tanks.adm").read_bytes()
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    with (
        patch.object(operator, "secret", return_value="unused-local-test-token"),
        patch.object(operator, "exchange", return_value={"id": "new-instance"}) as request,
    ):
        assert operator.main(["create", "clone", "--snapshot", "-"]) == 0
        assert request.call_args.args[2]["snapshot"] == pack(read_snapshot(FIXTURES / "tanks.adm"))
    assert "new-instance" in capsys.readouterr().out
