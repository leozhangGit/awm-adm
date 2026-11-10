"""contracts and authored race/crash faults; automatic tests stay offline."""

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from awm_adm.api import create_app
from awm_adm.application.coordinator import wrap_result
from awm_adm.application.store import TERMINAL
from awm_adm.config import AppConfig
from awm_adm.contracts import RequestRecord
from awm_adm.engine import read_snapshot
from awm_adm.runtime.compute import compute
from awm_adm.runtime.protocol import RuntimeFault, pack
from awm_adm.runtime.service import Runtime

OWNER = "authored-test-owner-" + "x" * 48
FIXTURES = Path(__file__).parent / "fixtures/v1/reference"


def configuration(root):
    return AppConfig.model_validate(
        {"server": {"data_dir": str(root)}, "proof": {"lean_executable": "/nonexistent/lean"}}
    )


@pytest.fixture
def app_runtime(tmp_path):
    runtime = Runtime(configuration(tmp_path / "store"), start_scheduler=False)
    try:
        yield runtime
    finally:
        runtime.close()


def client(runtime):
    return TestClient(
        create_app(runtime.config, runtime=runtime, owner_token=OWNER),
        headers={"Authorization": "Bearer " + OWNER},
    )


def envelope(key="request-1", query=None, **kw):
    return {"idempotency_key": key, "query": query or {"op": "capabilities"}, **kw}


def tank(runtime):
    return runtime.create("tanks", snapshot=pack(read_snapshot(FIXTURES / "tanks.adm")))["id"]


def execute(runtime, key):
    lease = runtime.store.claim_request(key)
    assert lease
    runtime.coordinator.perform(key, lease)
    return runtime.store.request(key, lease["id"])


def plan():
    return {
        "op": "find_plan",
        "module": "tanks",
        "initial_state": {"left": 0, "right": 0},
        "goal": "tanks.four_litres",
    }


def test_async_http_idempotency_and_atomic_completion(app_runtime):
    rt = app_runtime
    key = tank(rt)
    with client(rt) as c:
        url = f"/api/v1/adms/{key}/requests"
        body = envelope(query=plan())
        first = c.post(url, json=body)
        assert first.status_code == 202
        uid = first.json()["request_id"]
        assert first.json()["status"] == "received"
        assert c.post(url, json=body).json()["request_id"] == uid
        assert c.post(url, json=envelope(query={**plan(), "max_depth": 0})).status_code == 409
        done = execute(rt, key)
        RequestRecord.model_validate({k: done[k] for k in RequestRecord.model_fields})
        assert done["result"]["value"]["steps"] == 6
        assert done["result"]["binding"]["selection"] == {"kind": "module_all", "actions": None}
        assert done["result"]["claims"] == ["valid_witness", "shortest_action_count"]
        assert c.post(url, json=body).json()["result"] == done["result"]
        events = c.get(f"/api/v1/adms/{key}/events").json()["items"]
        assert [e["kind"] for e in events] == ["request.received", "request.evaluating", "request.succeeded"]
        assert events[-1]["attempt_id"] == done["attempt_id"]
        assert c.get(f"/api/v1/adms/{key}/requests?limit=0").status_code == 422
        assert c.get("/api/v1/openapi.json").json()["paths"][url.replace(key, "{adm}")]["post"]


def test_concurrent_retries_share_one_resource(app_runtime):
    key = tank(app_runtime)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: app_runtime.coordinator.submit(key, envelope()), range(16)))
    assert len({r["request_id"] for r in results}) == 1
    assert len(app_runtime.store.events(key)["items"]) == 1


def test_scoped_tokens_cross_adm_and_revocation(app_runtime):
    rt = app_runtime
    a = tank(rt)
    b = rt.create("other")["id"]
    with client(rt) as c:
        issued = c.post("/api/v1/auth/tokens", json={"adms": [a], "permissions": ["read", "submit"]}).json()
        headers = {"Authorization": "Bearer " + issued["token"]}
        assert [r["id"] for r in c.get("/api/v1/adms", headers=headers).json()["items"]] == [a]
        uid = c.post(f"/api/v1/adms/{a}/requests", json=envelope(), headers=headers).json()["request_id"]
        assert c.get(f"/api/v1/adms/{b}/requests/{uid}", headers=headers).status_code == 403
        assert c.get(f"/api/v1/adms/{b}/requests/{uid}").status_code == 404
        assert (
            c.patch(
                f"/api/v1/adms/{a}/settings", json={"expected_epoch": 0, "mode": "forward"}, headers=headers
            ).status_code
            == 403
        )
        assert c.get("/api/v1/openapi.json", headers=headers).status_code == 403
        assert c.delete("/api/v1/auth/tokens/" + issued["id"]).status_code == 200
        assert c.get(f"/api/v1/adms/{a}", headers=headers).status_code == 401
        with rt.store.db() as db:
            assert issued["token"] not in str([tuple(r) for r in db.execute("SELECT * FROM credentials")])


