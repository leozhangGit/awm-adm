"""standing policies: finite budgets, shared interest and local serving."""

from uuid import uuid4

# ruff: noqa: F811
import pytest

from awm_adm.runtime.protocol import RuntimeFault
from awm_adm.runtime.service import Runtime

from .test_application import app_runtime, client, configuration, envelope, execute  # noqa: F401
from .test_sources import fact, ingest, install, profile, project, scope


def feed(rt, key, **kw):
    return rt.sources.feeds.create(
        key,
        {
            "idempotency_key": str(uuid4()),
            "name": "Authored history feed",
            "expected_revision": rt.store.info(key)["revision_id"],
            "expected_source_generation": rt.sources.policy(key)["generation"],
            "source_ids": ["records"],
            "enabled": True,
            "publication": "checked_auto",
            "requirements": profile()["predicates"],
            **kw,
        },
    )


def pump(rt, key, target="accepted", count=50):
    for _ in range(count):
        rt.sources.tick()
        page = rt.sources.feeds.overview(key)
        if any(i["status"] == target for i in page["items"]):
            return page
    raise AssertionError(page)


def control(rt, key, f, enabled):
    current = rt.sources.feeds.get(key, f["id"])
    return rt.sources.feeds.control(
        key,
        f["id"],
        {
            "expected_generation": current["generation"],
            "expected_revision": rt.store.info(key)["revision_id"],
            "enabled": enabled,
        },
    )


def lookup(rt, key, year=2021):
    return rt.query(
        key,
        {
            "op": "lookup_fact",
            "entity_id": "site",
            "predicate": "site.capacity",
            "effective_at": f"{year}-01-01T00:00:00Z",
        },
    )


def test_enabled_feed_learns_without_request_and_serves(app_runtime):
    rt = app_runtime
    key = rt.create("empty")["id"]
    install(rt, key)
    f = feed(rt, key)
    ingest(rt, key)
    page = pump(rt, key)
    assert page["feeds"][0]["reserved"]["items"] == 1
    assert lookup(rt, key)["result"]["status"] == "succeeded"
    before = rt.store.info(key)["revision_id"]
    for _ in range(8):
        rt.sources.tick()
    assert rt.store.info(key)["revision_id"] == before
    assert rt.sources.feeds.get(key, f["id"])["cursor"] == 1
    ingest(rt, key, [fact(12, 2024, 2026)])
    for _ in range(30):
        rt.sources.tick()
    assert lookup(rt, key, 2025)["result"]["status"] == "succeeded"
    assert rt.sources.feeds.overview(key)["feeds"][0]["counts"]["accepted"] == 2


def test_pause_one_shared_interest_and_last_interest_fence(app_runtime):
    rt = app_runtime
    key = rt.create("shared")["id"]
    install(rt, key)
    a, b = feed(rt, key), feed(rt, key)
    ingest(rt, key)
    for _ in range(5):
        rt.sources.tick()
    control(rt, key, a, False)
    page = pump(rt, key)
    assert len({i["id"] for i in page["items"]}) == 1
    assert len(rt.sources.overview(key)["episodes"]) == 1
    assert all(f["reserved"]["items"] == 1 for f in page["feeds"])
    control(rt, key, b, False)
    ingest(rt, key, [fact(12, 2024, 2026)])
    for _ in range(10):
        rt.sources.tick()
    assert lookup(rt, key, 2025)["result"]["status"] == "needs_input"
    control(rt, key, b, True)
    for _ in range(30):
        rt.sources.tick()
    assert lookup(rt, key, 2025)["result"]["status"] == "succeeded"


def test_owner_requirements_hold_invalid_auto_value(app_runtime):
    rt = app_runtime
    key = rt.create("requirements")["id"]
    install(rt, key)
    requirements = profile()["predicates"]
    requirements[0]["maximum"] = 5
    feed(rt, key, requirements=requirements)
    ingest(rt, key)
    for _ in range(15):
        rt.sources.tick()
    page = rt.sources.feeds.overview(key)
    assert page["items"][0]["episode_status"] == "awaiting_review"
    assert lookup(rt, key)["result"]["status"] == "needs_input"
    with pytest.raises(RuntimeFault, match="requirements"):
        feed(rt, key, requirements=[])


