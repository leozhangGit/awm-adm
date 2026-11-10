"""deletion and owner-control fault checks on disposable isolated instances."""

from uuid import uuid4

import pytest

from awm_adm.runtime.protocol import RuntimeFault, loads
from awm_adm.runtime.service import Runtime

from .test_application import app_runtime as app_runtime
from .test_application import client, envelope, tank
from .test_learning_service import advance, connection, episode
from .test_learning_service import rig as rig


def delete_input(rt, key):
    info = rt.store.info(key)
    return {
        "idempotency_key": str(uuid4()),
        "expected_revision": info["revision_id"],
        "expected_epoch": info["policy_epoch"],
        "confirm_name": info["name"],
        "confirm_delete": True,
    }


def finish(rt, operation, gw=None):
    for _ in range(12):
        rt.lifecycle.tick()
        if gw:
            gw.synchronize()
        result = rt.lifecycle.view(operation)
        if result["stage"] == "deleted":
            return result
    raise AssertionError(rt.lifecycle.view(operation))


def test_named_deletion_fences_content_and_preserves_independent_copy(app_runtime):
    rt = app_runtime
    key = tank(rt)
    snapshot = rt.store.snapshot(key)
    clone = rt.create("Independent copy", snapshot=snapshot)["id"]
    cloned_snapshot = rt.store.snapshot(clone)
    req = rt.coordinator.submit(key, envelope())
    export = rt.coordinator.operation("export", {"idempotency_key": "export-before-delete"}, adm=key)
    rt.coordinator.run_operation()
    assert rt.coordinator.operation_info(export["operation_id"])["result"]
    body = delete_input(rt, key)
    with client(rt) as c:
        for bad in (
            {**body, "confirm_name": "wrong"},
            {**body, "confirm_delete": False},
            {**body, "expected_epoch": 999},
        ):
            assert c.request("DELETE", f"/api/v1/adms/{key}", json=bad).status_code == 409
        response = c.request("DELETE", f"/api/v1/adms/{key}", json=body)
        assert response.status_code == 202
        operation = response.json()["operation_id"]
        assert c.request("DELETE", f"/api/v1/adms/{key}", json=body).json()["operation_id"] == operation
        for suffix in ("", "/model", "/requests", "/events", "/requirements"):
            assert c.get(f"/api/v1/adms/{key}{suffix}").status_code == 410
        assert c.get(f"/api/v1/adms/{key}/conversations?channel=ask").status_code == 410
        assert c.post(f"/api/v1/adms/{key}/requests", json=envelope("late")).status_code == 410
        assert c.get(f"/api/v1/operations/{export['operation_id']}").json()["result"] is None
        finish(rt, operation)
        assert c.request("DELETE", f"/api/v1/adms/{key}", json=body).json()["stage"] == "deleted"
        assert (
            c.request("DELETE", f"/api/v1/adms/{key}", json={**body, "confirm_name": "other"}).status_code
            == 409
        )
    assert not list(rt.store.root.glob(key + ".db*"))
    with rt.store.db() as db:
        old = db.execute(
            "SELECT body,result FROM operations WHERE id=?", (export["operation_id"],)
        ).fetchone()
        assert loads(old["body"]) == {} and old["result"] is None
    assert req["request_id"]
    assert rt.query(clone, {"op": "capabilities"})["result"]["status"] == "succeeded"
    assert rt.store.snapshot(clone) == cloned_snapshot


@pytest.mark.parametrize("stage", ["requested", "fenced", "draining", "purging", "deleted"])
def test_restart_at_every_deletion_boundary_keeps_fence(app_runtime, stage):
    rt = app_runtime
    key = rt.create("Delete after crash")["id"]
    body = delete_input(rt, key)
    op = rt.lifecycle.request(key, body)["operation_id"]
    while rt.lifecycle.view(op)["stage"] != stage:
        assert rt.lifecycle.tick()
    config = rt.config
    rt.close()
    with_runtime = Runtime(config, start_scheduler=False)
    try:
        with pytest.raises(RuntimeFault, match="delet"):
            with_runtime.store.info(key)
        finish(with_runtime, op)
        assert with_runtime.lifecycle.request(key, body)["stage"] == "deleted"
        assert not list(with_runtime.store.root.glob(key + ".db*"))
    finally:
        with_runtime.close()


