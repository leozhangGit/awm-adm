"""Acquisition deadlines across Teach, worker and gateway; simulated clocks only."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from awm_adm.config import AppConfig, load_config
from awm_adm.gateway import service as gateway_service
from awm_adm.providers.failures import uncertain
from awm_adm.runtime import component
from awm_adm.runtime.protocol import RuntimeFault, loads
from awm_adm.runtime.service import Runtime

from .test_application import app_runtime as app_runtime
from .test_direct_teach import has_ready, preparation, pump, task
from .test_instance import value_query
from .test_learning_service import advance, connection, episode
from .test_learning_service import rig as rig


def test_acquisition_defaults_leave_other_provider_calls_and_compute_unchanged():
    for config in (
        AppConfig(),
        load_config(Path("config/default.toml")),
        load_config(Path("deploy/config.toml")),
    ):
        assert config.learning.acquisition_timeout_ms == 180000
        assert config.learning.preparation_timeout_ms == 180000
        assert config.learning.episode.max_duration_ms == 720000
        assert config.learning.call.max_duration_ms == 60000
        assert config.learning.call.max_output_tokens == 8192
        assert config.learning.call.max_input_tokens == 128000


@pytest.mark.parametrize("value", [0, 600001, True])
def test_acquisition_timeout_has_finite_configuration_bounds(value):
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"learning": {"acquisition_timeout_ms": value}})


@pytest.mark.parametrize("cap,parent_remaining", [(180000, 900000), (90000, 900000), (180000, 45000)])
def test_automatic_teach_uses_acquisition_cap_and_remaining_parent_deadline(
    rig, monkeypatch, cap, parent_remaining
):
    rt, gw = rig
    data = rt.config.model_dump()
    data["learning"]["acquisition_timeout_ms"] = cap
    config = AppConfig.model_validate(data)
    monkeypatch.setattr(rt, "config", config)
    monkeypatch.setattr(rt.learning, "config", config)
    key, uid = preparation(rt, gw)
    t = task(rt, key, uid)
    now = rt.conversations.now()
    assert 899000 <= t["execution"]["deadline_ms"] - now <= 900000
    monkeypatch.setattr(rt.conversations, "now", lambda: now)
    t["execution"]["deadline_ms"] = now + parent_remaining
    rt.conversations.teaching.execution.persist(key, t)
    pump(rt, key, uid, lambda _: has_ready(rt))
    step = task(rt, key, uid)["execution"]["steps"][0]
    saved = rt.learning.episode(key, step["episode_id"])
    assert saved["body"]["call_limits"]["max_duration_ms"] == min(cap, parent_remaining)
    assert saved["body"]["limits"]["max_duration_ms"] == min(720000, parent_remaining)
    assert saved["body"]["limits"]["max_calls"] == 2
    assert saved["body"]["call_limits"]["max_output_tokens"] == 8192
    job = rt.learning.claim()
    assert job["timeout_ms"] == min(cap, parent_remaining)


@pytest.mark.parametrize("explicit_ms,queue_delay", [(None, 0), (30000, 0), (180000, 700)])
def test_acquisition_deadline_reaches_gateway_and_preserves_shorter_bounds(
    rig, monkeypatch, explicit_ms, queue_delay
):
    rt, gw = rig
    c = connection(rt, gw)
    key = rt.create("Bounded deadline")["id"]
    options = {} if explicit_ms is None else {"call_limits": {"max_duration_ms": explicit_ms}}
    saved = episode(rt, key, c, **options)
    assert saved["body"]["call_limits"]["max_duration_ms"] == (explicit_ms or 180000)
    assert saved["deadline"] - saved["created"] == 720
    advance(rt, key, saved["id"], "acquiring")
    clock = [saved["created"] + queue_delay]
    monkeypatch.setattr(rt.learning, "now", lambda: clock[0])
    monkeypatch.setattr(gateway_service.time, "time", lambda: clock[0])
    job = rt.learning.claim()
    seen = []

    def acquire(config, wire, credential, timeout, **kw):
        seen.append(timeout)
        return uncertain("timeout", "gateway_wait")

    monkeypatch.setattr(gateway_service, "acquire", acquire)
    gw.dispatch(job["grant_id"], job["lease"])
    assert seen == [min((explicit_ms or 180000) / 1000, 720 - queue_delay)]


def test_acquisition_above_configured_cap_is_rejected_before_dispatch(rig):
    rt, gw = rig
    c = connection(rt, gw)
    key = rt.create("Explicit cap")["id"]
    with pytest.raises(RuntimeFault) as error:
        episode(rt, key, c, call_limits={"max_duration_ms": 180001})
    assert error.value.code == "invalid_limits"
    assert rt.learning.claim() is None


def test_response_after_old_one_minute_limit_can_pass_full_admission(rig, monkeypatch):
    rt, gw = rig
    c = connection(rt, gw)
    key = rt.create("Slow simulated response")["id"]
    saved = episode(rt, key, c, publication="checked_auto")
    advance(rt, key, saved["id"], "acquiring")
    clock = [rt.learning.now()]
    monkeypatch.setattr(rt.learning, "now", lambda: clock[0])
    monkeypatch.setattr(gateway_service.time, "time", lambda: clock[0])
    original = gateway_service.acquire
    durations = []

    def acquire(config, wire, credential, timeout, **kw):
        durations.append(timeout)
        result = original(config, wire, credential, timeout, **kw)
        clock[0] += 90  # No sleep: the accepted result arrives after the old cap.
        return result

    monkeypatch.setattr(gateway_service, "acquire", acquire)
    job = rt.learning.claim()
    assert job["timeout_ms"] == 180000
    assert gw.dispatch(job["grant_id"], job["lease"])["status"] == "succeeded"
    done = advance(rt, key, saved["id"], "accepted")
    assert durations == [180]
    assert done["usage"]["calls"] == 1
    assert rt.query(key, value_query())["result"]["value"] == 10


@pytest.mark.parametrize("timeout_ms", [60000, 180000])
def test_timeout_keeps_reservation_and_original_limit_after_restart(rig, monkeypatch, timeout_ms):
    rt, gw = rig
    c = connection(rt, gw)
    key = rt.create("Unknown acquisition")["id"]
    revision = rt.store.info(key)["revision_id"]
    saved = episode(rt, key, c, call_limits={"max_duration_ms": timeout_ms})
    advance(rt, key, saved["id"], "acquiring")
    clock = [rt.learning.now()]
    monkeypatch.setattr(rt.learning, "now", lambda: clock[0])
    monkeypatch.setattr(gateway_service.time, "time", lambda: clock[0])
    calls = []

    def acquire(config, wire, credential, timeout, **kw):
        calls.append(timeout)
        clock[0] += timeout + 0.024
        result = uncertain("timeout", "gateway_wait")
        result["diagnostics"].update(timeout_ms=timeout_ms, elapsed_ms=timeout_ms + 24)
        return result

    monkeypatch.setattr(gateway_service, "acquire", acquire)
    job = rt.learning.claim()
    gw.dispatch(job["grant_id"], job["lease"])
    done = advance(rt, key, saved["id"], "stopped")
    assert done["reason"] == "outcome_unknown" and done["receipts"] == []
    usage = done["usage"]
    assert usage["calls"] == 1 and usage["unresolved"] == 1
    assert usage["input_tokens"] > 0 and usage["output_tokens"] == 8192
    with rt.store.db() as db:
        outcome = loads(db.execute("SELECT outcome FROM grants WHERE id=?", (job["grant_id"],)).fetchone()[0])
    assert outcome["error"] == "provider_timeout"
    assert outcome["diagnostics"]["failure_stage"] == "gateway_wait"
    assert outcome["diagnostics"]["timeout_ms"] == timeout_ms
    assert rt.store.info(key)["revision_id"] == revision
    assert rt.learning.claim() is None
    data = rt.config.model_dump()
    data["learning"]["acquisition_timeout_ms"] = 240000
    config = AppConfig.model_validate(data)
    rt.close()
    restarted = Runtime(config, start_scheduler=False)
    try:
        for _ in range(3):
            restarted.learning.tick()
            assert restarted.learning.claim() is None
        retained = restarted.learning.episode(key, saved["id"])
        assert retained["status"] == "stopped" and retained["usage"] == usage
        assert retained["body"]["call_limits"]["max_duration_ms"] == timeout_ms
        assert restarted.store.info(key)["revision_id"] == revision
        assert calls == [timeout_ms / 1000]
    finally:
        restarted.close()


@pytest.mark.parametrize("timeout_ms", [30000, 180000])
def test_worker_rpc_grace_follows_grant_without_extending_it(monkeypatch, timeout_ms):
    def exchange(url, token, body, *, timeout):
        assert url == "http://provider-gateway:8090/internal/dispatch"
        assert body == {"grant_id": "grant", "lease": "lease"}
        assert timeout == timeout_ms / 1000 + 3
        return {"status": "succeeded"}

    monkeypatch.setattr(component, "exchange", exchange)
    job = {"grant_id": "grant", "lease": "lease", "timeout_ms": timeout_ms}
    assert component.dispatch_job(job, "private-token") == {"status": "succeeded"}
    assert job["timeout_ms"] == timeout_ms