def test_review_holds_order_but_serving_and_other_adm_progress(app_runtime):
    rt = app_runtime
    a = rt.create("a")["id"]
    b = rt.create("b")["id"]
    for key in (a, b):
        install(rt, key)
    feed(rt, a, publication="review")
    feed(rt, b)
    ingest(rt, a)
    ingest(rt, a, [fact(12, 2024, 2026)])
    ingest(rt, b)
    pump(rt, b)
    for _ in range(15):
        rt.sources.tick()
    page = rt.sources.feeds.overview(a)
    assert all(i.get("episode_status") == "awaiting_review" for i in page["items"])
    assert rt.query(a, {"op": "capabilities"})["result"]["status"] == "succeeded"
    assert lookup(rt, b)["result"]["status"] == "succeeded"
    first, second = page["items"]
    rt.sources.review(
        a, second["episode"], {"expected_revision": rt.store.info(a)["revision_id"], "approve": True}
    )
    for _ in range(5):
        rt.sources.tick()
    assert lookup(rt, a, 2025)["result"]["status"] == "needs_input"
    rt.sources.review(
        a, first["episode"], {"expected_revision": rt.store.info(a)["revision_id"], "approve": True}
    )
    pump(rt, a)


def test_poison_no_progress_and_lifetime_budget(app_runtime):
    rt = app_runtime
    key = rt.create("poison")["id"]
    install(rt, key)
    f = feed(rt, key, max_failures=2, max_pending=1)
    for _ in range(5):
        ingest(rt, key, content="invalid JSON")
    for _ in range(30):
        rt.sources.tick()
    current = rt.sources.feeds.get(key, f["id"])
    assert not current["enabled"] and current["stall_reason"] == "no_progress_limit"
    assert current["reserved"]["items"] == 2
    assert rt.sources.feeds.overview(key)["feeds"][0]["backlog"] == 3
    key2 = rt.create("bounded")["id"]
    install(rt, key2)
    g = feed(rt, key2, budget={"max_items": 1, "max_work": 3000000})
    ingest(rt, key2)
    ingest(rt, key2, [fact(12, 2024, 2026)])
    for _ in range(25):
        rt.sources.tick()
    current = rt.sources.feeds.get(key2, g["id"])
    assert current["reserved"]["items"] == 1 and current["stall_reason"] == "quota_exceeded"
    control(rt, key2, g, False)
    control(rt, key2, g, True)
    for _ in range(5):
        rt.sources.tick()
    assert rt.sources.feeds.get(key2, g["id"])["reserved"]["items"] == 1


def test_durable_pause_restart_cursor_and_explicit_reprocessing(tmp_path):
    config = configuration(tmp_path / "store")
    rt = Runtime(config, start_scheduler=False)
    key = rt.create("restart")["id"]
    install(rt, key)
    f = feed(rt, key)
    ingest(rt, key)
    rt.sources.feeds.tick()  # durable item before job creation
    control(rt, key, f, False)
    rt.close()
    rt = Runtime(config, start_scheduler=False)
    try:
        for _ in range(5):
            rt.sources.tick()
        assert lookup(rt, key)["result"]["status"] == "needs_input"
        control(rt, key, f, True)
        pump(rt, key)
        before = rt.store.info(key)["revision_id"]
        current = rt.sources.feeds.get(key, f["id"])
        body = {
            "idempotency_key": "explicit-redo",
            "expected_generation": current["generation"],
            "source_sequence": 1,
        }
        one = rt.sources.feeds.reprocess(key, f["id"], body)
        assert rt.sources.feeds.reprocess(key, f["id"], body) == one
        assert rt.sources.feeds.get(key, f["id"])["reserved"]["items"] == 2
        for _ in range(20):
            rt.sources.tick()
        assert len(rt.sources.overview(key)["jobs"]) == 2
        assert rt.store.info(key)["revision_id"] != before
    finally:
        rt.close()


