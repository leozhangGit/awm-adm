"""Request-size capacity, safe retained diagnostics and pre-dispatch stopping."""

import base64
import copy
from pathlib import Path

import pytest

from awm_adm.config import AppConfig, load_config
from awm_adm.learning.diagnostics import InputCapacityExceeded
from awm_adm.runtime.protocol import RuntimeFault, dumps, loads
from awm_adm.runtime.service import Runtime

from .interaction_support import definition, reply
from .test_application import app_runtime as app_runtime
from .test_application import client
from .test_direct_teach import has_ready, preparation, pump, task
from .test_learning_service import rig as rig

LARGE_TEXT = (
    "Teach doubling whole numbers zero through five, with outputs zero through ten. "
    + "Supplied context for this bounded rule. " * 600
)


def test_default_input_capacity_is_consistent_in_python_and_both_installations():
    for config in (
        AppConfig(),
        load_config(Path("config/default.toml")),
        load_config(Path("deploy/config.toml")),
    ):
        assert config.learning.call.max_input_tokens == 128000
        assert config.learning.episode.max_input_tokens == 384000
        assert config.learning.episode.max_calls == 3
        assert config.learning.call.max_output_tokens == 8192
        assert config.learning.call.max_duration_ms == 60000


def test_large_teach_reaches_acquisition_and_checked_publication_with_new_defaults(rig):
    rt, gw = rig
    key, uid = preparation(rt, gw, text=LARGE_TEXT)
    pump(rt, key, uid, lambda _: has_ready(rt))
    step = task(rt, key, uid)["execution"]["steps"][0]
    ep = rt.learning.episode(key, step["episode_id"])
    assert ep["body"]["call_limits"]["max_input_tokens"] == 128000
    assert ep["body"]["limits"]["max_input_tokens"] == 256000
    assert ep["body"]["limits"]["max_calls"] == 2
    with rt.store.db() as db:
        grant = loads(db.execute("SELECT body FROM grants WHERE id=?", (ep["grant_id"],)).fetchone()[0])
    assert 32000 < grant["input_estimate"] < 128000
    assert grant["input_estimate"] == len(base64.b64decode(grant["wire"])) + 4096
    assert LARGE_TEXT in loads(base64.b64decode(grant["wire"]))["input"][0]["content"]
    reply(rt, definition())
    done = pump(rt, key, uid, lambda t: t["execution"]["phase"] == "narration")
    assert done["execution"]["steps"][0]["status"] == "accepted"
    assert "math.double" in rt.query(key, {"op": "capabilities"})["result"]["value"]["declarations"]


@pytest.mark.parametrize("cap", [16000, 32000, 128000])
def test_oversize_learning_keeps_diagnostics_through_episode_api_and_chat(rig, monkeypatch, cap):
    rt, gw = rig
    config = rt.config.model_dump()
    config["learning"]["call"]["max_input_tokens"] = cap
    config = AppConfig.model_validate(config)
    monkeypatch.setattr(rt, "config", config)
    monkeypatch.setattr(rt.learning, "config", config)
    key, uid = preparation(rt, gw, text=LARGE_TEXT)
    revision = rt.store.info(key)["revision_id"]
    original = rt.learning.supervisor.run

    def sized(task_input, **kw):
        value = original(task_input, **kw)
        if task_input["operation"] == "learning_prepare" and cap == 128000:
            # Author an over-cap complete wire, without needing a huge user message.
            value["wire"] = base64.b64encode(b"x" * (cap + 1 - 4096)).decode()
            value["input_estimate"] = cap + 1
        return value

    monkeypatch.setattr(rt.learning.supervisor, "run", sized)
    current = pump(rt, key, uid, lambda t: t["execution"]["phase"] == "narration")
    step = current["execution"]["steps"][0]
    episode_id = step["episode_id"]
    ep = rt.learning.episode(key, episode_id)
    diagnostic = ep["failure_diagnostics"]
    assert ep["status"] == "stopped" and ep["reason"] == "invalid_limits"
    assert ep["grant_id"] is None and ep["receipts"] == [] and ep["usage"]["calls"] == 0
    assert ep["body"]["call_limits"]["max_input_tokens"] == cap
    assert diagnostic["code"] == "input_capacity_exceeded"
    assert diagnostic["required_input_reservation"] > cap
    assert diagnostic["available_input_reservation"] == cap
    assert diagnostic["provider_call_dispatched"] is False
    assert diagnostic["measurement"] == "conservative_input_estimate"
    assert "Supplied context" not in dumps(diagnostic).decode()
    assert step["failure_diagnostics"] == diagnostic
    assert current["execution"]["summary"]["unresolved"][0]["diagnostic"] == diagnostic
    # A narration cannot erase the checked failure; deliver even without narration.
    current["execution"]["narration_failure"] = "offline_test"
    rt.conversations.teaching.execution.deliver(key, current)
    with client(rt) as http:
        value = http.get(f"/api/v1/adms/{key}/interactions/{uid}").json()
        saved = http.get(f"/api/v1/adms/{key}/episodes/{episode_id}").json()
        assert saved["failure_diagnostics"] == diagnostic
        assert value["status"] == "failed"
        assert value["failure_code"] == "invalid_limits"
        assert value["failure_diagnostics"]["items"][0] == {
            "objective_id": step["id"],
            "episode_id": episode_id,
            "reason": "invalid_limits",
            "diagnostic": diagnostic,
        }
        assert value["failure_diagnostics"]["complete"] is True
        assert diagnostic["message"] in value["reply"]
        assert value["teaching"]["admissions"] == []
        for _ in range(3):
            rt.learning.tick()
            assert http.get(f"/api/v1/adms/{key}/interactions/{uid}").json() == value
    assert rt.store.info(key)["revision_id"] == revision
    assert rt.store.info(key)["mode"] == "backward"
    assert rt.learning.episode(key, episode_id)["usage"]["calls"] == 0
    # Reopening the durable service must retain the original bound and failure,
    # rather than expanding it to new defaults or dispatching an acquisition.
    rt.close()
    restarted = Runtime(config, start_scheduler=False)
    try:
        restored = restarted.interactions.get(key, uid)
        assert restored["failure_diagnostics"] == value["failure_diagnostics"]
        restored_episode = restarted.learning.episode(key, episode_id)
        assert restored_episode["failure_diagnostics"] == diagnostic
        assert restored_episode["body"]["call_limits"]["max_input_tokens"] == cap
        assert restored_episode["usage"]["calls"] == 0
    finally:
        restarted.close()