def test_session_csrf_origin_host_and_logout(app_runtime):
    key = app_runtime.create("session")["id"]
    with client(app_runtime) as c:
        from tests.test_admin import setup

        login = setup(c)
        assert login.status_code == 200 and "HttpOnly" in login.headers["set-cookie"]
        c.headers.pop("authorization")
        path = f"/api/v1/adms/{key}/settings"
        body = {"expected_epoch": 0, "mode": "forward"}
        assert c.patch(path, json=body).status_code == 403
        assert (
            c.patch(
                path,
                json=body,
                headers={"X-CSRF-Token": login.json()["csrf"], "Origin": "http://evil.example"},
            ).status_code
            == 403
        )
        assert c.get("/api/v1/adms", headers={"Host": "evil.example"}).status_code == 403
        assert (
            c.patch(
                path, json=body, headers={"X-CSRF-Token": login.json()["csrf"], "Origin": "http://testserver"}
            ).status_code
            == 200
        )
        assert (
            c.post("/api/v1/auth/logout", headers={"X-CSRF-Token": login.json()["csrf"]}).status_code == 200
        )
        assert c.get("/api/v1/adms").status_code == 401


@pytest.mark.parametrize(
    "raw", [b'{"name":"secret-value","name":"duplicate"}', b'{"x":NaN}', b"{", b"[" * 70 + b"]" * 70]
)
def test_strict_safe_json(app_runtime, raw):
    with client(app_runtime) as c:
        response = c.post("/api/v1/adms", content=raw, headers={"Content-Type": "application/json"})
        assert response.status_code == 400
        assert response.json()["error_profile"] == "awm-adm-error/2"
        assert "secret-value" not in response.text


def test_oversized_and_unknown_input(app_runtime):
    with client(app_runtime) as c:
        assert (
            c.post(
                "/api/v1/adms", content=b" " * 2_097_153, headers={"Content-Type": "application/json"}
            ).status_code
            == 413
        )
        assert c.post("/api/v1/adms", json={"credential": "never-echo"}).status_code == 422
        assert "never-echo" not in c.post("/api/v1/adms", json={"credential": "never-echo"}).text


def test_cancel_queued_running_and_late_publication(app_runtime):
    rt = app_runtime
    key = tank(rt)
    record = rt.coordinator.submit(key, envelope())
    uid = record["request_id"]
    lease = rt.store.claim_request(key)
    rev = rt.store.revision(key)
    local = compute(
        {
            "operation": "query",
            "snapshot": rev["snapshot"],
            "context": lease["context"],
            "query": lease["envelope"]["query"],
            "limits": rt.limits(),
        }
    )
    wrapped = wrap_result(key, lease, local)
    rt.coordinator.cancel(key, uid)
    with pytest.raises(RuntimeFault):
        rt.store.finish_request(key, lease, "succeeded", result=wrapped)
    assert rt.store.request(key, uid)["result"] is None
    rt.coordinator.cancel(key, uid)
    assert len(rt.store.events(key)["items"]) == 3
    uid2 = rt.coordinator.submit(key, envelope("second"))["request_id"]
    rt.coordinator.cancel(key, uid2)
    assert rt.store.claim_request(key) is None


def test_result_and_event_rollback_together(app_runtime):
    rt = app_runtime
    key = tank(rt)
    uid = rt.coordinator.submit(key, envelope())["request_id"]
    lease = rt.store.claim_request(key)
    with patch.object(rt.store, "emit", side_effect=sqlite3.OperationalError("authored outbox failure")):
        with pytest.raises(sqlite3.OperationalError):
            rt.store.finish_request(key, lease, "failed")
    assert rt.store.request(key, uid)["status"] == "evaluating"
    assert [e["kind"] for e in rt.store.events(key)["items"]] == ["request.received", "request.evaluating"]