def transition(rt, key, p, kind="extend"):
    return rt.sources.coverage(
        key,
        {
            "expected_revision": rt.store.info(key)["revision_id"],
            "expected_generation": rt.sources.policy(key)["generation"],
            "projection": p,
            "kind": kind,
            "reason": "Owner selected bounded coverage",
        },
    )


def test_coverage_preserves_symbols_and_window_holds_history(app_runtime):
    rt = app_runtime
    key = rt.create("coverage")["id"]
    install(rt, key)
    project(rt, key, ingest(rt, key))
    before = lookup(rt, key)["result"]
    p = profile()
    p["cells"].append(scope(2026, 2028))
    transition(rt, key, p)
    assert lookup(rt, key)["result"]["status"] == "succeeded"
    project(rt, key, ingest(rt, key, [fact(12, 2026, 2028)]))
    assert lookup(rt, key, 2027)["result"]["status"] == "succeeded"
    # Re-acquiring the old cell reuses its original symbol even after extension.
    project(rt, key, ingest(rt, key))
    assert lookup(rt, key)["result"]["fact"]["symbol"] == before["fact"]["symbol"]
    p["cells"] = p["cells"][1:]
    transition(rt, key, p, "window")
    assert lookup(rt, key)["result"]["status"] == "needs_input"
    assert lookup(rt, key, 2027)["result"]["status"] == "succeeded"
    assert len(rt.sources.overview(key)["versions"]) == 3


def test_unsupported_coverage_change_is_atomic(app_runtime):
    rt = app_runtime
    key = rt.create("coverage")["id"]
    install(rt, key)
    project(rt, key, ingest(rt, key))
    before = rt.store.info(key)["revision_id"]
    p = profile()
    p["cells"] = [scope(2020, 2022), scope(2022, 2026)]
    with pytest.raises(RuntimeFault):
        transition(rt, key, p, "window")
    assert rt.store.info(key)["revision_id"] == before
    assert lookup(rt, key)["result"]["status"] == "succeeded"


def test_feed_http_owner_authority_and_pagination(app_runtime):
    rt = app_runtime
    key = rt.create("http")["id"]
    install(rt, key)
    with client(rt) as c:
        assert c.get(f"/api/v1/adms/{key}/feeds?limit=0").status_code == 422
        body = {
            "idempotency_key": "http-feed",
            "name": "Local",
            "expected_revision": rt.store.info(key)["revision_id"],
            "expected_source_generation": 1,
            "source_ids": ["records"],
        }
        response = c.post(f"/api/v1/adms/{key}/feeds", json=body)
        assert response.status_code == 201, response.text
        assert not response.json()["enabled"]
        assert c.post(f"/api/v1/adms/{key}/feeds", json=body).json()["id"] == response.json()["id"]


def extraction_connection(rt, gateway):
    import json

    content = json.dumps([fact()])
    c = rt.learning.save_connection(
        {
            "idempotency_key": str(uuid4()),
            "name": "Recorded extraction",
            "provider": "recorded",
            "model": "fixture",
            "enabled": True,
            "purposes": ["extraction"],
            "recorded_responses": [
                {"claims": [{**fact(), "start_byte": 0, "end_byte": len(content.encode())}]}
            ],
        }
    )
    gateway.synchronize()
    gateway.synchronize()
    return rt.learning.connection(c["id"])


from .test_learning_service import dispatch, rig  # noqa: E402, F401


