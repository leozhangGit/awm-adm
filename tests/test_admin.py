"""Login-free workspace, browser boundary, retired routes and schema-16 upgrade."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from awm_adm.api import create_app
from awm_adm.application.auth import AppendAuthority
from awm_adm.runtime.http import create_internal
from awm_adm.runtime.service import Runtime
from tests.test_application import OWNER, configuration, tank
from tests.test_application import app_runtime as app_runtime


def browser(rt, **kw):
    return TestClient(create_app(rt.config, runtime=rt), **kw)


@pytest.mark.parametrize(
    "path", ["status", "setup", "login", "logout", "me", "recover", "password", "tokens", "sessions"]
)
def test_authentication_routes_are_retired_without_side_effects(app_runtime, path):
    with browser(app_runtime) as c:
        for method in ("GET", "POST", "DELETE"):
            response = c.request(method, "/api/v1/auth/" + path, json={})
            assert response.status_code == 404
            assert "set-cookie" not in response.headers
        assert c.get("/api/v1/adms").status_code == 200
    with app_runtime.store.db() as db:
        assert db.execute("SELECT count(*) FROM administrator").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM credentials").fetchone()[0] == 0
    assert app_runtime.learning.usage()["calls"] == 0


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "null"},
        {"Origin": "https://evil.example"},
        {"Origin": "http://localhost:9528"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Host": "evil.example"},
    ],
)
def test_foreign_web_requests_cannot_read_or_mutate(app_runtime, headers):
    with browser(app_runtime) as c:
        assert c.get("/api/v1/adms", headers=headers).status_code == 403
        assert c.post("/api/v1/adms", headers=headers, json={"name": "unwanted"}).status_code == 403
        assert c.options(
            "/api/v1/adms", headers={**headers, "Access-Control-Request-Method": "POST"}
        ).status_code in {403, 405}
    assert not app_runtime.store.list()


def test_forms_and_remote_peers_cannot_bypass_local_boundary(app_runtime):
    with browser(app_runtime) as c:
        assert c.post("/api/v1/adms", data={"name": "unwanted"}).status_code == 415
        assert (
            c.post(
                "/api/v1/adms",
                json={"name": "local", "mode": "backward", "idempotency_key": "local-create"},
                headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
            ).status_code
            == 202
        )
    with browser(app_runtime, client=("203.0.113.1", 9999)) as c:
        assert (
            c.get(
                "/api/v1/adms", headers={"X-Forwarded-For": "127.0.0.1", "X-AWM-ADM-Client": "codex-local/1"}
            ).status_code
            == 403
        )
    with TestClient(
        create_app(app_runtime.config, runtime=app_runtime, ingress={"172.29.0.1"}),
        client=("172.29.0.1", 9000),
        base_url="http://127.0.0.1:9527",
    ) as c:
        assert c.get("/api/v1/adms").status_code == 200
    with TestClient(
        create_app(app_runtime.config, runtime=app_runtime, ingress={"172.29.0.1"}),
        client=("172.29.0.2", 9000),
        base_url="http://127.0.0.1:9527",
    ) as c:
        assert c.get("/api/v1/adms").status_code == 403


def test_upgrade_preserves_model_history_and_actor_and_needs_no_account(tmp_path):
    config = configuration(tmp_path / "store")
    rt = Runtime(config, start_scheduler=False)
    key = tank(rt)
    before = rt.store.revision(key)
    issued = AppendAuthority(rt.store).issue(adms=[key])
    with rt.store.db() as db:
        db.execute(
            "INSERT INTO administrator VALUES(1,'historic-owner','owner@example.test','historic-hash',7)"
        )
        db.execute("DROP TABLE local_workspace")
        db.execute("PRAGMA user_version=16")
    rt.close()
    rt = Runtime(config, start_scheduler=False)
    try:
        assert rt.store.revision(key) == before
        with browser(rt) as c:
            first = c.get("/api/v1/system").json()["local_service"]["installation_id"]
            assert c.get(f"/api/v1/adms/{key}/model").status_code == 200
            assert c.get("/api/v1/connection").status_code == 200
        with rt.store.db() as db:
            assert db.execute("SELECT uid,generation FROM administrator").fetchone()[:] == (
                "historic-owner",
                7,
            )
            assert (
                db.execute("SELECT revoked FROM credentials WHERE id=?", (issued["id"],)).fetchone()[0] == 1
            )
            assert db.execute("PRAGMA user_version").fetchone()[0] == 17
        rt.close()
        rt = Runtime(config, start_scheduler=False)
        with browser(rt) as c:
            assert c.get("/api/v1/system").json()["local_service"]["installation_id"] == first
            assert c.get(f"/api/v1/adms/{key}").status_code == 200
        assert rt.learning.usage()["calls"] == 0
    finally:
        rt.close()


def test_internal_machine_authority_remains_and_auth_tickets_are_retired(app_runtime):
    with TestClient(
        create_internal(
            app_runtime, {"owner": OWNER, "worker": "worker-fixture", "gateway": "gateway-fixture"}
        )
    ) as c:
        assert c.get("/internal/m2/adms").status_code == 401
        assert c.get("/internal/m2/adms", headers={"Authorization": "Bearer " + OWNER}).status_code == 200
        assert (
            c.post(
                "/internal/v3/auth/bootstrap", json={}, headers={"Authorization": "Bearer " + OWNER}
            ).status_code
            == 404
        )


def test_workspace_migration_rolls_back_on_failure(tmp_path):
    from awm_adm.runtime.storage import migrate

    path = tmp_path / "registry.db"
    with sqlite3.connect(path) as db:
        migrate(db, "registry")
        db.execute("DROP TABLE local_workspace")
        db.execute("PRAGMA user_version=16")

    class Fail(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.startswith("PRAGMA user_version=17"):
                raise RuntimeError("authored rollback fault")
            return super().execute(sql, *args)

    with sqlite3.connect(path, factory=Fail) as db:
        with pytest.raises(RuntimeError):
            migrate(db, "registry")
        assert db.execute("PRAGMA user_version").fetchone()[0] == 16
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='local_workspace'").fetchone()
