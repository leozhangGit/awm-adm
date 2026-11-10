"""local authentication, race/failure boundaries and legacy authority migration."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from awm_adm.api import create_app
from awm_adm.application.admin import COOKIE, PASSWORD_WORK, Administrator
from awm_adm.application.auth import Authority
from awm_adm.runtime.http import create_internal
from awm_adm.runtime.protocol import RuntimeFault
from awm_adm.runtime.service import Runtime
from tests.test_application import OWNER, configuration, tank
from tests.test_application import app_runtime as app_runtime

PASSWORD = "authored local passphrase alpha"
NEXT = "authored local passphrase beta"
EMAIL = "owner@example.test"


def browser(rt):
    return TestClient(create_app(rt.config, runtime=rt, owner_token=OWNER))


def setup(c, token=OWNER):
    return c.post(
        "/api/v1/auth/setup",
        json={"email": " OWNER@EXAMPLE.TEST ", "password": PASSWORD, "bootstrap_token": token},
    )


def login(c, password=PASSWORD):
    return c.post("/api/v1/auth/login", json={"email": EMAIL, "password": password})


def csrf(c):
    return {"X-CSRF-Token": c.get("/api/v1/auth/me").json()["csrf"]}


def test_fresh_admin_cookie_csrf_scope_and_replay(app_runtime):
    rt = app_runtime
    key = tank(rt)
    auth = Authority(rt.store, OWNER)
    old = auth.issue(kind="session")
    scoped = auth.issue(adms=[key], permissions=["read"])
    with browser(rt) as c:
        assert c.get("/api/v1/auth/status").json() == {"setup_required": True}
        response = setup(c)
        assert response.status_code == 200
        cookie = response.headers.get_list("set-cookie")[-1]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/api;" in cookie
        assert c.cookies[COOKIE] not in response.text
        assert c.get("/api/v1/auth/me").json()["administrator"]["email"] == EMAIL
        assert setup(c).status_code == 401
        assert c.get("/api/v1/adms").json()["items"][0]["id"] == key
        headers = {"Authorization": "Bearer " + OWNER}
        assert c.get("/api/v1/adms", headers=headers).status_code == 401
        assert c.post("/api/v1/auth/sessions", headers=headers).status_code == 404
        headers = {"Authorization": "Bearer " + scoped["token"]}
        assert c.get("/api/v1/adms", headers=headers).status_code == 200
        assert c.get("/api/v1/auth/me", headers=headers).status_code == 403
        assert c.post("/api/v1/auth/logout").status_code == 403
        assert c.post("/api/v1/auth/logout", headers=csrf(c)).status_code == 200
        assert c.get("/api/v1/auth/me").status_code == 401
        c.cookies.set("awm_session", old["token"])
        assert c.get("/api/v1/adms").status_code == 401
        assert login(c).status_code == 200
        with rt.store.db() as db:
            row = db.execute("SELECT * FROM administrator").fetchone()
            assert row["password_hash"].startswith("$argon2id$v=19$m=19456,t=2,p=1$")
            assert PASSWORD not in json.dumps(dict(row))
        assert PASSWORD not in c.get("/api/v1/operations/diagnostics").text


def test_password_change_and_recovery_revoke_all_sessions_not_clients(app_runtime):
    rt = app_runtime
    admin = Administrator(Authority(rt.store, OWNER))
    key = tank(rt)
    token = admin.auth.issue(adms=[key], permissions=["read"])
    with browser(rt) as a, browser(rt) as b:
        setup(a)
        login(b)
        acookie, bcookie = a.cookies[COOKIE], b.cookies[COOKIE]
        assert (
            a.post(
                "/api/v1/auth/password",
                headers=csrf(a),
                json={"current_password": PASSWORD, "new_password": NEXT},
            ).status_code
            == 200
        )
        for c, cookie in ((a, acookie), (b, bcookie)):
            c.cookies.set(COOKIE, cookie)
            assert c.get("/api/v1/auth/me").status_code == 401
            c.cookies.clear()
        assert login(a).status_code == 401
        assert login(a, NEXT).status_code == 200
        first = admin.ticket("recovery")
        second = admin.ticket("recovery")
        body = {"reset_token": first["token"], "password": PASSWORD}
        assert b.post("/api/v1/auth/recover", json=body).status_code == 401
        body["reset_token"] = second["token"]
        assert b.post("/api/v1/auth/recover", json=body).status_code == 200
        assert b.post("/api/v1/auth/recover", json=body).status_code == 401
        assert a.get("/api/v1/auth/me").status_code == 401
        assert login(b).status_code == 200
        assert b.get("/api/v1/adms", headers={"Authorization": "Bearer " + token["token"]}).status_code == 200
        assert admin.metadata()["session_generation"] == 3


def test_expiry_throttling_restart_and_expired_bootstrap(tmp_path):
    config = configuration(tmp_path / "store")
    rt = Runtime(config, start_scheduler=False)
    with browser(rt) as c:
        with rt.store.db() as db:
            db.execute("UPDATE auth_control SET legacy_until=0")
        assert setup(c).status_code == 401
        admin = Administrator(Authority(rt.store, OWNER))
        ticket = admin.ticket("bootstrap")
        assert setup(c, ticket["token"]).status_code == 200
        cookie = c.cookies[COOKIE]
        for _ in range(5):
            assert login(c, "wrong").status_code == 401
        assert login(c).status_code == 429
    rt.close()
    rt = Runtime(config, start_scheduler=False)
    try:
        with browser(rt) as c:
            c.cookies.set(COOKIE, cookie)
            assert c.get("/api/v1/auth/me").status_code == 200
            assert login(c).status_code == 429  # Durable, not reset by process restart.
            admin = Administrator(Authority(rt.store, OWNER))
            reset = admin.ticket("recovery")
            with rt.store.db() as db:
                db.execute("UPDATE auth_tickets SET expires=0")
                db.execute("UPDATE credentials SET expires=0")
            assert c.get("/api/v1/auth/me").status_code == 401
            assert (
                c.post(
                    "/api/v1/auth/recover", json={"reset_token": reset["token"], "password": NEXT}
                ).status_code
                == 401
            )
            reset = admin.ticket("recovery")
            assert (
                c.post(
                    "/api/v1/auth/recover", json={"reset_token": reset["token"], "password": NEXT}
                ).status_code
                == 200
            )
            assert login(c, NEXT).status_code == 200
    finally:
        rt.close()


def test_private_recovery_role_separation_and_concurrent_setup(app_runtime):
    rt = app_runtime
    tokens = {"owner": OWNER, "worker": "w" * 48, "gateway": "g" * 48}
    with TestClient(create_internal(rt, tokens)) as c:
        for role in ("worker", "gateway"):
            assert (
                c.post(
                    "/internal/v3/auth/bootstrap",
                    headers={"Authorization": "Bearer " + tokens[role]},
                    json={},
                ).status_code
                == 403
            )
        result = c.post(
            "/internal/v3/auth/bootstrap", headers={"Authorization": "Bearer " + OWNER}, json={}
        ).json()

    def create(_):
        with browser(rt) as c:
            return setup(c, result["token"]).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(create, range(4)))
    assert statuses.count(200) == 1
    assert set(statuses) <= {200, 401, 429}
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM administrator").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM auth_tickets").fetchone()[0] == 0
    with browser(rt) as c:
        assert c.post("/internal/v3/auth/recovery", json={}).status_code == 404


@pytest.mark.parametrize(
    "route,body",
    [
        ("setup", {"email": EMAIL, "password": PASSWORD, "bootstrap_token": OWNER}),
        ("login", {"email": EMAIL, "password": PASSWORD}),
        ("recover", {"password": PASSWORD, "reset_token": OWNER}),
    ],
)
def test_auth_json_origin_boundary_and_secret_redaction(app_runtime, route, body):
    with browser(app_runtime) as c:
        url = "/api/v1/auth/" + route
        assert c.post(url, json=body, headers={"Origin": "http://evil.test"}).status_code == 403
        assert c.post(url, json=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert (
            c.post(url, content=json.dumps(body), headers={"Content-Type": "text/plain"}).status_code == 415
        )
        invalid = c.post(url, json={**body, "extra": OWNER})
        assert invalid.status_code == 422 and OWNER not in invalid.text and PASSWORD not in invalid.text
        assert (
            c.post(url, content=b"x" * 2_097_153, headers={"Content-Type": "application/json"}).status_code
            == 413
        )
        assert (
            c.post(
                url, content='{"password":"a","password":"b"}', headers={"Content-Type": "application/json"}
            ).status_code
            == 400
        )


def test_session_forgery_and_no_password_work_backlog(app_runtime):
    with browser(app_runtime) as c:
        setup(c)
        cookie = c.cookies[COOKIE]
        c.cookies.clear()
        c.cookies.set(COOKIE, cookie[:-1] + ("z" if cookie[-1] != "z" else "x"))
        assert c.get("/api/v1/auth/me").status_code == 401
        with PASSWORD_WORK:
            assert login(c).status_code == 429
        c.cookies.clear()
        assert login(c).status_code == 200
        assert c.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "forged"}).status_code == 403


def test_operator_writes_private_file_without_secret_stdout(app_runtime, tmp_path, capsys):
    from awm_adm.runtime.operator import main

    token_file, output = tmp_path / "operator", tmp_path / "reset"
    token_file.write_text(OWNER)
    args = ["--token-file", str(token_file), "bootstrap", "--output", str(output)]
    with patch(
        "awm_adm.runtime.operator.exchange", return_value={"token": "s" * 64, "expires_in": 900}
    ) as exchange:
        assert main(args) == 0
        assert output.stat().st_mode & 0o777 == 0o600
        assert output.read_text().strip() == "s" * 64
        assert "s" * 64 not in capsys.readouterr().out
        assert main(args) == 1
        assert exchange.call_count == 1


def test_migration_journal_resumes_before_runtime_starts(tmp_path):
    root = tmp_path / "store"
    rt = Runtime(configuration(root), start_scheduler=False)
    key = tank(rt)
    rt.close()
    # Simulate V2 storage by removing exactly M1's additive registry structures.
    with sqlite3.connect(root / "registry.db") as db:
        from .migration_support import remove_admin

        remove_admin(db)
        from tests.migration_support import remove_conversations

        remove_conversations(db)
        db.execute("PRAGMA user_version=7")
    with sqlite3.connect(root / f"{key}.db") as db:
        db.execute("PRAGMA user_version=16")
    with pytest.raises(RuntimeFault, match="Unsupported database"):
        Runtime(configuration(root), start_scheduler=False)
    with sqlite3.connect(root / "registry.db") as db:
        assert db.execute("SELECT status FROM installation_upgrade").fetchone()[0] == "migrating"
    with sqlite3.connect(root / f"{key}.db") as db:
        from tests.migration_support import remove_conversations

        remove_conversations(db)
        db.execute("PRAGMA user_version=7")
    rt = Runtime(configuration(root), start_scheduler=False)
    try:
        assert rt.store.info(key)["status"] == "ready"
        with rt.store.db() as db:
            assert db.execute("SELECT status,target FROM installation_upgrade").fetchone()[:] == ("ready", 15)
    finally:
        rt.close()


def test_recovery_attempts_and_unicode_password_bounds(app_runtime):
    admin = Administrator(Authority(app_runtime.store, OWNER))
    with browser(app_runtime) as c:
        assert setup(c).status_code == 200
        token = admin.ticket("recovery")["token"]
        for _ in range(5):
            assert (
                c.post(
                    "/api/v1/auth/recover", json={"reset_token": "invalid" * 10, "password": NEXT}
                ).status_code
                == 401
            )
        assert (
            c.post("/api/v1/auth/recover", json={"reset_token": token, "password": NEXT}).status_code == 429
        )
        token = admin.ticket("recovery")["token"]
        assert (
            c.post("/api/v1/auth/recover", json={"reset_token": token, "password": "short"}).status_code
            == 422
        )
        assert (
            c.post("/api/v1/auth/recover", json={"reset_token": token, "password": NEXT}).status_code == 200
        )
        assert login(c, NEXT).status_code == 200


def test_login_never_clears_separate_v2_cookie(app_runtime):
    with browser(app_runtime) as c:
        response = setup(c)
        assert response.status_code == 200
        assert all(not value.startswith("awm_session=") for value in response.headers.get_list("set-cookie"))
        response = c.post("/api/v1/auth/logout", headers=csrf(c))
        assert all(not value.startswith("awm_session=") for value in response.headers.get_list("set-cookie"))