def test_cleanup_failure_is_resumable_without_reopening(app_runtime, monkeypatch):
    rt = app_runtime
    key = rt.create("Blocked cleanup")["id"]
    op = rt.lifecycle.request(key, delete_input(rt, key))["operation_id"]
    for _ in range(3):
        rt.lifecycle.tick()
    original = rt.store.root.__class__.unlink

    def denied(path, *a, **kw):
        if path.name == key + ".db":
            raise PermissionError("authored cleanup interruption")
        return original(path, *a, **kw)

    with monkeypatch.context() as m:
        m.setattr(rt.store.root.__class__, "unlink", denied)
        rt.lifecycle.tick()
    view = rt.lifecycle.view(op)
    assert view["stage"] == "blocked" and view["resume_stage"] == "purging"
    with pytest.raises(RuntimeFault):
        rt.store.snapshot(key)
    rt.lifecycle.retry(op, view["version"])
    finish(rt, op)


def test_append_and_scoped_tokens_revoked_but_other_model_authority_preserved(app_runtime):
    rt = app_runtime
    key = rt.create("Delete token target")["id"]
    other = rt.create("Keep target")["id"]
    with client(rt) as c:
        token = c.post(
            "/api/v1/auth/tokens", json={"adms": [key, other], "permissions": ["read", "submit"]}
        ).json()
        op = rt.lifecycle.request(key, delete_input(rt, key))["operation_id"]
        finish(rt, op)
        headers = {"Authorization": "Bearer " + token["token"]}
        assert c.get(f"/api/v1/adms/{key}", headers=headers).status_code == 403
        assert c.get(f"/api/v1/adms/{other}", headers=headers).status_code == 200
        assert (
            c.request(
                "DELETE", f"/api/v1/adms/{other}", headers=headers, json=delete_input(rt, other)
            ).status_code
            == 403
        )


def test_unknown_call_does_not_keep_model_content_and_late_usage_only_settles(rig):
    rt, gw = rig
    c = connection(rt, gw)
    key = rt.create("Sensitive model to delete")["id"]
    ep = episode(rt, key, c)
    advance(rt, key, ep["id"], "acquiring")
    job = rt.learning.claim()
    assert job
    grant = rt.learning.authorize(job["grant_id"], job["lease"])
    gw.store.begin(job["grant_id"], grant["provenance"]["request_hash"], grant)
    before = rt.learning.usage()
    op = rt.lifecycle.request(key, delete_input(rt, key))["operation_id"]
    for _ in range(4):
        rt.lifecycle.tick()
    assert rt.lifecycle.view(op)["stage"] == "purging"
    assert not (rt.store.root / (key + ".db")).exists()
    assert rt.learning.usage() == before
    finish(rt, op, gw)
    row = gw.store.lookup(job["grant_id"])
    assert set(loads(row["request"])) == {"lease"}
    with rt.store.db() as db:
        safe = loads(db.execute("SELECT body FROM grants WHERE id=?", (job["grant_id"],)).fetchone()[0])
        assert "wire" not in safe and "provenance" not in safe and safe["episode"] is None
    outcome = {
        "status": "succeeded",
        "text": "PRIVATE MODEL CONTENT",
        "usage": {"input_tokens": 12, "output_tokens": 5},
    }
    gw.store.finish(job["grant_id"], outcome)
    gw.deliver(gw.store.lookup(job["grant_id"]))
    view = rt.learning.grant_view(job["grant_id"])
    assert not view["unresolved"] and view["input_tokens"] == 12 and view["output_tokens"] == 5
    assert "PRIVATE MODEL CONTENT" not in str(gw.store.lookup(job["grant_id"]))
    assert not (rt.store.root / (key + ".db")).exists()
    assert rt.learning.connection(c["id"])["enabled"]
    with pytest.raises(RuntimeFault):
        rt.learning.authorize(job["grant_id"], job["lease"])


