"""Explicit Docker client access; no providers, credentials or user's installation."""

import tomllib

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from awm_adm.access_policy import TrustedClients
from awm_adm.api import create_app
from awm_adm.application.http import Boundary
from awm_adm.config import AppConfig, Server
from awm_adm.config_conversion import toml
from awm_adm.runtime.http import create_internal
from awm_adm.runtime.service import Runtime
from tests.test_application import OWNER, configuration

POLICY = {"hosts": ["adm-service:9527"], "source_networks": ["172.30.95.0/24"]}


@pytest.mark.parametrize(
    "change",
    [
        {"source_networks": []},
        {"hosts": []},
        {"hosts": ["*:9527"]},
        {"hosts": ["http://adm-service:9527"]},
        {"hosts": ["adm-service:9528"]},
        {"hosts": ["adm-service:09527"]},
        {"hosts": ["adm-service:9527/path"]},
        {"hosts": ["adm-service.:9527"]},
        {"hosts": ["ADM-SERVICE:9527"]},
        {"hosts": ["adm-service:9527", "adm-service:9527"]},
        {"hosts": ["localhost:9527"]},
        {"hosts": ["127.0.0.1:9527"]},
        {"hosts": ["8.8.8.8:9527"]},
        {"source_networks": ["0.0.0.0/0"]},
        {"source_networks": ["172.30.95.1/24"]},
        {"source_networks": ["172.30.95.5"]},
        {"source_networks": ["127.0.0.0/8"]},
        {"source_networks": ["169.254.0.0/16"]},
        {"source_networks": ["203.0.113.0/24"]},
        {"source_networks": ["::/0"]},
        {"source_networks": ["::1/128"]},
        {"source_networks": ["fe80::/10"]},
        {"source_networks": ["172.30.95.0/24", "172.30.95.0/24"]},
    ],
)
def test_incomplete_or_unsafe_configuration_fails_at_startup(change):
    with pytest.raises(ValidationError):
        Server.model_validate({"trusted_clients": POLICY | change})


def test_additive_defaults_and_custom_policy_roundtrip():
    assert Server().trusted_clients == TrustedClients()
    raw = AppConfig().model_dump()
    raw["server"]["trusted_clients"] = POLICY
    result = AppConfig.model_validate(raw)
    assert AppConfig.model_validate(tomllib.loads(toml(result.model_dump()))) == result
    for value in ("10.42.0.5/32", "192.168.42.0/24", "fd12:3456::/64"):
        assert TrustedClients.model_validate(POLICY | {"source_networks": [value]})


async def endpoint(request):
    return JSONResponse({"accepted": True})


downstream = Starlette(routes=[Route("/api/v1/adms", endpoint, methods=["GET", "POST", "OPTIONS"])])


def boundary(peer="172.30.95.5", host="adm-service:9527", enabled=True):
    return TestClient(
        Boundary(
            downstream,
            maximum=128,
            port=9527,
            ingress={"172.29.0.1"},
            trusted_clients=TrustedClients.model_validate(POLICY) if enabled else None,
        ),
        client=(peer, 12345),
        base_url="http://" + host,
    )


@pytest.mark.parametrize(
    "peer,host,enabled,status",
    [
        ("172.30.95.5", "adm-service:9527", True, 200),
        ("172.30.95.5", "adm-service:9527", False, 403),
        ("172.30.96.5", "adm-service:9527", True, 403),
        ("203.0.113.5", "adm-service:9527", True, 403),
        ("172.30.95.5", "other-service:9527", True, 403),
        ("172.30.95.5", "adm-service:9528", True, 403),
        ("172.30.95.5", "localhost:9527", True, 403),
        ("172.30.95.5", "127.0.0.1:9527", True, 403),
        ("127.0.0.1", "adm-service:9527", True, 403),
        ("172.29.0.1", "adm-service:9527", True, 403),
        ("172.29.0.1", "127.0.0.1:9527", True, 200),
        ("127.0.0.1", "localhost:9527", True, 200),
        ("::1", "[::1]:9527", True, 200),
    ],
)
def test_host_and_actual_peer_must_match_one_access_path(peer, host, enabled, status):
    with boundary(peer, host, enabled) as c:
        assert c.get("/api/v1/adms").status_code == status


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "http://adm-service:9527"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "same-origin"},
        {"Sec-Fetch-Site": "none"},
        {"Sec-Fetch-Mode": "navigate"},
        {"Sec-Fetch-Site": "cross-site"},
        [("Host", "adm-service:9527"), ("Host", "localhost:9527")],
        [("Origin", "http://adm-service:9527"), ("Origin", "http://adm-service:9527")],
    ],
)
def test_opt_in_cannot_be_used_as_a_browser_origin(headers):
    with boundary() as c:
        for method in ("GET", "POST", "OPTIONS"):
            assert c.request(method, "/api/v1/adms", headers=headers).status_code == 403