def test_expiry_reclaim_retry_fences_old_attempt(app_runtime):
    rt = app_runtime
    key = tank(rt)
    uid = rt.coordinator.submit(key, envelope())["request_id"]
    old = rt.store.claim_request(key)
    with rt.store.db(key) as db:
        db.execute("UPDATE requests SET expires=0")
    rt.store.reclaim(key)
    assert rt.store.request(key, uid)["status"] == "inconclusive"
    rt.store.retry_request(key, uid)
    new = rt.store.claim_request(key)
    assert old["attempt"] != new["attempt"]
    with pytest.raises(RuntimeFault):
        rt.store.finish_request(key, old, "failed")
    rt.coordinator.perform(key, new)
    assert rt.store.request(key, uid)["status"] == "succeeded"
    assert [a["status"] for a in rt.store.request(key, uid)["attempts"]] == ["inconclusive", "succeeded"]


def test_restart_preserves_queue_and_interrupts_running(tmp_path):
    cfg = configuration(tmp_path / "restart")
    rt = Runtime(cfg, start_scheduler=False)
    key = tank(rt)
    uid = rt.coordinator.submit(key, envelope())["request_id"]
    rt.store.claim_request(key)
    queued = rt.coordinator.submit(key, envelope("queued"))["request_id"]
    rt.close()
    rt = Runtime(cfg, start_scheduler=False)
    try:
        assert rt.store.request(key, uid)["status"] == "inconclusive"
        assert rt.store.request(key, queued)["status"] == "received"
        assert execute(rt, key)["request_id"] == queued
    finally:
        rt.close()


def test_event_consumers_replay_sse_and_retention(app_runtime):
    rt = app_runtime
    key = tank(rt)
    rt.coordinator.submit(key, envelope())
    execute(rt, key)
    with client(rt) as c:
        url = f"/api/v1/adms/{key}"
        a = c.post(url + "/event-consumers", json={}).json()
        b = c.post(url + "/event-consumers", json={}).json()
        assert c.put(url + "/event-consumers/" + a["id"] + "/cursor", json={"cursor": 3}).status_code == 200
        assert (
            c.put(url + "/event-consumers/" + b["id"] + "/cursor", json={"cursor": 1}).json()["cursor"] == 1
        )
        events = c.get(
            url + "/events?once=true", headers={"Accept": "text/event-stream", "Last-Event-ID": key + ":1"}
        )
        assert (
            events.status_code == 200
            and "request.succeeded" in events.text
            and "request.received" not in events.text
        )
        assert (
            c.get(
                url + "/events?once=true", headers={"Accept": "text/event-stream", "Last-Event-ID": "other:1"}
            ).status_code
            == 422
        )
        assert c.get(url + "/events").json()["cursor"] == 3
        assert c.post(url + "/events/prune", json={"cursor": 2}).status_code == 200
        assert c.get(url + "/events?after=1").status_code == 410
        assert c.get(url + "/event-window").json()["earliest_cursor"] == 2
        assert c.get(url + "/events?after=2").json()["items"][0]["kind"] == "request.succeeded"


def test_policy_change_fences_computation_and_preserves_history(app_runtime):
    rt = app_runtime
    key = tank(rt)
    first = rt.coordinator.submit(key, envelope())["request_id"]
    done = execute(rt, key)
    second = rt.coordinator.submit(key, envelope("second"))["request_id"]
    lease = rt.store.claim_request(key)
    with client(rt) as c:
        url = f"/api/v1/adms/{key}"
        policy = c.get(url + "/requirements").json()["policy"]
        updated = c.put(url + "/requirements", json={"expected_epoch": 0, "policy": policy})
        assert updated.status_code == 200, updated.text
        assert updated.json()["policy_epoch"] == 1
        assert c.patch(url + "/settings", json={"expected_epoch": 0, "mode": "forward"}).status_code == 409
        assert rt.store.request(key, second)["status"] == "needs_input"
        with pytest.raises(RuntimeFault):
            rt.store.finish_request(key, lease, "succeeded", result=done["result"])
        assert rt.store.request(key, first)["result"] == done["result"]
        assert rt.store.request(key, first)["pinned_context"]["policy_epoch"] == 0
        assert rt.store.request(key, first)["current_context"]["policy_epoch"] == 1
        assert len(c.get(url + "/versions").json()["items"]) == 2