def test_two_adms_shared_connection_and_unknown_across_period(rig, monkeypatch):
    rt, gateway = rig
    c = extraction_connection(rt, gateway)
    keys = [rt.create(n)["id"] for n in ("one", "two")]
    for key in keys:
        install(rt, key)
        feed(
            rt,
            key,
            extractor="external",
            connection_id=c["id"],
            connection_version=c["version"],
            allow_external=True,
        )
        ingest(rt, key)
    for _ in range(5):
        rt.sources.tick()
    claim = rt.learning.claim()
    assert claim
    rt.learning.authorize(claim["grant_id"], claim["lease"])  # authored worker death after dispatch
    for _ in range(5):
        rt.sources.tick()
    # Background has one slot; a dead worker must first become explicitly unknown.
    assert rt.learning.claim() is None
    rt.learning.outcome(claim["grant_id"], claim["lease"], {"status": "outcome_unknown"})
    dispatch(rt, gateway)
    with rt.store.db() as db:
        dispatched_adm = db.execute("SELECT adm FROM grants WHERE id=?", (claim["grant_id"],)).fetchone()[0]
    other = next(k for k in keys if k != dispatched_adm)
    pump(rt, other)
    usage = rt.learning.usage()
    assert usage["unresolved"] >= 1
    now = rt.learning.now()
    monkeypatch.setattr(rt.learning, "now", lambda: now + 2 * rt.config.learning.quotas.period_seconds)
    rt.learning.tick()
    assert rt.learning.usage()["calls"] >= 1
    assert rt.learning.usage()["unresolved"] >= 1
    for key in keys:
        assert rt.sources.feeds.overview(key)["feeds"][0]["reserved"]["calls"] == 1
    assert rt.learning.claim() is None  # no unknown retry


def test_restart_after_external_reservation_never_redispatches(rig):
    rt, gateway = rig
    c = extraction_connection(rt, gateway)
    key = rt.create("crash")["id"]
    install(rt, key)
    f = feed(
        rt,
        key,
        extractor="external",
        connection_id=c["id"],
        connection_version=c["version"],
        allow_external=True,
    )
    ingest(rt, key)
    for _ in range(4):
        rt.sources.tick()
    claim = rt.learning.claim()
    assert claim
    rt.learning.authorize(claim["grant_id"], claim["lease"])
    config = rt.config
    rt.close()
    other = Runtime(config, start_scheduler=False)
    try:
        page = pump(other, key, "dead_letter")
        assert page["provider_usage"]["unresolved"] == 1
        assert other.learning.claim() is None
        assert other.sources.feeds.get(key, f["id"])["reserved"]["calls"] == 1
    finally:
        other.close()


def test_last_interest_pause_during_compute_blocks_activation(app_runtime, monkeypatch):
    rt = app_runtime
    key = rt.create("race")["id"]
    install(rt, key)
    f = feed(rt, key)
    ingest(rt, key)
    original = rt.sources.compute

    def paused(*args, **kwargs):
        value = original(*args, **kwargs)
        if args[1] == "source_admit":
            control(rt, key, f, False)
        return value

    monkeypatch.setattr(rt.sources, "compute", paused)
    for _ in range(15):
        rt.sources.tick()
    assert lookup(rt, key)["result"]["status"] == "needs_input"
    assert rt.sources.overview(key)["episodes"][0]["status"] == "failed"


def test_mode_or_source_policy_change_stalls_feed(app_runtime):
    rt = app_runtime
    key = rt.create("change")["id"]
    install(rt, key)
    f = feed(rt, key)
    ingest(rt, key)
    rt.sources.feeds.tick()
    # Owner policy revision changes the authority epoch before a queued extraction.
    install(rt, key)
    for _ in range(5):
        rt.sources.tick()
    page = rt.sources.feeds.overview(key)
    assert page["feeds"][0]["stall_reason"] == "policy_changed_requires_owner_review"
    assert not rt.sources.overview(key)["jobs"]
    with pytest.raises(RuntimeFault):
        control(rt, key, f, True)


def test_bounded_history_preserves_complete_original_and_authority(app_runtime):
    rt = app_runtime
    key = rt.create("history")["id"]
    install(rt, key)
    for _ in range(3):
        ingest(rt, key, content="x" * 3000, media_type="text/plain")
    with client(rt) as c:
        base = f"/api/v1/adms/{key}"
        page = c.get(base + "/sources?limit=2").json()
        assert page["more"] and len(page["versions"]) == 2
        row = page["versions"][0]
        assert row["content_truncated"] and len(row["content"]) == 2048
        assert len(c.get(base + "/sources/history/versions/" + row["id"]).json()["content"]) == 3000
        assert len(c.get(base + "/sources?limit=2&page=1").json()["versions"]) == 1
        issued = c.post("/api/v1/auth/tokens", json={"adms": [key], "permissions": ["read"]}).json()
        headers = {"Authorization": "Bearer " + issued["token"]}
        assert c.get(base + "/feeds", headers=headers).status_code == 200
        body = {
            "idempotency_key": "denied",
            "name": "Denied",
            "source_ids": ["records"],
            "expected_revision": rt.store.info(key)["revision_id"],
            "expected_source_generation": 1,
        }
        assert c.post(base + "/feeds", json=body, headers=headers).status_code == 403
        c.headers.pop("Authorization")
        assert c.post(base + "/feeds", json={}).status_code in (401, 422)