def test_rename_and_future_only_mode_preserve_theory(app_runtime):
    rt = app_runtime
    key = tank(rt)
    info = rt.store.info(key)
    before = rt.store.snapshot(key)
    with client(rt) as c:
        r = c.patch(
            f"/api/v1/adms/{key}/name", json={"expected_name": info["name"], "name": "Water laboratory"}
        )
        assert r.status_code == 200 and r.json()["revision_id"] == info["revision_id"]
        assert (
            c.patch(
                f"/api/v1/adms/{key}/name", json={"expected_name": "stale", "name": "Different"}
            ).status_code
            == 409
        )
        switched = c.patch(
            f"/api/v1/adms/{key}/settings", json={"expected_epoch": info["policy_epoch"], "mode": "forward"}
        ).json()
        assert switched["mode"] == "forward" and switched["theory_version"] == info["theory_version"]
    assert rt.store.snapshot(key) == before


def test_managed_sources_tasks_and_uncertain_dollars_are_removed_without_refund(rig):
    from .test_intake import append_credential, pushed, started

    rt, gw = rig
    key, cid, task, meta, _ = started(rt, gw, queue=True)
    access = append_credential(rt, key, task)
    with client(rt) as c:
        assert (
            c.post(
                access["endpoint"], json=pushed(), headers={"Authorization": "Bearer " + access["token"]}
            ).status_code
            == 202
        )
    for _ in range(5):
        rt.sources.tick()
    job = rt.learning.claim()
    assert job
    body = rt.learning.authorize(job["grant_id"], job["lease"])
    gw.store.begin(job["grant_id"], body["provenance"]["request_hash"], body)
    allowance = body["allowance_id"]
    before = rt.learning.allowances.view(allowance)
    assert before["reserved_micro_usd"] > 0
    operation = rt.lifecycle.request(key, delete_input(rt, key))["operation_id"]
    finish(rt, operation, gw)
    after = rt.learning.allowances.view(allowance)
    with rt.store.db() as db:
        retained = db.execute(
            "SELECT reserved,settled FROM charges WHERE grant_id=?", (job["grant_id"],)
        ).fetchone()
    assert retained["settled"] is None
    assert after["reserved_micro_usd"] == retained["reserved"]
    assert after["reserved_micro_usd"] <= before["reserved_micro_usd"]
    assert after["settled_micro_usd"] == before["settled_micro_usd"]
    assert after["state"] == "closed" and after["scope_id"] == "deleted"
    with client(rt) as c:
        assert (
            c.post(
                access["endpoint"], json=pushed(), headers={"Authorization": "Bearer " + access["token"]}
            ).status_code
            == 401
        )
        for suffix in (f"conversations/{cid}", f"tasks/{task}", "attachments"):
            assert c.get(f"/api/v1/adms/{key}/{suffix}").status_code == 410
    with rt.store.db() as db:
        assert not db.execute("SELECT 1 FROM budget_children WHERE allowance_id=?", (allowance,)).fetchone()
        assert not db.execute("SELECT 1 FROM source_arrivals WHERE adm=?", (key,)).fetchone()
    assert not (rt.store.root / (key + ".db")).exists()
    assert meta["id"]