def test_changed_policy_during_validation_rejected(app_runtime):
    rt = app_runtime
    key = tank(rt)
    original = rt.supervisor.run

    def racing(task, **kw):
        result = original(task, **kw)
        rt.store.change(key, 0, mode="forward")
        return result

    with client(rt) as c, patch.object(rt.supervisor, "run", side_effect=racing):
        response = c.put(
            f"/api/v1/adms/{key}/requirements",
            json={"expected_epoch": 0, "policy": {"profile": "adm-conformance/0.1", "contracts": []}},
        )
    assert response.status_code == 409
    assert rt.store.info(key)["mode"] == "forward"


def test_snapshot_operations_idempotency_and_recheck(app_runtime):
    rt = app_runtime
    key = tank(rt)
    with client(rt) as c:
        created = c.post("/api/v1/adms", json={"name": "empty", "idempotency_key": "empty"})
        assert created.status_code == 202
        rt.coordinator.run_operation()
        empty = c.get("/api/v1/operations/" + created.json()["operation_id"]).json()
        assert empty["status"] == "succeeded"
        export = c.post(f"/api/v1/adms/{key}/snapshot-exports", json={"idempotency_key": "export"}).json()
        assert rt.coordinator.run_operation()
        package = c.get("/api/v1/operations/" + export["operation_id"]).json()["result"]["snapshot"]
        imported = c.post(
            "/api/v1/adms",
            json={"name": "clone", "idempotency_key": "clone", "snapshot": package},
        ).json()
        assert rt.coordinator.run_operation()
        done = c.get("/api/v1/operations/" + imported["operation_id"]).json()
        clone = done["result"]["adm_id"]
        assert clone != key
        assert (
            c.post(
                "/api/v1/adms",
                json={"name": "clone", "idempotency_key": "clone", "snapshot": package},
            ).json()["operation_id"]
            == imported["operation_id"]
        )
        rt.coordinator.submit(clone, envelope(query=plan()))
        assert execute(rt, clone)["result"]["value"]["steps"] == 6
        bad = c.post(
            "/api/v1/adms",
            json={"name": "bad", "idempotency_key": "bad", "snapshot": {"bad": True}},
        ).json()
        rt.coordinator.run_operation()
        assert c.get("/api/v1/operations/" + bad["operation_id"]).json()["status"] == "failed"


def test_explanations_are_scoped_and_finite_results_keep_claims(app_runtime):
    rt = app_runtime
    key = tank(rt)
    rt.coordinator.submit(key, envelope(query={**plan(), "max_depth": 0, "transitions": []}))
    done = execute(rt, key)
    assert done["result"]["binding"]["selection"] == {"kind": "explicit", "actions": []}
    assert done["result"]["claims"] == ["no_plan_within_bound"]
    rt.coordinator.submit(
        key, envelope("explain", {"op": "explain", "result_id": done["result"]["result_id"]})
    )
    explained = execute(rt, key)
    assert explained["result"]["value"]["explanation"] == done["result"]
    other = rt.create("other")["id"]
    rt.coordinator.submit(
        other, envelope("explain", {"op": "explain", "result_id": done["result"]["result_id"]})
    )
    assert execute(rt, other)["status"] == "failed"


def test_exhaustion_and_gap_never_claim_learning(app_runtime):
    rt = app_runtime
    key = rt.create("empty")["id"]
    rt.coordinator.submit(key, envelope(limits={"max_work": 1}, on_gap="learn"))
    done = execute(rt, key)
    assert done["status"] == "inconclusive" and done["learning_job_ids"] == []
    rt.coordinator.submit(key, envelope("gap", plan(), on_gap="learn"))
    gap = execute(rt, key)
    assert gap["status"] == "needs_input" and gap["learning_job_ids"] == []
    assert gap["error"]["details"]["learning_available"]
    assert gap["error"]["details"]["authorization_required"]


def test_background_scheduler_and_archive(tmp_path):
    rt = Runtime(configuration(tmp_path / "auto"))
    try:
        key = tank(rt)
        uid = rt.coordinator.submit(key, envelope(query=plan()))["request_id"]
        until = time.monotonic() + 5
        while rt.store.request(key, uid)["status"] not in TERMINAL and time.monotonic() < until:
            time.sleep(0.01)
        assert rt.store.request(key, uid)["status"] == "succeeded"
        rt.store.change(key, 0, archive=True)
        rt.coordinator.changed(key)
        with pytest.raises(RuntimeFault):
            rt.coordinator.submit(key, envelope("new"))
        assert rt.coordinator.submit(key, envelope(query=plan()))["request_id"] == uid
    finally:
        rt.close()