def test_backpressure_keeps_cursor_and_review_hold_visible(app_runtime):
    rt = app_runtime
    key = rt.create("overload")["id"]
    install(rt, key)
    f = feed(rt, key, publication="review", max_pending=2)
    for _ in range(8):
        ingest(rt, key)
    for _ in range(30):
        rt.sources.tick()
    page = rt.sources.feeds.overview(key)
    assert page["feeds"][0]["backlog"] == 6
    assert page["feeds"][0]["reserved"]["items"] == 2
    assert page["feeds"][0]["stall_reason"] == "pending_limit"
    assert all(i["episode_status"] == "awaiting_review" for i in page["items"])
    assert rt.sources.feeds.get(key, f["id"])["cursor"] == 2


def test_conflict_modes_and_future_only_owner_resume(app_runtime):
    rt = app_runtime
    key = rt.create("modes")["id"]
    install(rt, key)
    f = feed(rt, key)
    ingest(rt, key)
    pump(rt, key)
    ingest(rt, key, [fact(12)])
    pump(rt, key, "rejected")
    assert lookup(rt, key)["result"]["value"] == 10
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    ingest(rt, key, [fact(14)])
    for _ in range(5):
        rt.sources.tick()
    assert (
        rt.sources.feeds.overview(key)["feeds"][0]["stall_reason"] == "policy_changed_requires_owner_review"
    )
    control(rt, key, f, True)
    for _ in range(20):
        rt.sources.tick()
    assert lookup(rt, key)["result"]["value"] == 14
    assert rt.sources.feeds.overview(key)["feeds"][0]["counts"]["rejected"] == 1


def test_schema_six_migrates_without_republishing_existing_fact(tmp_path):
    config = configuration(tmp_path / "migration")
    rt = Runtime(config, start_scheduler=False)
    key = rt.create("v6")["id"]
    install(rt, key)
    project(rt, key, ingest(rt, key))
    before = rt.store.info(key)["revision_id"]
    result = lookup(rt, key)["result"]
    with rt.store.db(key) as db:
        for table in ("feeds", "feed_runs", "feed_items", "feed_controls", "coverage_transitions"):
            db.execute("DROP TABLE " + table)
        from tests.migration_support import remove_conversations

        remove_conversations(db)
        db.execute("PRAGMA user_version=6")
    with rt.store.db() as db:
        from tests.migration_support import remove_admin

        remove_admin(db)
        from tests.migration_support import remove_conversations

        remove_conversations(db)
        db.execute("PRAGMA user_version=6")
    rt.close()
    new = Runtime(config, start_scheduler=False)
    try:
        assert new.store.info(key)["revision_id"] == before
        after = lookup(new, key)["result"]
        assert {k: v for k, v in after.items() if k != "execution"} == {
            k: v for k, v in result.items() if k != "execution"
        }
        assert new.store.run_info(key, result["execution"]["run_id"])["result"] == result
        assert new.sources.feeds.overview(key)["feeds"] == []
        with new.store.db(key) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 15
    finally:
        new.close()


