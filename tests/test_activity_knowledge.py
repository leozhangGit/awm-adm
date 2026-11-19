"""Current knowledge and complete, nonduplicated console/API activity."""

import pytest

from awm_adm.interaction.activity import history
from awm_adm.interaction.knowledge import search
from awm_adm.runtime.protocol import RuntimeFault

from .interaction_support import narration, proposal
from .test_application import app_runtime as app_runtime
from .test_application import client, envelope, execute, tank
from .test_direct_ask import interpreted, recorded, work
from .test_learning_service import rig as rig


def test_chat_and_api_requests_have_one_history_entry_each_with_original_bindings(rig):
    rt, gw = rig
    key = tank(rt)
    recorded(rt, gw, proposal("capabilities"))
    item = interpreted(rt, gw, key, "What can this model do?", idempotency_key="question")
    execute(rt, key)
    rt.conversations.ask.tick()
    narration(rt, work(rt, key, item["id"]))
    rid = rt.coordinator.submit(key, envelope("api-question", {"op": "capabilities"}))["request_id"]
    execute(rt, key)
    page = history(rt, key)
    assert len(page["items"]) == 2
    assert {i["kind"] for i in page["items"]} == {"ask", "request"}
    query = next(i for i in page["items"] if i["kind"] == "request")
    assert query["request_id"] == rid
    assert query["binding"] == rt.store.request(key, rid)["pinned_context"]
    assert query["summary"] and query["result_id"]
    assert len(history(rt, key, kind="ask")["items"]) == 1
    assert len(history(rt, key, kind="request", origin="api")["items"]) == 1
    assert not history(rt, key, origin="console")["items"]
    with rt.store.db() as db:
        before = db.execute("SELECT count(*) FROM grants").fetchone()[0]
    assert history(rt, key) == page
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == before


def test_activity_pages_are_stable_across_new_messages_and_equal_times(rig, monkeypatch):
    rt, gw = rig
    key = tank(rt)
    recorded(rt, gw, proposal("capabilities"))
    now = rt.learning.now()
    monkeypatch.setattr(rt.learning, "now", lambda: now)
    ids = {rt.interactions.submit(key, "ask", {"text": f"Question {i}"})["id"] for i in range(3)}
    first = history(rt, key, limit=1)
    new = rt.interactions.submit(key, "ask", {"text": "After the query"})
    seen = {first["items"][0]["resource_id"]}
    cursor = first["next_cursor"]
    while cursor:
        page = history(rt, key, after=cursor, limit=1)
        assert not seen & {i["resource_id"] for i in page["items"]}
        seen.update(i["resource_id"] for i in page["items"])
        cursor = page["next_cursor"]
    assert seen == ids and new["id"] not in seen
    with pytest.raises(RuntimeFault, match="time range"):
        history(rt, key, start=int(now * 1000) - 1, after=first["next_cursor"])
    assert len(history(rt, key, start=int(now * 1000), end=int(now * 1000) + 1)["items"]) == 4
    assert not history(rt, key, end=int(now * 1000))["items"]


def test_search_uses_current_accepted_model_and_pins_pagination(app_runtime):
    rt = app_runtime
    key = tank(rt)
    page = search(rt, key, query="tanks", kind="declaration", limit=1)
    assert page["items"] and page["next_cursor"] == 1
    assert page["items"][0]["description"]
    second = search(
        rt, key, query="tanks", kind="declaration", limit=1, after=1, revision=page["revision_id"]
    )
    assert second["items"][0]["id"] != page["items"][0]["id"]
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    with pytest.raises(RuntimeFault, match="accepted model changed"):
        search(rt, key, after=1, revision=page["revision_id"])
    http = client(rt)
    assert http.get(f"/api/v1/adms/{key}/knowledge?query=not-a-symbol").json()["items"] == []
    assert http.get(f"/api/v1/adms/{key}/activity?start=20&end=10").status_code == 422


def test_undated_legacy_source_activity_is_visible_without_an_invented_time(app_runtime):
    from .test_sources import ingest, install, job

    rt = app_runtime
    key = rt.create("Earlier source work")["id"]
    install(rt, key)
    source = ingest(rt, key)
    item = job(rt, key, source)
    with rt.store.db(key) as db:
        db.execute("UPDATE source_jobs SET data=json_remove(data,'$.created') WHERE id=?", (item["id"],))
    page = history(rt, key)
    assert page["undated_legacy_items"] == 1
    entry = next(i for i in page["items"] if i["resource_id"] == item["id"])
    assert entry["created_at_ms"] is None
    assert not history(rt, key, start=0)["items"]


def test_knowledge_evidence_is_readable_and_source_holds_remain_explicit(app_runtime):
    from .test_sources import fact, ingest, install, project

    rt = app_runtime
    key = rt.create("Source search")["id"]
    install(rt, key)
    original = ingest(rt, key)
    assert project(rt, key, original)["status"] == "accepted"
    page = search(rt, key)
    evidence = [r for r in page["items"] if r["category"] == "evidence"]
    assert any("Source assertion: 10 places" in r["description"] for r in evidence)
    assert not any(
        "input_digest:" in r["excerpt"] or "configuration_digest:" in r["excerpt"] for r in evidence
    )
    # Supersession holds current support without deleting the retained declaration.
    ingest(rt, key, [fact(11)], item=original["item_id"], version_id="v2", supersedes_version="v1")
    assert any("support is on hold" in r["description"] for r in search(rt, key, kind="declaration")["items"])