def test_active_child_receives_cancel_and_other_instance_serves(app_runtime):
    rt = app_runtime
    key = tank(rt)
    other = rt.create("other")["id"]
    uid = rt.coordinator.submit(key, envelope())["request_id"]
    lease = rt.store.claim_request(key)
    started = Event()
    stopped = Event()
    original = rt.supervisor.run

    def controlled(task, *, cancel=None):
        if task.get("context", {}).get("instance_id") == key:
            started.set()
            assert cancel.wait(3)
            stopped.set()
            raise RuntimeFault("cancelled", "authored pause")
        return original(task, cancel=cancel)

    with patch.object(rt.supervisor, "run", side_effect=controlled), ThreadPoolExecutor() as pool:
        running = pool.submit(rt.coordinator.perform, key, lease)
        assert started.wait(2)
        rt.coordinator.submit(other, envelope())
        assert execute(rt, other)["status"] == "succeeded"
        rt.coordinator.cancel(key, uid)
        running.result(timeout=3)
        assert stopped.is_set()
    assert rt.store.request(key, uid)["status"] == "cancelled"


def test_read_only_token_and_independent_consumer_ownership(app_runtime):
    rt = app_runtime
    key = tank(rt)
    with client(rt) as c:
        first = c.post("/api/v1/auth/tokens", json={"adms": [key], "permissions": ["read"]}).json()
        second = c.post("/api/v1/auth/tokens", json={"adms": [key], "permissions": ["read"]}).json()
        h1 = {"Authorization": "Bearer " + first["token"]}
        h2 = {"Authorization": "Bearer " + second["token"]}
        prefix = f"/api/v1/adms/{key}"
        assert c.post(prefix + "/requests", json=envelope(), headers=h1).status_code == 403
        consumer = c.post(prefix + "/event-consumers", json={}, headers=h1).json()
        assert (
            c.put(
                prefix + "/event-consumers/" + consumer["id"] + "/cursor", json={"cursor": 0}, headers=h2
            ).status_code
            == 404
        )
        with rt.store.db() as db:
            db.execute("UPDATE credentials SET expires=0 WHERE id=?", (first["id"],))
        assert c.get(prefix, headers=h1).status_code == 401


def test_valid_and_violating_owner_requirement_survives_export(app_runtime):
    rt = app_runtime
    key = tank(rt)

    def policy(value):
        return {
            "profile": "adm-conformance/0.1",
            "contracts": [
                {
                    "contract_id": "owner",
                    "origin": "Independent fixture requirement",
                    "required_symbols": ["tanks.State"],
                    "checks": [
                        {
                            "id": "constant",
                            "kind": "value",
                            "params": {},
                            "expression": {"op": "literal", "value": 1},
                            "expected": {"op": "literal", "value": value},
                        }
                    ],
                }
            ],
        }

    with client(rt) as c:
        url = f"/api/v1/adms/{key}"
        response = c.put(url + "/requirements", json={"expected_epoch": 0, "policy": policy(2)})
        assert response.status_code >= 400
        assert rt.store.info(key)["policy_epoch"] == 0
        valid = c.put(url + "/requirements", json={"expected_epoch": 0, "policy": policy(1)})
        assert valid.status_code == 200, valid.text
        assert c.get(url + "/requirements").json()["policy"] == policy(1)
        op = c.post(url + "/snapshot-exports", json={"idempotency_key": "policy-export"}).json()
        rt.coordinator.run_operation()
        package = c.get("/api/v1/operations/" + op["operation_id"]).json()["result"]["snapshot"]
        clone = rt.create("clone", snapshot=package)["id"]
        assert c.get(f"/api/v1/adms/{clone}/requirements").json()["policy"] == policy(1)


def test_corrupt_child_binding_cannot_publish(app_runtime):
    rt = app_runtime
    key = tank(rt)
    uid = rt.coordinator.submit(key, envelope())["request_id"]
    lease = rt.store.claim_request(key)
    with patch.object(rt.supervisor, "run", return_value={"status": "succeeded", "binding": {}}):
        rt.coordinator.perform(key, lease)
    assert rt.store.request(key, uid)["status"] == "failed"
    assert not any(e["kind"] == "request.succeeded" for e in rt.store.events(key)["items"])


