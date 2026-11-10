"""Integrated administrative setup and isolation gates; never a remote provider."""

from uuid import uuid4

from .test_allowances import setup
from .test_application import app_runtime as app_runtime
from .test_application import client
from .test_learning_service import rig as rig


def test_readable_price_setup_is_exact_replayable_and_call_free(rig):
    rt, gw = rig
    conn, _ = setup(rt, gw)
    with client(rt) as http:
        path = f"/api/v1/connections/{conn['id']}/price-options"
        response = http.get(path)
        assert response.status_code == 200
        options = response.json()
        assert len(options["items"]) == 1 and options["items"][0]["synthetic"]
        price = options["items"][0]
        body = {k: options[k] for k in ("connection_id", "connection_version", "configuration_digest")}
        body.update(
            {
                k: price[k]
                for k in (
                    "bound_profile",
                    "input_micro_usd_per_million",
                    "output_micro_usd_per_million",
                    "valid_until_ms",
                )
            }
        )
        body["idempotency_key"] = str(uuid4())
        installed = http.post("/api/v1/prices", json=body)
        assert installed.status_code == 201
        assert http.post("/api/v1/prices", json=body).json() == installed.json()
        denied = http.post("/api/v1/prices", json={**body, "input_micro_usd_per_million": 1})
        assert denied.status_code == 409
        token = http.app.state.authority.issue(adms=[], permissions=["read", "submit"])
        http.cookies.clear()
        assert http.get(path, headers={"Authorization": "Bearer " + token["token"]}).status_code == 403
    assert rt.learning.usage()["calls"] == 0


def test_price_options_do_not_invent_a_profile_for_another_model(rig):
    rt, gw = rig
    conn, _ = setup(rt, gw)
    from unittest.mock import patch

    with patch.object(
        rt.learning, "connection", return_value={**conn, "provider": "openai", "model": "unverified-model"}
    ):
        assert rt.learning.allowances.price_options(conn["id"])["items"] == []
    assert rt.learning.usage()["calls"] == 0
