"""Output reservations and unchanged source admission; no external provider calls."""

import base64
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from awm_adm.config import AppConfig, load_config
from awm_adm.feeds.models import FeedBudget
from awm_adm.gateway import service as gateway_service
from awm_adm.providers.failures import uncertain
from awm_adm.providers.transport import interpret
from awm_adm.runtime.protocol import loads
from awm_adm.runtime.service import Runtime
from awm_adm.sources.models import ExtractionCallLimits

from .test_application import app_runtime as app_runtime
from .test_application import client
from .test_direct_teach import has_ready, pump
from .test_extraction_timeout import external, grant
from .test_feeds import extraction_connection, feed, lookup
from .test_feeds import pump as feed_pump
from .test_intake import material_task
from .test_learning_service import rig as rig
from .test_sources import ingest, install


def output_cap(rt, monkeypatch, value):
    data = rt.config.model_dump()
    data["llm"]["call"]["max_output_tokens"] = value
    config = AppConfig.model_validate(data)
    monkeypatch.setattr(rt, "config", config)
    state = rt.settings.get()
    rt.settings.update(
        {
            "expected_revision": state["revision"],
            "values": state["values"] | {"llm_call": data["llm"]["call"]},
        }
    )
    monkeypatch.setattr(rt.learning, "config", config)


def wire(body):
    return json.loads(base64.b64decode(body["wire"]))


def test_extraction_output_defaults_share_the_common_policy():
    for config in (
        AppConfig(),
        load_config(Path("config/default.toml")),
        load_config(Path("deploy/config.toml")),
    ):
        assert config.llm.call.max_output_tokens == 32768
        assert config.llm.call.max_duration_ms == 360000
        assert config.episode_limits()["max_output_tokens"] == 98304
    assert ExtractionCallLimits().max_output_tokens == 32768
    assert FeedBudget().max_output_tokens == FeedBudget().max_calls * 32768 == 655360


@pytest.mark.parametrize("value", [0, 100001, True])
def test_extraction_output_configuration_has_finite_strict_bounds(value):
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"llm": {"call": {"max_output_tokens": value}}})


@pytest.mark.parametrize("queue", [False, True])
@pytest.mark.parametrize("cap", [8192, 16384])
def test_teach_and_managed_intake_capture_matching_call_and_lifetime_reservations(
    rig, monkeypatch, queue, cap
):
    rt, gw = rig
    output_cap(rt, monkeypatch, cap)
    key, _, uid, _ = material_task(rt, gw, queue=queue)
    task = pump(rt, key, uid, lambda _: has_ready(rt))
    step = task["execution"]["steps"][0]
    saved = rt.sources.feeds.get(key, step["feed_id"])
    assert saved["body"]["call_limits"]["max_output_tokens"] == cap
    assert saved["body"]["budget"]["max_output_tokens"] == 6 * cap
    assert saved["body"]["budget"]["max_calls"] == 6
    assert saved["reserved"]["output_tokens"] == cap
    claimed = rt.learning.claim()
    body = grant(rt, claimed["grant_id"])
    assert body["limits"]["max_output_tokens"] == wire(body)["max_output_tokens"] == cap
    assert body["limits"]["max_duration_ms"] == 360000
    with rt.store.db() as db:
        row = db.execute(
            "SELECT output_tokens,calls,unresolved FROM grants WHERE id=?", (claimed["grant_id"],)
        ).fetchone()
    assert tuple(row) == (cap, 1, 1)


@pytest.mark.parametrize("path", ["sources/jobs", "feeds"])
@pytest.mark.parametrize(
    "explicit,cap", [(None, 16384), (8192, 16384), (4096, 4096), (None, 8192), (16385, 16384)]
)
def test_direct_apis_reserve_exact_output_and_reject_over_cap_before_dispatch(
    rig, monkeypatch, path, explicit, cap
):
    rt, gw = rig
    output_cap(rt, monkeypatch, cap)
    c = extraction_connection(rt, gw)
    key = rt.create("Source output capacity")["id"]
    install(rt, key)
    source = ingest(rt, key)
    body = {"idempotency_key": "one", "expected_revision": rt.store.info(key)["revision_id"], **external(c)}
    if path == "sources/jobs":
        body.update(expected_generation=1, **{k: source[k] for k in ("source_id", "item_id", "version_id")})
    else:
        body.update(
            name="Bounded feed",
            enabled=True,
            expected_source_generation=1,
            source_ids=["records"],
            allow_external=True,
        )
    if explicit is not None:
        body["call_limits"] = {"max_output_tokens": explicit}
    with client(rt) as api:
        response = api.post(f"/api/v1/adms/{key}/{path}", json=body)
    wanted = explicit or cap
    if wanted > cap:
        assert response.status_code == 422 and response.json()["code"] == "invalid_limits"
        assert rt.learning.usage()["calls"] == 0
        assert rt.learning.claim() is None
        return
    assert response.status_code in (200, 201, 202), response.text
    for _ in range(5):
        rt.sources.tick()
    claimed = rt.learning.claim()
    captured = grant(rt, claimed["grant_id"])
    assert captured["limits"]["max_output_tokens"] == wire(captured)["max_output_tokens"] == wanted
    assert rt.learning.usage()["output_tokens"] == wanted
    assert rt.learning.usage()["calls"] == 1
    if path == "feeds":
        saved = rt.sources.feeds.get(key, response.json()["id"])
        assert saved["reserved"]["output_tokens"] == wanted
        assert saved["body"]["budget"]["max_output_tokens"] == 20 * wanted