def test_operation_restart_reconciles_committed_instance(tmp_path):
    cfg = configuration(tmp_path / "operations")
    rt = Runtime(cfg, start_scheduler=False)
    op = rt.coordinator.operation(
        "create", {"idempotency_key": "create", "name": "recover", "mode": "backward"}
    )
    key = rt.create("recover")["id"]
    with rt.store.db() as db:
        db.execute("UPDATE operations SET status='running',adm=? WHERE id=?", (key, op["operation_id"]))
    rt.close()
    rt = Runtime(cfg, start_scheduler=False)
    try:
        result = rt.coordinator.operation_info(op["operation_id"])
        assert result["status"] == "succeeded" and result["result"]["adm_id"] == key
        assert len(rt.store.list()) == 1
    finally:
        rt.close()


def test_schema_two_store_migrates_with_existing_model_and_run(tmp_path):
    cfg = configuration(tmp_path / "migration")
    rt = Runtime(cfg, start_scheduler=False)
    key = tank(rt)
    run = rt.query(key, {"op": "capabilities"})
    rt.close()
    # Reconstruct the exact M2 schema: remove all schema-3/4/5/6 tables.
    root = Path(cfg.server.data_dir)
    with sqlite3.connect(root / "registry.db") as db:
        from tests.migration_support import remove_admin

        remove_admin(db)
        for table in ("learning_control", "connections", "grants", "connection_tests", "source_arrivals"):
            db.execute("DROP TABLE " + table)
        db.execute("DROP TABLE operations")
        db.execute("DROP TABLE credentials")
        from tests.migration_support import remove_conversations

        remove_conversations(db)
        db.execute("PRAGMA user_version=2")
    with sqlite3.connect(root / (key + ".db")) as db:
        for table in (
            "control",
            "revisions",
            "requests",
            "attempts",
            "events",
            "consumers",
            "episodes",
            "interests",
            "learning_receipts",
            "language_profiles",
            "conversations",
            "interpretations",
            "language_executions",
            "teaching_drafts",
            "source_profiles",
            "feeds",
            "feed_runs",
            "feed_items",
            "feed_controls",
            "coverage_transitions",
            "source_versions",
            "source_heads",
            "source_batches",
            "source_jobs",
            "source_claims",
            "source_episodes",
            "source_support",
            "source_revalidations",
        ):
            db.execute("DROP TABLE " + table)
        from tests.migration_support import remove_conversations

        remove_conversations(db)
        db.execute("PRAGMA user_version=2")
    rt = Runtime(cfg, start_scheduler=False)
    try:
        assert rt.store.run_info(key, run["id"]) == run
        rt.coordinator.submit(key, envelope(query=plan()))
        assert execute(rt, key)["result"]["value"]["steps"] == 6
    finally:
        rt.close()


def test_owner_change_also_fences_private_operator_run(app_runtime):
    rt = app_runtime
    key = tank(rt)
    original = rt.supervisor.run

    def racing(task, **kw):
        result = original(task, **kw)
        rt.store.change(key, 0, mode="forward")
        return result

    with patch.object(rt.supervisor, "run", side_effect=racing), pytest.raises(RuntimeFault):
        rt.query(key, {"op": "capabilities"})
    with rt.store.db(key) as db:
        assert db.execute("SELECT status,result FROM runs").fetchone()["result"] is None


def test_cancellable_supervisor_delivers_complete_input_to_slow_reader():
    import subprocess
    import sys

    from awm_adm.runtime.supervisor import Supervisor

    original = subprocess.Popen

    def slow_reader(_command, **kwargs):
        return original(
            [
                sys.executable,
                "-I",
                "-c",
                "import time,sys,json; time.sleep(.3); data=json.load(sys.stdin); print(json.dumps({'ok':True,'value':len(data['payload'])}))",
            ],
            **kwargs,
        )

    supervisor = Supervisor(1)
    try:
        with patch("awm_adm.runtime.supervisor.subprocess.Popen", side_effect=slow_reader):
            assert (
                supervisor.run(
                    {"limits": {"max_duration_ms": 2000}, "payload": "x" * 1_000_000}, cancel=Event()
                )
                == 1_000_000
            )
    finally:
        supervisor.close()


def test_exported_openapi_matches_running_public_contract(app_runtime):
    exported = json.loads((Path(__file__).parents[1] / "contracts/openapi.json").read_text())
    with client(app_runtime) as c:
        response = c.get("/api/v1/openapi.json")
        assert response.status_code == 200
        assert response.json() == exported