@pytest.mark.parametrize("point", ["before_begin", "in_transport"])
def test_gateway_race_cannot_restore_deleted_payload_or_dispatch_again(rig, monkeypatch, point):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    rt, gw = rig
    c = connection(rt, gw)
    key = rt.create("Racing gateway")["id"]
    ep = episode(rt, key, c)
    advance(rt, key, ep["id"], "acquiring")
    job = rt.learning.claim()
    assert job
    entered, release = Event(), Event()
    if point == "before_begin":
        original = gw.store.begin

        def delayed(*args, **kwargs):
            entered.set()
            assert release.wait(10)
            return original(*args, **kwargs)

        monkeypatch.setattr(gw.store, "begin", delayed)
    else:

        def delayed(*args, **kwargs):
            entered.set()
            assert release.wait(10)
            return {
                "status": "succeeded",
                "text": "PRIVATE LATE RESULT",
                "usage": {"input_tokens": 10, "output_tokens": 4},
            }

        monkeypatch.setattr("awm_adm.gateway.service.acquire", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(gw.dispatch, job["grant_id"], job["lease"])
        try:
            assert entered.wait(10)
            op = rt.lifecycle.request(key, delete_input(rt, key))["operation_id"]
            finish(rt, op, gw)
        finally:
            release.set()
        if point == "before_begin":
            with pytest.raises(ValueError):
                future.result(timeout=10)
        else:
            future.result(timeout=10)
    assert "PRIVATE LATE RESULT" not in str(gw.store.lookup(job["grant_id"]))
    assert not (rt.store.root / (key + ".db")).exists()
    assert rt.lifecycle.view(op)["stage"] == "deleted"
    before = rt.learning.usage()
    gw.dispatch(job["grant_id"], job["lease"])
    assert rt.learning.usage() == before


@pytest.mark.parametrize("kind", ["export", "local_request"])
def test_late_local_work_cannot_republish_or_recreate(rig, monkeypatch, kind):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    rt, _ = rig
    key = tank(rt)
    entered, release = Event(), Event()
    original = rt.supervisor.run

    def delayed(task, **kwargs):
        result = original(task, **kwargs)
        entered.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(rt.supervisor, "run", delayed)
    if kind == "export":
        op = rt.coordinator.operation("export", {"idempotency_key": "racing-export"}, adm=key)
        action = rt.coordinator.run_operation
    else:
        rt.coordinator.submit(key, envelope("racing-query"))
        lease = rt.store.claim_request(key)

        def action():
            return rt.coordinator.perform(key, lease)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(action)
        try:
            assert entered.wait(10)
            deletion = rt.lifecycle.request(key, delete_input(rt, key))["operation_id"]
            finish(rt, deletion)
        finally:
            release.set()
        future.result(timeout=10)
    assert not (rt.store.root / (key + ".db")).exists()
    if kind == "export":
        assert rt.coordinator.operation_info(op["operation_id"])["result"] is None


@pytest.mark.parametrize("grant_stage", ["ready", "leased", "known"])
def test_deleted_grant_accounting_is_known_or_conservative(rig, grant_stage):
    rt, gw = rig
    c = connection(rt, gw)
    key = rt.create("Grant stages")["id"]
    ep = episode(rt, key, c)
    advance(rt, key, ep["id"], "acquiring")
    if grant_stage != "ready":
        job = rt.learning.claim()
        assert job
        if grant_stage == "known":
            gw.dispatch(job["grant_id"], job["lease"])
    before = rt.learning.usage()
    op = rt.lifecycle.request(key, delete_input(rt, key))["operation_id"]
    finish(rt, op, gw)
    after = rt.learning.usage()
    if grant_stage == "known":
        assert after == before
    else:
        assert after == {"calls": 0, "input_tokens": 0, "output_tokens": 0, "unresolved": 0}


def test_archived_model_deletes_and_capacity_is_reusable(app_runtime):
    rt = app_runtime
    key = rt.create("Archived model")["id"]
    info = rt.store.info(key)
    rt.store.change(key, info["policy_epoch"], archive=True)
    op = rt.lifecycle.request(key, delete_input(rt, key))["operation_id"]
    finish(rt, op)
    new = rt.create("Fresh model")["id"]
    assert new != key and rt.store.info(new)["status"] == "ready"


def test_failed_drain_transaction_retries_same_intent_without_refunding(rig, monkeypatch):
    rt, gw = rig
    c = connection(rt, gw)
    key = rt.create("Transaction crash")["id"]
    ep = episode(rt, key, c)
    advance(rt, key, ep["id"], "acquiring")
    job = rt.learning.claim()
    rt.learning.authorize(job["grant_id"], job["lease"])
    original = rt.lifecycle._advance

    def fail_after_drain(db, operation, stage):
        if stage == "draining":
            raise OSError("authored failed phase commit")
        return original(db, operation, stage)

    op = rt.lifecycle.request(key, delete_input(rt, key))["operation_id"]
    rt.lifecycle.tick()
    with monkeypatch.context() as m:
        m.setattr(rt.lifecycle, "_advance", fail_after_drain)
        rt.lifecycle.tick()
    view = rt.lifecycle.view(op)
    assert view["stage"] == "blocked"
    rt.lifecycle.retry(op, view["version"])
    finish(rt, op, gw)
    assert rt.learning.usage()["unresolved"] == 1


def test_cookie_csrf_and_competing_deletions(app_runtime):
    from concurrent.futures import ThreadPoolExecutor

    rt = app_runtime
    key = rt.create("Exact confirmation")["id"]
    body = delete_input(rt, key)
    with client(rt) as c:
        from .test_admin import setup

        c.headers.pop("Authorization")
        assert setup(c).status_code == 200
        login = c.get("/api/v1/auth/me").json()
        assert c.request("DELETE", f"/api/v1/adms/{key}", json=body).status_code == 403
        assert (
            c.request(
                "DELETE", f"/api/v1/adms/{key}", json=body, headers={"X-CSRF-Token": login["csrf"]}
            ).status_code
            == 202
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: rt.lifecycle.request(key, body), range(2)))
    assert replies[0]["operation_id"] == replies[1]["operation_id"]
    with pytest.raises(RuntimeFault):
        rt.lifecycle.request(key, {**body, "idempotency_key": str(uuid4())})
    finish(rt, replies[0]["operation_id"])