def test_later_capacity_stop_preserves_accepted_child_and_partial_completion(rig, monkeypatch):
    rt, gw = rig

    def two_children(plan):
        child = copy.deepcopy(plan["children"][0])
        child["objective"] = "Establish a second independent bounded function"
        child["interfaces"] = {"math.second": child["interfaces"].pop("math.double")}
        plan["children"].append(child)

    key, uid = preparation(rt, gw, mutate=two_children)
    original = rt.learning.supervisor.run

    def oversized_second(task_input, **kw):
        value = original(task_input, **kw)
        if (
            task_input["operation"] == "learning_prepare"
            and "math.second" in task_input["body"]["task"]["acquisition_contract"]["interfaces"]
        ):
            value["input_estimate"] = 128001
        return value

    monkeypatch.setattr(rt.learning.supervisor, "run", oversized_second)
    pump(rt, key, uid, lambda _: has_ready(rt))
    reply(rt, definition())
    current = pump(rt, key, uid, lambda t: t["execution"]["phase"] == "narration")
    summary = current["execution"]["summary"]
    assert summary["status"] == "partially_succeeded"
    assert len(summary["accepted_ids"]) == 1 and len(summary["unresolved_ids"]) == 1
    assert summary["unresolved"][0]["diagnostic"]["required_input_reservation"] == 128001
    assert current["execution"]["steps"][0]["status"] == "accepted"
    assert "math.double" in rt.query(key, {"op": "capabilities"})["result"]["value"]["declarations"]


@pytest.mark.parametrize("required", [127999, 128000, 128001])
def test_exact_input_cap_boundary_before_grant_creation(rig, required):
    rt, gw = rig
    key, uid = preparation(rt, gw)
    pump(rt, key, uid, lambda _: has_ready(rt))
    step = task(rt, key, uid)["execution"]["steps"][0]
    ep = rt.learning.episode(key, step["episode_id"])
    with rt.store.db() as db:
        body = loads(db.execute("SELECT body FROM grants WHERE id=?", (ep["grant_id"],)).fetchone()[0])
        count = db.execute("SELECT count(*) FROM grants").fetchone()[0]
    body.pop("operation_id", None)
    body["input_estimate"] = required
    body["limits"]["max_input_tokens"] = 128000
    if required > 128000:
        with pytest.raises(InputCapacityExceeded) as caught:
            rt.learning.reserve(body, adm=key)
        assert caught.value.diagnostic["required_input_reservation"] == required
    else:
        assert rt.learning.reserve(body, adm=key)
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == count + (required <= 128000)


def test_capacity_http_error_exposes_only_trusted_numeric_diagnostic(app_runtime, monkeypatch):
    rt = app_runtime

    def fail():
        raise InputCapacityExceeded(128001, 128000)

    monkeypatch.setattr(rt.learning, "settings", fail)
    with client(rt) as http:
        response = http.get("/api/v1/learning")
        assert response.status_code == 422
        assert response.json()["details"]["required_input_reservation"] == 128001

        def unsafe():
            raise RuntimeFault("invalid_limits", "private-prompt-or-secret")

        monkeypatch.setattr(rt.learning, "settings", unsafe)
        response = http.get("/api/v1/learning")
        assert response.status_code == 422
        assert "private-prompt-or-secret" not in response.text
