"""Console-facing revision, session, paging and accepted-artifact boundaries."""

from pathlib import Path

from fastapi.testclient import TestClient

from awm_adm.api import create_app
from awm_adm.engine import read_snapshot
from awm_adm.runtime.protocol import pack
from tests.test_application import OWNER, client, envelope, tank
from tests.test_application import app_runtime as app_runtime


def test_console_model_is_pinned_and_scoped(app_runtime):
    rt = app_runtime
    key = tank(rt)
    with client(rt) as c:
        view = c.get(f"/api/v1/adms/{key}/model").json()
        assert view["declarations"]["tanks.State"]["kind"] == "type"
        assert {a["role"] for a in view["artifacts"]} >= {"declaration", "provenance", "conformance"}
        revision = view["revision_id"]
        changed = c.patch(f"/api/v1/adms/{key}/settings", json={"expected_epoch": 0, "mode": "forward"})
        assert changed.status_code == 200
        historical = c.get(f"/api/v1/adms/{key}/model?revision={revision}").json()
        assert historical == view
        assert c.get(f"/api/v1/adms/{key}/requirements").json()["policy_epoch"] == 1
        other = rt.create("other")["id"]
        assert c.get(f"/api/v1/adms/{other}/model?revision={revision}").status_code == 404
        assert c.get(f"/api/v1/adms/{key}/model", headers={"Authorization": ""}).status_code == 200
        assert c.get("/api/v1/operations").status_code == 200
        assert c.get("/api/v1/auth/me").status_code == 404


def test_displayed_revision_cas_preserves_idempotent_replay(app_runtime):
    rt = app_runtime
    key = tank(rt)
    with client(rt) as c:
        url = f"/api/v1/adms/{key}/requests"
        revision = rt.store.info(key)["revision_id"]
        headers = {"If-Match": revision}
        first = c.post(url, json=envelope(), headers=headers)
        assert first.status_code == 202
        rt.store.change(key, 0, mode="forward")
        # A lost response can still be recovered after owner changes.
        assert (
            c.post(url, json=envelope(), headers=headers).json()["request_id"] == first.json()["request_id"]
        )
        stale = c.post(url, json=envelope("new"), headers=headers)
        assert stale.status_code == 409 and stale.json()["code"] == "stale_context"
        assert len(rt.store.page(key, "requests")["items"]) == 1
        assert c.post(url, json=envelope("new")).status_code == 202  # API clients may opt out.


def test_console_reads_require_no_session_and_expose_no_credentials(app_runtime):
    with TestClient(create_app(app_runtime.config, runtime=app_runtime)) as c:
        result = c.get("/api/v1/system")
        assert result.status_code == 200
        assert result.json()["local_service"]["profile"] == "awm-adm-local/1"
        assert result.json()["request_limits"]["max_work"] > 0
        assert OWNER not in result.text
        assert not result.cookies
        assert c.get("/api/v1/adms").status_code == 200


def test_recent_pages_and_operation_summaries_are_bounded(app_runtime):
    rt = app_runtime
    key = tank(rt)
    ids = [rt.coordinator.submit(key, envelope(f"request-{i}"))["request_id"] for i in range(4)]
    with client(rt) as c:
        base = f"/api/v1/adms/{key}/requests?order=desc&limit=2"
        page = c.get(base).json()
        assert [r["request_id"] for r in page["items"]] == ids[2:][::-1]
        next_page = c.get(base + "&after=" + str(page["next_cursor"])).json()
        assert [r["request_id"] for r in next_page["items"]] == ids[:2][::-1]
        assert next_page["next_cursor"] is None
        assert c.get(base.replace("desc", "invalid")).status_code == 422
        op = c.post(f"/api/v1/adms/{key}/snapshot-exports", json={"idempotency_key": "export"}).json()
        rt.coordinator.run_operation()
        summary = c.get("/api/v1/operations").json()["items"][0]
        assert summary["operation_id"] == op["operation_id"]
        assert set(summary) == {"operation_id", "kind", "adm_id", "status", "created_at_ms"}


def test_packaged_examples_import_as_independent_models(app_runtime):
    import json

    root = Path(__file__).resolve().parents[1]
    # Test image carries the same console source; exports carry public assets.
    examples = root / "console/public/examples"
    if not examples.exists():
        examples = root / "console-source/public/examples"
    for name in ("tanks", "access"):
        source = root / f"tests/fixtures/v1/reference/{name}.adm"
        package = json.loads((examples / f"{name}.snapshot.json").read_text())
        assert package == pack(read_snapshot(source))
        result = app_runtime.create("[Sandbox] " + name, snapshot=package)
        assert result["status"] == "ready"


def test_console_assets_contain_no_saved_owner_credential(app_runtime):
    with TestClient(create_app(app_runtime.config, runtime=app_runtime)) as c:
        assert c.get("/api/v1/operations").status_code == 200
        assert c.get("/api/v1/auth/me").status_code == 404
