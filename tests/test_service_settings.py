"""Durable installation defaults, immutable captured work and capacity preservation."""

import sqlite3

import pytest

from awm_adm.runtime.service import Runtime
from awm_adm.runtime.storage import migrate
from awm_adm.temporal_evidence.capacity import CatalogCapacity
from awm_adm.temporal_evidence.legacy import extend

from .temporal_support import catalog, fact
from .test_application import app_runtime as app_runtime
from .test_application import client, configuration
from .test_catalog_capacity import many
from .test_direct_ask import recorded, work
from .test_learning_service import rig as rig
from .test_single_connection import enable_input
from .test_sources import ingest, install, project
from .test_temporal_evidence import ask


def change(rt, **overrides):
    state = rt.settings.get()
    values = state["values"] | overrides
    return rt.settings.update({"expected_revision": state["revision"], "values": values})


def test_settings_persist_without_changing_models_or_connection(tmp_path):
    cfg = configuration(tmp_path / "settings")
    rt = Runtime(cfg, start_scheduler=False)
    try:
        key = rt.create("Preserved knowledge")["id"]
        snapshot = rt.store.snapshot(key)
        connection = rt.learning.connection_manager.view()
        saved = change(
            rt,
            llm_call={"max_input_tokens": 300000, "max_output_tokens": 40000, "max_duration_ms": 450000},
            catalog_predicate_limit=300,
        )
        assert saved["revision"] == 1
        assert saved["defaults"]["llm_call"]["max_output_tokens"] == 32768
        assert rt.learning.settings()["call_caps"]["max_output_tokens"] == 40000
        assert rt.learning.settings()["episode_caps"]["max_output_tokens"] == 120000
        assert rt.store.snapshot(key) == snapshot
        assert rt.learning.connection_manager.view() == connection
        assert rt.learning.usage()["calls"] == 0
        rt.close()
        rt = Runtime(cfg, start_scheduler=False)
        assert rt.settings.get() == saved
        assert rt.store.snapshot(key) == snapshot
        assert rt.learning.usage()["calls"] == 0
    finally:
        rt.close()


def test_api_validates_atomically_and_detects_concurrent_edits(app_runtime):
    rt = app_runtime
    with client(rt) as http:
        initial = http.get("/api/v1/settings").json()
        body = {
            "expected_revision": initial["revision"],
            "values": initial["values"] | {"catalog_predicate_limit": 100},
        }
        result = http.put("/api/v1/settings", json=body)
        assert result.status_code == 200
        saved = result.json()
        assert http.put("/api/v1/settings", json=body).json() == saved
        conflicting = {**body, "values": initial["values"] | {"catalog_predicate_limit": 200}}
        assert http.put("/api/v1/settings", json=conflicting).status_code == 409
        for field, bad in [
            ("max_input_tokens", 1050001),
            ("max_output_tokens", 100001),
            ("max_duration_ms", 600001),
            ("max_output_tokens", True),
            ("max_output_tokens", 1.5),
        ]:
            invalid = {
                "expected_revision": saved["revision"],
                "values": saved["values"] | {"llm_call": saved["values"]["llm_call"] | {field: bad}},
            }
            assert http.put("/api/v1/settings", json=invalid).status_code == 422
        invalid = {
            "expected_revision": saved["revision"],
            "values": saved["values"] | {"catalog_predicate_limit": 65537},
        }
        assert http.put("/api/v1/settings", json=invalid).status_code == 422
        assert http.get("/api/v1/settings").json() == saved
    assert rt.learning.usage()["calls"] == 0


def test_saving_defaults_persists_override_over_later_startup_configuration(tmp_path):
    from awm_adm.config import AppConfig

    cfg = configuration(tmp_path / "settings")
    rt = Runtime(cfg, start_scheduler=False)
    saved = change(rt)
    assert saved["revision"] == 1
    rt.close()
    config = cfg.model_dump()
    config["llm"]["call"]["max_output_tokens"] = 1000
    rt = Runtime(AppConfig.model_validate(config), start_scheduler=False)
    try:
        assert rt.settings.get()["defaults"]["llm_call"]["max_output_tokens"] == 1000
        assert rt.settings.get()["values"] == saved["values"]
        assert rt.settings.call.max_output_tokens == 32768
    finally:
        rt.close()