def test_success_with_reported_usage_above_old_cap_passes_full_admission(rig, monkeypatch):
    rt, gw = rig
    c = extraction_connection(rt, gw)
    key = rt.create("Recorded output accounting")["id"]
    install(rt, key)
    saved = feed(rt, key, **external(c), allow_external=True)
    ingest(rt, key)
    for _ in range(5):
        rt.sources.tick()
    claimed = rt.learning.claim()
    original = gateway_service.acquire

    def acquire(config, raw, credential, timeout, **kw):
        assert json.loads(raw)["max_output_tokens"] == 32768
        result = original(config, raw, credential, timeout, **kw)
        result["usage"]["output_tokens"] = 12000  # Authored usage, not measured generation.
        return result

    monkeypatch.setattr(gateway_service, "acquire", acquire)
    assert gw.dispatch(claimed["grant_id"], claimed["lease"])["status"] == "succeeded"
    feed_pump(rt, key)
    assert lookup(rt, key)["result"]["value"] == 10
    assert rt.learning.usage()["output_tokens"] == 12000
    assert rt.learning.usage()["unresolved"] == 0
    assert rt.sources.feeds.get(key, saved["id"])["reserved"]["output_tokens"] == 32768


@pytest.mark.parametrize("cap", [8192, 16384])
@pytest.mark.parametrize("outcome_kind", ["incomplete", "uncertain"])
def test_failed_output_is_never_admitted_and_keeps_captured_accounting_after_restart(
    rig, monkeypatch, cap, outcome_kind
):
    rt, gw = rig
    c = extraction_connection(rt, gw)
    key = rt.create("Retained extraction failure")["id"]
    install(rt, key)
    revision = rt.store.info(key)["revision_id"]
    saved = feed(
        rt,
        key,
        **external(c),
        allow_external=True,
        call_limits={"max_output_tokens": cap},
        budget={"max_output_tokens": cap},
    )
    ingest(rt, key)
    for _ in range(5):
        rt.sources.tick()
    claimed = rt.learning.claim()
    original = gateway_service.acquire
    calls = []

    def acquire(config, raw, credential, timeout, **kw):
        calls.append(json.loads(raw)["max_output_tokens"])
        if outcome_kind == "uncertain":
            return uncertain("timeout", "gateway_wait")
        candidate = original(config, raw, credential, timeout, **kw)
        # Even a syntactically complete candidate in an incomplete response is rejected.
        return interpret(
            "openai",
            json.dumps(
                {
                    "id": "response",
                    "model": "authored",
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "usage": {
                        "input_tokens": 500,
                        "output_tokens": cap,
                        "output_tokens_details": {"reasoning_tokens": 100},
                    },
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "status": "incomplete",
                            "content": [{"type": "output_text", "text": candidate["text"]}],
                        }
                    ],
                }
            ).encode(),
        )

    monkeypatch.setattr(gateway_service, "acquire", acquire)
    gw.dispatch(claimed["grant_id"], claimed["lease"])
    feed_pump(rt, key, "dead_letter")
    usage = rt.learning.usage()
    assert usage["calls"] == 1 and usage["output_tokens"] == cap
    assert usage["unresolved"] == (outcome_kind == "uncertain")
    assert not rt.sources.overview(key)["claims"]
    assert rt.store.info(key)["revision_id"] == revision
    with rt.store.db() as db:
        outcome = loads(
            db.execute("SELECT outcome FROM grants WHERE id=?", (claimed["grant_id"],)).fetchone()[0]
        )
    if outcome_kind == "incomplete":
        assert outcome["error"] == "output_incomplete"
        assert not outcome.get("text")
        assert outcome["diagnostics"]["incomplete_reason"] == "max_output_tokens"
        assert outcome["usage"]["output_tokens"] == cap
    data = rt.config.model_dump()
    data["llm"]["call"]["max_output_tokens"] = 32768
    rt.close()
    restarted = Runtime(AppConfig.model_validate(data), start_scheduler=False)
    try:
        for _ in range(3):
            restarted.sources.tick()
            restarted.learning.tick()
            assert restarted.learning.claim() is None
        assert restarted.learning.usage() == usage
        retained = restarted.sources.feeds.get(key, saved["id"])
        assert retained["body"]["call_limits"]["max_output_tokens"] == cap
        assert retained["body"]["budget"]["max_output_tokens"] == cap
        captured = grant(restarted, claimed["grant_id"])
        assert captured["limits"]["max_output_tokens"] == wire(captured)["max_output_tokens"] == cap
        source = restarted.sources.get(key, "source_jobs", captured["source_job_id"])
        assert source["body"]["call_limits"]["max_output_tokens"] == cap
        assert restarted.store.info(key)["revision_id"] == revision
        assert calls == [cap]
    finally:
        restarted.close()


def test_smaller_feed_lifetime_budget_is_not_silently_enlarged(rig):
    rt, gw = rig
    c = extraction_connection(rt, gw)
    key = rt.create("Finite output reservation")["id"]
    install(rt, key)
    saved = feed(rt, key, **external(c), allow_external=True, budget={"max_output_tokens": 65535})
    ingest(rt, key, item="first")
    ingest(rt, key, item="second")
    for _ in range(8):
        rt.sources.tick()
    current = rt.sources.feeds.get(key, saved["id"])
    assert current["body"]["budget"]["max_output_tokens"] == 65535
    assert current["reserved"]["output_tokens"] == 32768
    assert current["reserved"]["items"] == 1
    assert rt.learning.usage()["calls"] == 1