def test_forwarded_headers_never_supply_a_trusted_host_or_peer():
    with boundary(peer="172.30.96.5") as c:
        assert (
            c.get(
                "/api/v1/adms",
                headers={
                    "X-Forwarded-For": "172.30.95.5",
                    "Forwarded": "for=172.30.95.5;host=adm-service:9527",
                },
            ).status_code
            == 403
        )
    with boundary(host="unknown:9527") as c:
        assert c.get("/api/v1/adms", headers={"X-Forwarded-Host": "adm-service:9527"}).status_code == 403


def test_content_limits_and_local_browser_behavior_survive_opt_in():
    with boundary() as c:
        assert c.post("/api/v1/adms", json={"idempotency_key": "one"}).status_code == 200
        assert c.post("/api/v1/adms", content="a=b").status_code == 415
        assert (
            c.post("/api/v1/adms", content="{", headers={"Content-Type": "application/json"}).status_code
            == 400
        )
        assert c.post("/api/v1/adms", json={"large": "x" * 128}).status_code == 413
    with boundary(peer="127.0.0.1", host="localhost:9527") as c:
        assert (
            c.post(
                "/api/v1/adms",
                json={},
                headers={"Origin": "http://localhost:9527", "Sec-Fetch-Site": "same-origin"},
            ).status_code
            == 200
        )
        assert c.get("/api/v1/adms", headers={"Origin": "http://localhost:9528"}).status_code == 403


def test_ipv6_ula_uses_actual_socket_peer():
    app = Boundary(
        downstream,
        maximum=128,
        port=9527,
        trusted_clients=TrustedClients(hosts=["adm-service:9527"], source_networks=["fd12:3456::/64"]),
    )
    for peer, status in (("fd12:3456::5", 200), ("fd12:3457::5", 403), ("::1", 403)):
        with TestClient(app, client=(peer, 12345), base_url="http://adm-service:9527") as c:
            assert c.get("/api/v1/adms").status_code == status


def test_opt_in_retains_workspace_identity_and_private_channel_auth(tmp_path):
    raw = configuration(tmp_path / "store").model_dump()
    raw["server"]["trusted_clients"] = POLICY
    config = AppConfig.model_validate(raw)
    rt = Runtime(config, start_scheduler=False)
    try:
        with TestClient(
            create_app(config, runtime=rt), client=("172.30.95.5", 12345), base_url="http://adm-service:9527"
        ) as c:
            assert c.get("/api/v1/adms").json()["items"] == []
            response = c.post(
                "/api/v1/adms", json={"idempotency_key": "trusted-create", "name": "Offline model"}
            )
            assert response.status_code == 202
            operation = response.json()["operation_id"]
            rt.coordinator.run_operation()
            assert c.get(f"/api/v1/operations/{operation}").json()["status"] == "succeeded"
            model = c.get("/api/v1/adms").json()["items"][0]
            assert model["name"] == "Offline model"
            assert c.get("/api/v1/auth/login").status_code == 404
        tokens = {"owner": OWNER, "worker": "fixture-worker", "gateway": "fixture-gateway"}
        with TestClient(create_internal(rt, tokens), client=("172.30.95.5", 12345)) as c:
            assert c.get("/internal/m2/adms").status_code == 401
        assert rt.learning.usage()["calls"] == 0
    finally:
        rt.close()