def test_unexpected_artifact_blocks_without_following_symlink(app_runtime, tmp_path):
    rt = app_runtime
    key = rt.create("Symlink guard")["id"]
    op = rt.lifecycle.request(key, delete_input(rt, key))["operation_id"]
    for _ in range(3):
        rt.lifecycle.tick()
    model = rt.store.root / (key + ".db")
    preserved = tmp_path / "saved-model.db"
    model.rename(preserved)
    model.symlink_to(preserved)
    rt.lifecycle.tick()
    view = rt.lifecycle.view(op)
    assert view["stage"] == "blocked" and preserved.exists()
    model.unlink()
    preserved.rename(model)
    rt.lifecycle.retry(op, view["version"])
    finish(rt, op)


def test_failed_creation_can_be_removed_but_initialization_cannot(app_runtime):
    rt = app_runtime
    key = rt.store.reserve("Failed import")
    body = {
        "idempotency_key": "failed-import-delete",
        "expected_revision": None,
        "expected_epoch": None,
        "confirm_name": "Failed import",
        "confirm_delete": True,
    }
    with pytest.raises(RuntimeFault):
        rt.lifecycle.request(key, body)
    rt.store.failed_creation(key)
    op = rt.lifecycle.request(key, body)["operation_id"]
    finish(rt, op)
    assert all(r["id"] != key for r in rt.store.list())


