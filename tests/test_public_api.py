"""One public namespace, disjoint histories and retired routes without side effects."""

import json
import re
from pathlib import Path

from awm_adm.runtime.service import Runtime
from tests.test_admin import browser, csrf, setup
from tests.test_application import app_runtime as app_runtime
from tests.test_application import client


def test_public_contract_is_current_and_unambiguous(app_runtime):
    with client(app_runtime) as c:
        contract = c.get("/api/v1/openapi.json").json()
        assert contract == json.loads((Path(__file__).parents[1] / "contracts/openapi.json").read_text())
        assert contract["info"]["version"] == "0.3.0"
        paths = contract["paths"]
        assert all(p.startswith("/api/v1/") or p.startswith("/health/") for p in paths)
        operations = [
            (method, re.sub(r"\{[^}]+\}", "{}", path), value["operationId"])
            for path, methods in paths.items()
            for method, value in methods.items()
        ]
        assert len(operations) == len({(m, p) for m, p, _ in operations})
        assert len(operations) == len({uid for _, _, uid in operations})
        assert "/api/v1/adms/{adm}/interpretation-sessions" in paths
        assert "/api/v1/adms/{adm}/interpretations" in paths
        assert "/api/v1/adms/{adm}/conversations" in paths
        assert set(paths["/api/v1/adms/{adm}"]) == {"get", "delete"}


def test_retired_routes_are_absent_and_do_not_mutate(app_runtime):
    key = app_runtime.create("Retirement boundary")["id"]
    with client(app_runtime) as c:
        for prefix in ("/api/v2", "/api/v3"):
            for method in ("GET", "POST"):
                assert c.request(method, prefix + "/adms", json={}).status_code == 404
        for method, path in (
            ("POST", "/auth/sessions"),
            ("GET", "/auth/sessions/current"),
            ("DELETE", "/auth/sessions/current"),
            ("POST", "/snapshot-imports"),
            ("POST", f"/adms/{key}/attachment-metadata"),
        ):
            response = c.request(method, "/api/v1" + path, json={})
            assert response.status_code == 404
            assert "set-cookie" not in response.headers
        assert c.get("/api/v1/adms").json()["items"][0]["id"] == key
        assert app_runtime.learning.usage()["calls"] == 0
        # No credentials, operations or attachment records are created by obsolete routes.
        with app_runtime.store.db() as db:
            assert db.execute("SELECT count(*) FROM credentials").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM operations").fetchone()[0] == 0
        with app_runtime.store.db(key) as db:
            assert db.execute("SELECT count(*) FROM chat_attachments").fetchone()[0] == 0


def test_preview_and_chat_histories_are_separate_and_survive_restart(app_runtime):
    rt = app_runtime
    key = rt.create("Separate histories")["id"]
    base = f"/api/v1/adms/{key}"
    with browser(rt) as c:
        assert setup(c).status_code == 200
        headers = csrf(c)
        # Same input identity is deliberately valid in the two independent resource stores.
        preview = c.post(
            base + "/interpretation-sessions",
            json={"idempotency_key": "same-id", "title": "Preview"},
            headers=headers,
        )
        chat = c.post(
            base + "/conversations",
            json={"idempotency_key": "same-id", "title": "Chat", "channel": "ask"},
            headers=headers,
        )
        assert preview.status_code == chat.status_code == 201
        preview_id, chat_id = preview.json()["id"], chat.json()["id"]
        assert preview_id != chat_id
        token = c.post(
            "/api/v1/auth/tokens", json={"adms": [key], "permissions": ["read", "submit"]}, headers=headers
        ).json()
        scoped = {"Authorization": "Bearer " + token["token"]}
        assert c.get(base + "/interpretation-sessions", headers=scoped).status_code == 200
        assert c.get(base + "/conversations?channel=ask", headers=scoped).status_code == 403
        cookies = c.cookies
    rt.close()
    reopened = Runtime(rt.config, start_scheduler=False)
    try:
        with browser(reopened) as c:
            c.cookies.update(cookies)
            assert c.get("/api/v1/auth/me").status_code == 200
            assert [x["id"] for x in c.get(base + "/interpretation-sessions").json()["items"]] == [preview_id]
            assert [x["id"] for x in c.get(base + "/conversations?channel=ask").json()["items"]] == [chat_id]
            assert c.get(base + f"/interpretation-sessions/{chat_id}").status_code == 404
            assert c.get(base + f"/conversations/{preview_id}").status_code == 404
            assert reopened.learning.usage()["calls"] == 0
    finally:
        reopened.close()
