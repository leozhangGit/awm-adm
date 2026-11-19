"""Overview history filters do not purge records or hide deletion recovery."""

from .test_application import app_runtime as app_runtime
from .test_application import client
from .test_lifecycle import delete_input, finish


def test_recent_window_filters_before_limit_and_merges_deletions(app_runtime):
    rt = app_runtime
    cutoff = 1_795_000_000_000
    boundary = rt.coordinator.operation("create", {"idempotency_key": "boundary", "name": "Recent"})
    expired = []
    for n in range(51):
        op = rt.coordinator.operation("create", {"idempotency_key": f"old-{n}", "name": "Old"})
        expired.append(op["operation_id"])
    deleted_model = rt.create("Disposable")["id"]
    deletion = rt.lifecycle.request(deleted_model, delete_input(rt, deleted_model))["operation_id"]
    finish(rt, deletion)
    with rt.store.db() as db:
        db.execute("UPDATE operations SET created=?", (cutoff / 1000 - 0.001,))
        db.execute("UPDATE operations SET created=? WHERE id=?", (cutoff / 1000, boundary["operation_id"]))
        db.execute("UPDATE deletions SET created=? WHERE id=?", (cutoff / 1000 + 1, deletion))
    with client(rt) as c:
        rows = c.get(f"/api/v1/operations?since_ms={cutoff}&include_deletions=true").json()["items"]
        assert [r["operation_id"] for r in rows] == [deletion, boundary["operation_id"]]
        assert rows[0]["kind"] == "delete" and rows[0]["status"] == "deleted"
        assert [r["created_at_ms"] for r in rows] == [cutoff + 1000, cutoff]
        assert all("result" not in r and "inventory" not in r for r in rows)
        assert (
            c.get(f"/api/v1/operations?since_ms={cutoff + 1001}&include_deletions=true").json()["items"] == []
        )
        legacy = c.get("/api/v1/operations").json()["items"]
        assert len(legacy) == 50 and all(r["kind"] != "delete" for r in legacy)
        assert c.get(f"/api/v1/operations/{expired[0]}").status_code == 200
        assert c.get("/api/v1/operations?since_ms=-1").status_code == 422
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM operations").fetchone()[0] == 52
        assert db.execute("SELECT count(*) FROM deletions").fetchone()[0] == 1


def test_old_pending_deletion_remains_reachable_outside_recent_window(app_runtime):
    rt = app_runtime
    model = rt.create("Pending deletion")["id"]
    operation = rt.lifecycle.request(model, delete_input(rt, model))["operation_id"]
    with rt.store.db() as db:
        db.execute("UPDATE deletions SET created=1 WHERE id=?", (operation,))
    with client(rt) as c:
        assert c.get("/api/v1/operations?since_ms=2000&include_deletions=true").json()["items"] == []
        active = c.get("/api/v1/deletions?scope=active").json()["items"]
        assert len(active) == 1 and active[0]["operation_id"] == operation
        assert active[0]["created_at_ms"] == 1000
        assert active[0]["stage"] == "requested"
    assert rt.lifecycle.view(operation)["stage"] == "requested"