@pytest.mark.parametrize("channel", ["ask", "teach"])
def test_queued_work_retains_policy_and_new_work_captures_updates(rig, channel):
    rt, gw = rig
    recorded(rt, gw, {})
    key = rt.create("Settings capture")["id"]
    original = rt.interactions.submit(key, channel, {"text": "Use the accepted model"})
    before = work(rt, key, original["id"])
    change(
        rt,
        llm_call={"max_input_tokens": 300000, "max_output_tokens": 40000, "max_duration_ms": 450000},
        catalog_predicate_limit=123,
    )
    assert work(rt, key, original["id"]) == before
    new = rt.interactions.submit(key, channel, {"text": "Independent new work"})
    after = work(rt, key, new["id"])
    assert after["llm_limits"]["call"]["max_output_tokens"] == 40000
    assert after["catalog_predicate_limit"] == 123
    assert before["llm_limits"]["call"]["max_output_tokens"] == 32768
    if channel == "teach":
        assert rt.conversations.teaching.get(key, original["id"])["catalog_predicate_limit"] == 65536
        assert rt.conversations.teaching.get(key, new["id"])["catalog_predicate_limit"] == 123
    assert rt.learning.usage()["calls"] == 0


def test_pending_connection_test_retains_captured_limits(rig):
    rt, gw = rig
    gw.synchronize()
    manager = rt.learning.connection_manager
    op = manager.enable(enable_input(gw))
    change(rt, llm_call={"max_input_tokens": 250000, "max_output_tokens": 1000, "max_duration_ms": 2000})
    gw.synchronize()
    gw.synchronize()
    assert manager.tick()
    from .test_shared_llm_limits import grant_body

    grant = grant_body(rt, manager.operation(op["id"])["grant_id"])
    assert grant["limits"]["max_output_tokens"] == 32768
    assert grant["limits"]["max_duration_ms"] == 360000


def test_lower_cap_keeps_existing_facts_and_snapshots_but_blocks_growth(app_runtime):
    rt = app_runtime
    key = rt.create("Existing catalog")["id"]
    install(rt, key, projection=catalog())
    assert project(rt, key, ingest(rt, key, [fact(0)]))["status"] == "accepted"
    policy = rt.sources.policy(key)
    snapshot = rt.store.snapshot(key)
    change(rt, catalog_predicate_limit=1)
    assert ask(rt, key)["result"]["value"]["value"] == 7
    clone = rt.create("Preserved import", snapshot=snapshot)["id"]
    assert ask(rt, clone)["result"]["value"]["value"] == 7
    projection = extend(policy["projection"], many(0, 2))
    with pytest.raises(CatalogCapacity) as failure:
        rt.sources.coverage(
            key,
            {
                "expected_revision": rt.store.info(key)["revision_id"],
                "expected_generation": policy["generation"],
                "kind": "extend",
                "projection": projection,
                "reason": "Additional properties",
            },
        )
    assert failure.value.diagnostic["limit"] == 1
    assert rt.store.snapshot(key) == snapshot
    assert rt.sources.policy(key) == policy
    change(rt, catalog_predicate_limit=10)
    rt.sources.coverage(
        key,
        {
            "expected_revision": rt.store.info(key)["revision_id"],
            "expected_generation": policy["generation"],
            "kind": "extend",
            "projection": projection,
            "reason": "Additional properties",
        },
    )
    assert ask(rt, key)["result"]["value"]["value"] == 7


def test_schema_18_migration_preserves_rows_and_rolls_back_atomically(tmp_path):
    path = tmp_path / "registry.db"
    with sqlite3.connect(path) as db:
        migrate(db, "registry")
        db.execute("DROP TABLE service_settings")
        db.execute("PRAGMA user_version=18")
        before = list(db.iterdump())

    class Fail(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.startswith("PRAGMA user_version=19"):
                raise RuntimeError("authored rollback fault")
            return super().execute(sql, *args)

    with sqlite3.connect(path, factory=Fail) as db:
        with pytest.raises(RuntimeError):
            migrate(db, "registry")
        assert list(db.iterdump()) == before
        assert db.execute("PRAGMA user_version").fetchone()[0] == 18
    with sqlite3.connect(path) as db:
        migrate(db, "registry")
        assert db.execute("PRAGMA user_version").fetchone()[0] == 19
        assert db.execute("SELECT revision,body FROM service_settings").fetchone() == (0, None)