def test_concurrent_feed_global_cap_survives_unknown_period_rollover(rig, monkeypatch):
    from awm_adm.config import AppConfig

    rt, gateway = rig
    config = rt.config.model_dump()
    config["learning"]["episode"].update(max_calls=1, no_progress_attempts=1)
    config["learning"]["quotas"].update(calls_per_adm=1, calls_installation=1)
    rt.config = rt.learning.config = AppConfig.model_validate(config)
    c = extraction_connection(rt, gateway)
    keys = [rt.create(name)["id"] for name in ("cap-a", "cap-b")]
    for key in keys:
        install(rt, key)
        feed(
            rt,
            key,
            extractor="external",
            allow_external=True,
            connection_id=c["id"],
            connection_version=c["version"],
            budget={"max_items": 1, "max_calls": 1, "max_work": 3000000},
        )
        ingest(rt, key)
    for _ in range(12):
        rt.sources.tick()
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == 1
    job = rt.learning.claim()
    assert job
    rt.learning.authorize(job["grant_id"], job["lease"])
    now = rt.learning.now()
    monkeypatch.setattr(rt.learning, "now", lambda: now + 2 * rt.config.learning.quotas.period_seconds)
    rt.learning.tick()
    for _ in range(10):
        rt.sources.tick()
    assert rt.learning.usage()["calls"] == 1
    assert rt.learning.usage()["unresolved"] == 1
    assert rt.learning.claim() is None
    assert all(rt.sources.feeds.overview(k)["feeds"][0]["reserved"]["calls"] == 1 for k in keys)
    reasons = {i["reason"] for k in keys for i in rt.sources.feeds.overview(k)["items"]}
    assert "quota_exceeded" in reasons
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == 1


@pytest.mark.parametrize("approve", [True, False])
def test_restart_preserves_completed_feed_records_exactly(tmp_path, approve):
    config = configuration(tmp_path / "terminal-history")
    rt = Runtime(config, start_scheduler=False)
    key = rt.create("terminal history")["id"]
    install(rt, key)
    f = feed(rt, key, publication="review")
    ingest(rt, key)
    for _ in range(15):
        rt.sources.tick()
    episode = rt.sources.overview(key)["episodes"][0]
    assert episode["status"] == "awaiting_review"
    rt.sources.review(
        key, episode["id"], {"expected_revision": rt.store.info(key)["revision_id"], "approve": approve}
    )
    for _ in range(15):
        rt.sources.tick()
    control(rt, key, f, False)

    def history(runtime):
        with runtime.store.db(key) as db:
            return {
                table: [tuple(row) for row in db.execute(f"SELECT id,status,data FROM {table} ORDER BY seq")]
                for table in ("source_jobs", "source_episodes")
            }

    original = history(rt)
    assert original["source_jobs"][0][1] == "extracted"
    assert original["source_episodes"][0][1] == ("accepted" if approve else "rejected")
    info = rt.store.info(key)
    feed_state = rt.sources.feeds.overview(key)
    rt.close()
    for _ in range(2):
        rt = Runtime(config, start_scheduler=False)
        try:
            assert history(rt) == original
            for _ in range(5):
                rt.sources.tick()
            assert history(rt) == original
            assert rt.store.info(key) == info
            assert rt.sources.feeds.overview(key) == feed_state
            assert rt.learning.claim() is None
        finally:
            rt.close()


def test_restart_keeps_feed_review_pending_until_new_owner_approval(tmp_path):
    config = configuration(tmp_path / "review-recovery")
    rt = Runtime(config, start_scheduler=False)
    key = rt.create("review recovery")["id"]
    install(rt, key)
    feed(rt, key, publication="review")
    ingest(rt, key)
    for _ in range(15):
        rt.sources.tick()
    episode = rt.sources.overview(key)["episodes"][0]
    assert episode["status"] == "awaiting_review"
    revision = rt.store.info(key)["revision_id"]
    rt.close()
    rt = Runtime(config, start_scheduler=False)
    try:
        for _ in range(5):
            rt.sources.tick()
        recovered = rt.sources.get(key, "source_episodes", episode["id"])
        assert recovered["status"] == "awaiting_review"
        assert rt.store.info(key)["revision_id"] == revision
        assert lookup(rt, key)["result"]["status"] == "needs_input"
        rt.sources.review(key, episode["id"], {"expected_revision": revision, "approve": True})
        pump(rt, key)
        assert lookup(rt, key)["result"]["status"] == "succeeded"
        assert rt.learning.usage()["calls"] == 0
    finally:
        rt.close()
