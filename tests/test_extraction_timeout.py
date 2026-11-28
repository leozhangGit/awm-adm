"""Extraction deadlines across Teach, feeds and APIs; recorded providers and clocks only."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from awm_adm.config import AppConfig, load_config
from awm_adm.gateway import service as gateway_service
from awm_adm.providers.failures import uncertain
from awm_adm.runtime.protocol import loads
from awm_adm.runtime.service import Runtime

from .test_application import app_runtime as app_runtime
from .test_application import client
from .test_direct_teach import has_ready, pump, task
from .test_feeds import extraction_connection, feed, lookup
from .test_feeds import pump as feed_pump
from .test_intake import material_task
from .test_learning_service import rig as rig
from .test_sources import ingest, install, job


def grant(rt, identity):
    with rt.store.db() as db:
        row = db.execute("SELECT body FROM grants WHERE id=?", (identity,)).fetchone()
    return loads(row[0])


def external(c):
    return {"extractor": "external", "connection_id": c["id"], "connection_version": c["version"]}


def test_extraction_defaults_match_other_provider_calls_and_leave_compute_unchanged():
    for config in (
        AppConfig(),
        load_config(Path("config/default.toml")),
        load_config(Path("deploy/config.toml")),
    ):
        assert config.llm.call.max_duration_ms == 360000
        assert config.llm.call.max_input_tokens == 256000
        assert config.llm.call.max_output_tokens == 32768
        assert config.episode_limits()["max_duration_ms"] == 1320000
        assert config.request.max_duration_ms == 10000


@pytest.mark.parametrize("value", [0, 600001, True])
def test_extraction_configuration_is_finitely_bounded(value):
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"llm": {"call": {"max_duration_ms": value}}})


@pytest.mark.parametrize("queue", [False, True])
@pytest.mark.parametrize("cap,remaining", [(360000, 900000), (90000, 900000)])
def test_teach_and_managed_queue_capture_cap_and_clip_parent(rig, monkeypatch, queue, cap, remaining):
    rt, gw = rig
    data = rt.config.model_dump()
    data["llm"]["call"]["max_duration_ms"] = cap
    monkeypatch.setattr(rt, "config", AppConfig.model_validate(data))
    state = rt.settings.get()
    rt.settings.update(
        {
            "expected_revision": state["revision"],
            "values": state["values"] | {"llm_call": data["llm"]["call"]},
        }
    )
    key, _, uid, _ = material_task(rt, gw, queue=queue)
    t = task(rt, key, uid)
    t["execution"]["deadline_ms"] = rt.conversations.now() + remaining
    rt.conversations.teaching.execution.persist(key, t)
    t = pump(rt, key, uid, lambda _: has_ready(rt))
    step = t["execution"]["steps"][0]
    saved = rt.sources.feeds.get(key, step["feed_id"])
    assert saved["body"]["call_limits"]["max_duration_ms"] == cap
    assert saved["body"]["call_limits"]["max_output_tokens"] == 32768
    claimed = rt.learning.claim()
    body = grant(rt, claimed["grant_id"])
    assert body["limits"]["max_duration_ms"] == cap
    assert body["deadline"] <= t["execution"]["deadline_ms"] / 1000
    assert body["queue_deadline"] <= t["execution"]["deadline_ms"] / 1000
    assert 0 < body["expires"] - rt.learning.now() <= min(cap, remaining) / 1000


@pytest.mark.parametrize("path", ["sources/jobs", "feeds"])
@pytest.mark.parametrize("explicit_ms", [None, 30000, 360001])
def test_direct_api_defaults_shorter_limits_and_configured_cap(rig, path, explicit_ms):
    rt, gw = rig
    c = extraction_connection(rt, gw)
    key = rt.create("Extraction API")["id"]
    install(rt, key)
    source = ingest(rt, key)
    body = {"idempotency_key": "one", "expected_revision": rt.store.info(key)["revision_id"], **external(c)}
    if path == "sources/jobs":
        body.update(expected_generation=1, **{k: source[k] for k in ("source_id", "item_id", "version_id")})
    else:
        body.update(
            name="Bounded feed", expected_source_generation=1, source_ids=["records"], allow_external=True
        )
    if explicit_ms is not None:
        body["call_limits"] = {"max_duration_ms": explicit_ms}
    with client(rt) as api:
        result = api.post(f"/api/v1/adms/{key}/{path}", json=body)
    if explicit_ms == 360001:
        assert result.status_code == 422, result.text
        assert result.json()["code"] == "invalid_limits"
        assert rt.learning.claim() is None
    else:
        assert result.status_code in (200, 201, 202), result.text
        assert result.json()["body"]["call_limits"]["max_duration_ms"] == (explicit_ms or 360000)


@pytest.mark.parametrize("delay", [0, 30, 61])
def test_source_queue_deadline_is_separate_from_execution(rig, monkeypatch, delay):
    rt, gw = rig
    c = extraction_connection(rt, gw)
    key = rt.create("Separate queue")["id"]
    install(rt, key)
    clock = [rt.learning.now()]
    monkeypatch.setattr(rt.learning, "now", lambda: clock[0])
    monkeypatch.setattr(gateway_service.time, "time", lambda: clock[0])
    saved = job(rt, key, ingest(rt, key), **external(c))
    assert saved["deadline"] - saved["created"] == 480
    rt.sources.tick()
    clock[0] += delay
    claimed = rt.learning.claim()
    if delay > 60:
        assert claimed is None
        assert rt.learning.usage()["calls"] == 0
        return
    durations = []

    def acquire(config, wire, credential, timeout, **kw):
        durations.append(timeout)
        return uncertain("timeout", "gateway_wait")

    monkeypatch.setattr(gateway_service, "acquire", acquire)
    gw.dispatch(claimed["grant_id"], claimed["lease"])
    assert durations == [360]


def test_feed_response_after_one_minute_passes_unchanged_source_admission(rig, monkeypatch):
    rt, gw = rig
    c = extraction_connection(rt, gw)
    key = rt.create("Slow extraction")["id"]
    install(rt, key)
    saved = feed(rt, key, **external(c), allow_external=True)
    ingest(rt, key)
    for _ in range(5):
        rt.sources.tick()
    claimed = rt.learning.claim()
    assert claimed["timeout_ms"] == 360000
    clock = [rt.learning.now()]
    monkeypatch.setattr(rt.learning, "now", lambda: clock[0])
    monkeypatch.setattr(gateway_service.time, "time", lambda: clock[0])
    original = gateway_service.acquire

    def acquire(config, wire, credential, timeout, **kw):
        assert 359 < timeout <= 360
        result = original(config, wire, credential, timeout, **kw)
        clock[0] += 90  # No sleeping or external provider.
        return result

    monkeypatch.setattr(gateway_service, "acquire", acquire)
    assert gw.dispatch(claimed["grant_id"], claimed["lease"])["status"] == "succeeded"
    feed_pump(rt, key)
    assert lookup(rt, key)["result"]["value"] == 10
    assert rt.sources.feeds.get(key, saved["id"])["reserved"]["calls"] == 1


@pytest.mark.parametrize("timeout_ms", [60000, 180000])
def test_unknown_extraction_retains_limits_accounting_and_no_retry_after_restart(
    rig, monkeypatch, timeout_ms
):
    rt, gw = rig
    c = extraction_connection(rt, gw)
    key = rt.create("Uncertain extraction")["id"]
    install(rt, key)
    revision = rt.store.info(key)["revision_id"]
    saved = feed(
        rt,
        key,
        **external(c),
        allow_external=True,
        call_limits={"max_duration_ms": timeout_ms, "max_output_tokens": 8192},
    )
    ingest(rt, key)
    for _ in range(5):
        rt.sources.tick()
    claimed = rt.learning.claim()
    clock = [rt.learning.now()]
    monkeypatch.setattr(rt.learning, "now", lambda: clock[0])
    monkeypatch.setattr(gateway_service.time, "time", lambda: clock[0])
    calls = []

    def acquire(config, wire, credential, timeout, **kw):
        calls.append(timeout)
        clock[0] += timeout + 0.024
        outcome = uncertain("timeout", "gateway_wait")
        outcome["diagnostics"].update(timeout_ms=timeout_ms, elapsed_ms=timeout_ms + 24)
        return outcome

    monkeypatch.setattr(gateway_service, "acquire", acquire)
    gw.dispatch(claimed["grant_id"], claimed["lease"])
    page = feed_pump(rt, key, "dead_letter")
    usage = rt.learning.usage()
    assert usage["calls"] == usage["unresolved"] == 1
    assert usage["input_tokens"] > 0 and usage["output_tokens"] == 8192
    assert rt.store.info(key)["revision_id"] == revision
    assert not rt.sources.overview(key)["claims"]
    data = rt.config.model_dump()
    data["llm"]["call"]["max_duration_ms"] = 240000
    rt.close()
    restarted = Runtime(AppConfig.model_validate(data), start_scheduler=False)
    try:
        for _ in range(3):
            restarted.sources.tick()
            restarted.learning.tick()
            assert restarted.learning.claim() is None
        assert restarted.learning.usage() == usage
        retained = restarted.sources.feeds.get(key, saved["id"])
        assert retained["body"]["call_limits"]["max_duration_ms"] == timeout_ms
        body = grant(restarted, claimed["grant_id"])
        assert body["limits"]["max_duration_ms"] == timeout_ms
        source = restarted.sources.get(key, "source_jobs", body["source_job_id"])
        assert source["status"] == "failed" and source["error"] == "provider_timeout"
        assert source["body"]["call_limits"]["max_duration_ms"] == timeout_ms
        assert restarted.sources.feeds.overview(key)["items"] == page["items"]
        assert restarted.store.info(key)["revision_id"] == revision
        assert len(calls) == 1
    finally:
        restarted.close()
