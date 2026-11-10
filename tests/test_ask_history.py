"""Historical Ask uses ordinary local requests; provider text cannot become a fact."""

import pytest

from awm_adm.conversations.history import parse
from awm_adm.runtime.protocol import dumps, loads

from .test_application import app_runtime as app_runtime
from .test_application import execute
from .test_ask import funded, interpret, proposal
from .test_learning_service import rig as rig
from .test_sources import fact, ingest, install, profile, project


def command(year=2021, **changes):
    return (
        "lookup fact with "
        + dumps(
            {
                "entity_id": "site",
                "predicate": "site.capacity",
                "effective_at": f"{year}-01-01T00:00:00Z",
                **changes,
            }
        ).decode()
    )


@pytest.mark.parametrize("year,expected", [(2021, "succeeded"), (2027, "needs_input")])
@pytest.mark.parametrize("origin", ["original", "snapshot", "disputed_snapshot"])
def test_history_local_answer_and_unknown(rig, year, expected, origin):
    rt, gw = rig
    key = rt.create("Historical Ask")["id"]
    install(rt, key)
    source = ingest(rt, key)
    assert project(rt, key, source)["status"] == "accepted"
    if origin == "disputed_snapshot":
        ingest(rt, key, [fact(11)], item=source["item_id"], version_id="v2", supersedes_version="v1")
        expected = "needs_input"
    if origin != "original":
        original = key
        key = rt.create("Snapshot copy", snapshot=rt.store.revision(key)["snapshot"])["id"]
        assert key != original and not rt.sources.versions(key)
        assert rt.sources.policy(key).get("projection") is None
    key, cid = funded(rt, gw, command(year), key=key)
    work, _ = interpret(rt, gw, key, cid, f"What was site capacity at January 1, {year}, midnight UTC?")
    assert work["status"] == "awaiting_local", work
    metadata = work["accepted_fact_projections"]
    assert len(metadata) == 1 and set(metadata[0]) == {"entities", "predicates", "cells"}
    assert "source" not in dumps(metadata).decode() and "assertion_kind" not in dumps(metadata).decode()
    result = execute(rt, key)
    assert result["status"] == expected
    assert result["query"]["effective_at"].startswith(str(year))
    assert rt.conversations.tick()
    presentation = rt.conversations.ask.get(key, work["id"])
    assert presentation["outcome"]["binding"] == (
        result["result"]["binding"] if result["result"] else result["pinned_context"]
    )
    if expected == "succeeded":
        assert result["result"]["value"]["value"] == 10
        assert result["result"]["binding"]["context"]["adm_id"] == key
        assert result["result"]["value"]["fact"]["claim"]["source"]["version_id"] == "v1"
        assert "Historical lookup for site" in presentation["outcome_text"]
    assert rt.learning.usage()["calls"] == 1


@pytest.mark.parametrize(
    "suffix",
    [
        '{"entity_id":"site","predicate":"site.capacity","effective_at":"2021-01-01T00:00:00Z","authorize":true}',
        '{"entity_id":"site","entity_id":"foreign","predicate":"site.capacity","effective_at":"2021-01-01T00:00:00Z"}',
        '{"entity_id":"site","predicate":"site.capacity","effective_at":"tomorrow"}',
        "[]",
    ],
)
def test_history_rejects_authority_duplicates_and_missing_dates(suffix):
    with pytest.raises(ValueError):
        parse(dumps(proposal("lookup fact with " + suffix)).decode(), profile())


def test_history_unknown_identity_asks_without_executing():
    parsed = parse(dumps(proposal(command(entity_id="other"))).decode(), profile())
    assert parsed["status"] == "needs_clarification" and parsed["query"] is None


def test_prior_allowance_does_not_gain_projection_disclosure(rig):
    rt, gw = rig
    key, cid = funded(rt, gw)
    with rt.store.db(key) as db, rt.store.transaction(db):
        conv = loads(db.execute("SELECT body FROM chat_conversations WHERE id=?", (cid,)).fetchone()[0])
        conv["preferences"].pop("historical_lookup")
        conv["preferences"].pop("snapshot_history")
        db.execute("UPDATE chat_conversations SET body=? WHERE id=?", (dumps(conv), cid))
    work, _ = interpret(rt, gw, key, cid)
    assert "fact_projection" not in work
    with rt.store.db() as db:
        grant = loads(db.execute("SELECT body FROM grants WHERE id=?", (work["grant_id"],)).fetchone()[0])
    import base64

    assert b"owner_fact_projection" not in base64.b64decode(grant["wire"])
    assert b"accepted_fact_projections" not in base64.b64decode(grant["wire"])


def test_projection_only_consent_does_not_gain_snapshot_disclosure(rig):
    rt, gw = rig
    key = rt.create("History")["id"]
    install(rt, key)
    assert project(rt, key, ingest(rt, key))["status"] == "accepted"
    key = rt.create("Copy", snapshot=rt.store.revision(key)["snapshot"])["id"]
    key, cid = funded(rt, gw, command(), key=key)
    with rt.store.db(key) as db, rt.store.transaction(db):
        conv = loads(db.execute("SELECT body FROM chat_conversations WHERE id=?", (cid,)).fetchone()[0])
        conv["preferences"].pop("snapshot_history")
        db.execute("UPDATE chat_conversations SET body=? WHERE id=?", (dumps(conv), cid))
    work, _ = interpret(rt, gw, key, cid)
    assert work["status"] == "needs_input" and "request_id" not in work
    assert "accepted_fact_projections" not in work
    with rt.store.db() as db:
        grant = loads(db.execute("SELECT body FROM grants WHERE id=?", (work["grant_id"],)).fetchone()[0])
    import base64

    assert b"accepted_fact_projections" not in base64.b64decode(grant["wire"])
    assert rt.learning.usage()["calls"] == 1
