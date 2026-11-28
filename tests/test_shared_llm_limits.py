import tomllib

import pytest

from awm_adm.config import AppConfig
from awm_adm.config_conversion import convert, toml
from awm_adm.contracts import CallLimits
from awm_adm.learning.diagnostics import LimitExceeded
from awm_adm.llm_limits import CallPolicy, aggregate, replay_body, resolve_call
from awm_adm.runtime.protocol import loads

from .test_application import app_runtime as app_runtime
from .test_direct_ask import recorded, work
from .test_direct_teach import has_ready, preparation, pump, task
from .test_learning_service import advance, connection, episode
from .test_learning_service import rig as rig


@pytest.mark.parametrize(
    "calls,inputs,outputs,minutes",
    [
        (1, 256000, 32768, 8),
        (2, 512000, 65536, 15),
        (3, 768000, 98304, 22),
        (6, 1536000, 196608, 43),
        (10, 2560000, 327680, 71),
        (20, 5120000, 655360, 141),
        (26, 6656000, 851968, 183),
    ],
)
def test_aggregate_arithmetic(calls, inputs, outputs, minutes):
    assert aggregate(resolve_call(CallPolicy()), calls) == {
        "max_calls": calls,
        "max_input_tokens": inputs,
        "max_output_tokens": outputs,
        "max_duration_ms": minutes * 60000,
    }


def test_shared_defaults_partial_and_oversized_override():
    policy = CallPolicy(max_output_tokens=12345)
    assert resolve_call(policy, {"max_duration_ms": 5000}) == {
        "max_calls": 1,
        "max_input_tokens": 256000,
        "max_output_tokens": 12345,
        "max_duration_ms": 5000,
    }
    with pytest.raises(LimitExceeded) as failure:
        resolve_call(policy, {"max_output_tokens": 12346})
    assert failure.value.diagnostic["provider_call_dispatched"] is False
    assert CallLimits().max_duration_ms == 60000  # Stored legacy profile remains deterministic.


def test_config_conversion_explicit_and_roundtrip():
    cfg, report = convert({"config_profile": "awm-adm-config/2"})
    assert AppConfig.model_validate(tomllib.loads(toml(cfg.model_dump()))) == cfg
    assert cfg.llm.call.max_duration_ms == 360000
    assert cfg.episode_limits()["max_output_tokens"] == 98304
    assert not report["custom_fields"]
    with pytest.raises(ValueError, match="Custom legacy"):
        convert({"config_profile": "awm-adm-config/2", "learning": {"call": {"max_output_tokens": 1000}}})
    cfg, report = convert(
        {"config_profile": "awm-adm-config/2", "learning": {"call": {"max_output_tokens": 1000}}},
        call={"max_output_tokens": 1000},
    )
    assert cfg.llm.call.max_output_tokens == 1000
    assert report["custom_fields"] == ["learning.call"]
    with pytest.raises(ValueError, match="unmixed"):
        convert({"config_profile": "awm-adm-config/2", "llm": {}})
    with pytest.raises(ValueError):
        AppConfig.model_validate({"learning": {"acquisition_timeout_ms": 5000}})


def test_resolution_never_changes_replayed_capture():
    old = {"call_limits": CallLimits().model_dump(), "limits": {"max_calls": 2, "max_output_tokens": 16384}}
    assert replay_body({"call_limits": {}, "limits": {}}, old, ("call_limits", "limits")) == old
    assert (
        replay_body({"call_limits": {"max_output_tokens": 2048}}, old)["call_limits"]["max_output_tokens"]
        == 2048
    )


def test_explicit_aggregate_constraints():
    cfg = AppConfig()
    assert cfg.episode_limits(overrides={"max_calls": 2})["max_duration_ms"] == 900000
    with pytest.raises(LimitExceeded):
        cfg.episode_limits(overrides={"max_output_tokens": 1000})
    with pytest.raises(LimitExceeded):
        cfg.episode_limits(overrides={"max_calls": 4})


def grant_body(rt, gid):
    with rt.store.db() as db:
        return loads(db.execute("SELECT body FROM grants WHERE id=?", (gid,)).fetchone()[0])