@pytest.mark.parametrize("stage", ["requested", "fenced", "draining", "purging", "deleted"])
def test_paired_restore_preserves_deletion_and_uncertain_accounting(tmp_path, stage):
    from cryptography.fernet import Fernet

    from awm_adm.gateway.service import Gateway
    from awm_adm.gateway.store import GatewayStore
    from awm_adm.operations.backup import backup, restore

    from .test_application import configuration

    rt = Runtime(configuration(tmp_path / "app"), start_scheduler=False)
    master = Fernet.generate_key()
    vault = GatewayStore(tmp_path / "gateway", master)
    gw = Gateway(vault, lambda route, body: rt.learning.synchronize(**body))
    try:
        c = connection(rt, gw)
        key = rt.create("Delete through restore")["id"]
        other = tank(rt)
        ep = episode(rt, key, c)
        advance(rt, key, ep["id"], "acquiring")
        job = rt.learning.claim()
        body = rt.learning.authorize(job["grant_id"], job["lease"])
        vault.begin(job["grant_id"], body["provenance"]["request_hash"], body)
        op = rt.lifecycle.request(key, delete_input(rt, key))["operation_id"]
        while rt.lifecycle.view(op)["stage"] != stage:
            rt.lifecycle.tick()
            if stage == "deleted":
                gw.synchronize()
        usage = rt.learning.usage()
    finally:
        rt.close()
        vault.close()
    backup(tmp_path / "app", tmp_path / "gateway", tmp_path / "backup")
    restore(tmp_path / "backup", tmp_path / "restored")
    rt = Runtime(configuration(tmp_path / "restored/app"), start_scheduler=False)
    vault = GatewayStore(tmp_path / "restored/gateway", master)

    def exchange(route, body):
        if route == "synchronize":
            return rt.learning.synchronize(**body)
        if route == "outcome":
            return rt.learning.outcome(body["grant_id"], body["lease"], body["outcome"])
        raise AssertionError("Restore cannot dispatch")

    gw = Gateway(vault, exchange)
    try:
        finish(rt, op, gw)
        assert rt.learning.usage() == usage
        assert not rt.learning.settings()["remote_calls_enabled"]
        assert not (rt.store.root / (key + ".db")).exists()
        assert rt.query(other, {"op": "capabilities"})["result"]["status"] == "succeeded"
    finally:
        rt.close()
        vault.close()


def test_deletion_pagination_separates_active_work_from_recent_history(app_runtime):
    rt = app_runtime
    operations = []
    for name in ("First", "Second", "Still cleaning"):
        key = rt.create(name)["id"]
        op = rt.lifecycle.request(key, delete_input(rt, key))["operation_id"]
        operations.append(op)
        if name != "Still cleaning":
            finish(rt, op)
    assert [x["operation_id"] for x in rt.lifecycle.listing(scope="active")["items"]] == operations[2:]
    page = rt.lifecycle.listing(limit=1, scope="completed")
    assert page["items"][0]["operation_id"] == operations[1]
    next_page = rt.lifecycle.listing(after=page["next_cursor"], limit=1, scope="completed")
    assert next_page["items"][0]["operation_id"] == operations[0]
    assert not rt.lifecycle.listing(after=next_page["next_cursor"], scope="completed")["items"]


def test_scope_cancellation_kills_child_and_preserves_other_model(monkeypatch):
    import subprocess
    import sys
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from awm_adm.runtime.supervisor import Supervisor

    original = subprocess.Popen
    started = Event()
    children = []

    def delayed(_command, **kwargs):
        process = original([sys.executable, "-I", "-c", "import time; time.sleep(60)"], **kwargs)
        children.append(process)
        started.set()
        return process

    supervisor = Supervisor(2)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with monkeypatch.context() as m:
                m.setattr("awm_adm.runtime.supervisor.subprocess.Popen", delayed)
                result = pool.submit(
                    supervisor.run, {"limits": {"max_duration_ms": 2000}}, scope="deleted-model"
                )
                assert started.wait(5)
                supervisor.cancel_scope("deleted-model")
                with pytest.raises(RuntimeFault):
                    result.result(timeout=5)
                assert children[0].poll() is not None
                with pytest.raises(RuntimeFault) as denied:
                    supervisor.run({"limits": {"max_duration_ms": 1000}}, scope="deleted-model")
                assert denied.value.code == "gone"

            # A separate model still owns usable local capacity.
            def healthy(_command, **kwargs):
                return original([sys.executable, "-I", "-c", 'print(\'{"ok":true,"value":7}\')'], **kwargs)

            m = monkeypatch.context()
            with m as patched:
                patched.setattr("awm_adm.runtime.supervisor.subprocess.Popen", healthy)
                assert supervisor.run({"limits": {"max_duration_ms": 1000}}, scope="kept-model") == 7
    finally:
        supervisor.close()
