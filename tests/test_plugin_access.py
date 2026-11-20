"""Service additions used by the narrow project connector; all providers are recorded."""

from fastapi.testclient import TestClient

from awm_adm.api import create_app
from awm_adm.interaction.admissions import AdmissionView
from tests.interaction_support import definition, reply
from tests.test_application import app_runtime as app_runtime
from tests.test_direct_ask import recorded
from tests.test_direct_teach import has_ready, preparation, pump
from tests.test_learning_service import rig as rig


def test_new_direct_work_checks_revision_but_identical_replay_recovers(rig):
    rt, gw = rig
    recorded(rt, gw, {})
    key = rt.create("Context fixture")["id"]
    with TestClient(create_app(rt.config, runtime=rt)) as c:
        path = f"/api/v1/adms/{key}/ask"
        revision = rt.store.info(key)["revision_id"]
        body = {"text": "What can the model do?", "idempotency_key": "recover-one"}
        first = c.post(path, json=body, headers={"If-Match": revision})
        assert first.status_code == 202
        rt.store.change(key, 0, mode="forward")
        replay = c.post(path, json=body, headers={"If-Match": revision})
        assert replay.json()["id"] == first.json()["id"]
        stale = c.post(path, json={**body, "idempotency_key": "fresh"}, headers={"If-Match": revision})
        assert stale.status_code == 409 and stale.json()["code"] == "stale_context"
        assert (
            c.post(path, json={**body, "text": "Different"}, headers={"If-Match": revision}).status_code
            == 409
        )
        with rt.store.db(key) as db:
            assert db.execute("SELECT count(*) FROM direct_interactions").fetchone()[0] == 1
        assert rt.learning.usage()["calls"] == 0


def test_teach_receipts_bind_actual_publication_and_definition_effects(rig):
    rt, gw = rig
    key, uid = preparation(rt, gw)
    base = rt.store.info(key)["revision_id"]
    pump(rt, key, uid, lambda _: has_ready(rt))
    reply(rt, definition())
    task = pump(rt, key, uid, lambda t: t["execution"]["phase"] == "narration")
    view = rt.interactions.get(key, uid)
    receipt = AdmissionView.model_validate(view["teaching"]["admissions"][0])
    assert receipt.classification == "accepted"
    assert receipt.decision_revision == base
    assert receipt.accepted_revision == rt.store.info(key)["revision_id"]
    assert receipt.accepted_revision != base
    assert receipt.effects["added"] and not receipt.effects["removed"]
    assert receipt.effects["declarations"].keys() == receipt.effects["support"].keys()
    assert all(x.startswith("sha256:") for x in receipt.effects["declarations"].values())
    assert task["execution"]["steps"][0]["status"] == "accepted"


def test_compose_preflight_rejects_off_host_and_private_publication():
    import runpy
    from pathlib import Path

    import pytest

    validate = runpy.run_path(str(Path(__file__).parents[1] / "scripts/check_local_deployment.py"))[
        "validate"
    ]
    import copy

    good = {
        "services": {
            "app": {"ports": [{"host_ip": "127.0.0.1", "published": "9527", "target": 9527}]},
            "provider-gateway": {},
        }
    }
    assert validate(good) == 9527
    bad = copy.deepcopy(good)
    bad["services"]["app"]["ports"][0]["host_ip"] = "0.0.0.0"
    with pytest.raises(ValueError):
        validate(bad)
    bad = copy.deepcopy(good)
    bad["services"]["provider-gateway"]["ports"] = [{"target": 8090}]
    with pytest.raises(ValueError):
        validate(bad)