@pytest.mark.parametrize("stage", ["ask", "preparation", "acquisition", "connection_test"])
def test_common_dispatch_profile_and_separate_queue_wait(rig, monkeypatch, stage):
    rt, gw = rig
    conn = recorded(rt, gw, {})
    key = rt.create("Shared call policy")["id"]
    clock = [rt.learning.now()]
    monkeypatch.setattr(rt.learning, "now", lambda: clock[0])
    if stage in {"ask", "preparation"}:
        item = rt.interactions.submit(
            key, "ask" if stage == "ask" else "teach", {"text": "Use the accepted model"}
        )
        assert rt.conversations.tick()
        gid = work(rt, key, item["id"])["grant_id"]
    elif stage == "acquisition":
        saved = episode(rt, key, conn)
        gid = advance(rt, key, saved["id"], "acquiring")["grant_id"]
    else:
        gid = rt.learning.test_connection(
            conn["id"], {"idempotency_key": "common-test", "expected_version": conn["version"]}
        )["id"]
    before = grant_body(rt, gid)
    assert before["limits"] == {
        "max_calls": 1,
        "max_input_tokens": 256000,
        "max_output_tokens": 32768,
        "max_duration_ms": 360000,
    }
    assert before["queue_deadline"] - clock[0] == 60
    clock[0] += 45
    claimed = rt.learning.claim()
    assert claimed["grant_id"] == gid
    after = grant_body(rt, gid)
    assert after["expires"] - clock[0] == 360


@pytest.mark.parametrize("stage", ["ask", "preparation", "acquisition", "connection_test"])
def test_every_stage_expires_undispatched_queue_without_worker(rig, monkeypatch, stage):
    rt, gw = rig
    conn = recorded(rt, gw, {})
    key = rt.create("Queue expiry")["id"]
    clock = [rt.learning.now()]
    monkeypatch.setattr(rt.learning, "now", lambda: clock[0])
    if stage in {"ask", "preparation"}:
        item = rt.interactions.submit(key, "ask" if stage == "ask" else "teach", {"text": "Use the model"})
        rt.conversations.tick()
        gid = work(rt, key, item["id"])["grant_id"]
    elif stage == "acquisition":
        saved = episode(rt, key, conn)
        gid = advance(rt, key, saved["id"], "acquiring")["grant_id"]
    else:
        gid = rt.learning.test_connection(
            conn["id"], {"idempotency_key": "queue-test", "expected_version": conn["version"]}
        )["id"]
    clock[0] += 61
    rt.learning.tick()
    view = rt.learning.grant_view(gid)
    assert view["status"] == "not_dispatched"
    assert view["outcome"]["error"] == "queue_timeout"
    assert view["calls"] == view["input_tokens"] == view["output_tokens"] == 0
    assert rt.learning.claim() is None


def test_episode_omission_and_replay_use_captured_policy(rig, monkeypatch):
    rt, gw = rig
    conn = connection(rt, gw)
    key = rt.create("Captured omission")["id"]
    saved = episode(rt, key, conn, call_limits={"max_output_tokens": 1000})
    source = dict(saved["body"])
    source["call_limits"] = {"max_output_tokens": 1000}
    source.pop("limits")
    config = rt.config.model_dump()
    config["llm"]["call"] = {
        "max_input_tokens": 300000,
        "max_output_tokens": 65536,
        "max_duration_ms": 500000,
    }
    monkeypatch.setattr(rt.learning, "config", AppConfig.model_validate(config))
    state = rt.settings.get()
    rt.settings.update(
        {
            "expected_revision": state["revision"],
            "values": state["values"] | {"llm_call": config["llm"]["call"]},
        }
    )
    replay = rt.learning.create(key, source)
    assert replay["id"] == saved["id"] and replay["body"] == saved["body"]
    assert saved["body"]["limits"]["max_output_tokens"] == 3000
    assert saved["body"]["call_limits"]["max_input_tokens"] == 256000


def test_parent_too_short_is_refused_without_squeezing_call(rig):
    rt, gw = rig
    key, uid = preparation(rt, gw)
    saved = task(rt, key, uid)
    saved["execution"]["deadline_ms"] = rt.conversations.now() + 45000
    rt.conversations.teaching.execution.persist(key, saved)
    terminal = pump(rt, key, uid, lambda t: t["execution"].get("summary") is not None)
    assert terminal["execution"]["steps"][0]["status"] != "accepted"
    assert rt.learning.usage()["calls"] == 1  # Preparation only.
    assert rt.learning.claim() is None


