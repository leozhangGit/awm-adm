import asyncio
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from awm_adm.api import create_app
from awm_adm.cli import main
from awm_adm.config import AppConfig, load_config

ROOT = Path(__file__).resolve().parents[1]


def test_owned_config_matches_defaults():
    assert load_config(ROOT / "config/default.toml") == AppConfig()
    assert not AppConfig().learning.remote_calls_enabled
    assert not AppConfig().sources.feed_enabled_by_default


@pytest.mark.parametrize(
    "changes",
    [
        {"server": {"bind_host": "0.0.0.0"}},
        {"server": {"data_dir": "../v1"}},
        {"server": {"api_key": "never-load-this"}},
        {"request": {"max_work": True}},
        {"runtime": {"provider_concurrency": 1, "provider_concurrency_per_adm": 2}},
        {"runtime": {"installation_storage_bytes": 1_048_576}},
        {"learning": {"call": {"max_output_tokens": 50_000}}},
        {"learning": {"episode": {"max_calls": 1}}},
        {"learning": {"quotas": {"calls_per_adm": 200}}},
        {"sources": {"item_bytes": 2048, "batch_bytes": 1024}},
        {"sources": {"feed_enabled_by_default": True}},
        {"sources": {"feed_enabled_by_default": 0}},
        {"retention": {"automatic_cleanup": True}},
        {"proof": {"fallback": "finite"}},
    ],
)
def test_invalid_or_unbounded_configuration(changes):
    with pytest.raises(ValidationError):
        AppConfig.model_validate(changes)


def test_cli_rejects_secret_fields_without_echoing_value(tmp_path, capsys):
    path = tmp_path / "invalid.toml"
    path.write_text('secret = "do-not-echo-this-value"\n')
    assert main(["check-config", str(path)]) == 2
    assert "do-not-echo-this-value" not in capsys.readouterr().out


def test_foundation_is_live_but_never_claims_to_serve():
    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
        ) as client:
            assert (await client.get("/health/live")).status_code == 200
            assert (await client.get("/health/ready")).status_code == 503
            body = (await client.get("/api/v1/system")).json()
            assert body["stage"] == "release"
            assert "finite_engine_library" in body["implemented"]
            assert body["operational"] is False
            assert not any(body["available"].values())
            assert (await client.post("/api/v1/adms/a/requests", json={})).status_code == 404
            assert (await client.post("/connections/test", json={})).status_code == 404

    asyncio.run(check())