def test_root_call_envelope_cannot_be_bypassed_with_new_child_identity(rig):
    rt, gw = rig
    key, uid = preparation(rt, gw)
    pump(rt, key, uid, lambda _: has_ready(rt))
    saved = task(rt, key, uid)
    child = rt.learning.episode(key, saved["execution"]["steps"][0]["episode_id"])
    body = grant_body(rt, child["grant_id"])
    body.pop("operation_id", None)
    # Deliberately reduce the root to the two already reserved calls.
    saved["llm_limits"]["aggregate"]["max_calls"] = 2
    with rt.store.db(key) as db:
        rt.conversations.teaching.save(db, saved)
    with pytest.raises(LimitExceeded) as failure:
        rt.learning.reserve(body, adm=key, episode=child["id"])
    assert failure.value.diagnostic["scope"] == "aggregate"
    assert failure.value.diagnostic["limit"] == "max_calls"
    assert rt.learning.usage()["calls"] == 2


def test_ask_queue_diagnostic_reaches_interaction_without_losing_cause(rig, monkeypatch):
    rt, gw = rig
    recorded(rt, gw, {})
    key = rt.create("Ask queue diagnostic")["id"]
    clock = [rt.learning.now()]
    monkeypatch.setattr(rt.learning, "now", lambda: clock[0])
    item = rt.interactions.submit(key, "ask", {"text": "Read the model"})
    rt.conversations.ask.tick()
    clock[0] += 61
    rt.learning.tick()
    rt.conversations.ask.tick()
    result = rt.interactions.get(key, item["id"])
    diagnostic = result["failure_diagnostics"]
    assert diagnostic["code"] == "queue_timeout"
    assert diagnostic["dispatch_status"] == "not_dispatched"
    assert diagnostic["effective_call_limits"]["max_duration_ms"] == 360000
    assert diagnostic["usage_unresolved"] is False
    assert rt.learning.usage()["calls"] == 0


def test_feed_new_item_keeps_its_captured_profile_after_config_change(rig, monkeypatch):
    from .test_extraction_timeout import external
    from .test_feeds import extraction_connection, feed
    from .test_sources import ingest, install

    rt, gw = rig
    conn = extraction_connection(rt, gw)
    key = rt.create("Captured standing feed")["id"]
    install(rt, key)
    saved = feed(rt, key, **external(conn), allow_external=True)
    config = rt.config.model_dump()
    config["llm"]["call"]["max_output_tokens"] = 1000
    changed = AppConfig.model_validate(config)
    monkeypatch.setattr(rt, "config", changed)
    state = rt.settings.get()
    rt.settings.update(
        {
            "expected_revision": state["revision"],
            "values": state["values"] | {"llm_call": config["llm"]["call"]},
        }
    )
    monkeypatch.setattr(rt.learning, "config", changed)
    ingest(rt, key)
    for _ in range(5):
        rt.sources.tick()
    claimed = rt.learning.claim()
    assert claimed is not None
    assert grant_body(rt, claimed["grant_id"])["limits"]["max_output_tokens"] == 32768
    assert rt.sources.feeds.get(key, saved["id"])["body"]["budget"]["max_output_tokens"] == 655360


def test_source_capacity_diagnostic_survives_without_a_grant(rig, monkeypatch):
    from awm_adm.sources.diagnostics import outcome

    from .test_extraction_timeout import external
    from .test_feeds import extraction_connection
    from .test_sources import ingest, install

    rt, gw = rig
    conn = extraction_connection(rt, gw)
    key = rt.create("Pre-dispatch source capacity")["id"]
    install(rt, key)
    source = ingest(rt, key)
    body = {
        "idempotency_key": "bounded-source",
        "expected_revision": rt.store.info(key)["revision_id"],
        "expected_generation": 1,
        "call_limits": {"max_input_tokens": 1},
        **{k: source[k] for k in ("source_id", "item_id", "version_id")},
        **external(conn),
    }
    item = rt.sources.create_job(key, body)
    rt.sources.tick()
    saved = rt.sources.get(key, "source_jobs", item["id"])
    diagnostic = outcome(saved)
    assert saved["status"] == "failed" and saved["grant_id"] is None
    assert diagnostic["limit_diagnostics"]["code"] == "input_capacity_exceeded"
    assert diagnostic["limit_diagnostics"]["available_input_reservation"] == 1
    assert rt.learning.usage()["calls"] == 0
