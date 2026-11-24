"""Historical Ask uses ordinary local requests; provider text cannot become a fact."""

import pytest

from awm_adm.conversations.history import parse
from awm_adm.runtime.protocol import dumps

from .interaction_support import narration, proposal
from .test_application import app_runtime as app_runtime
from .test_application import execute
from .test_direct_ask import interpreted, recorded
from .test_direct_ask import work as work_record
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
    recorded(rt, gw, proposal(command(year)))
    item = interpreted(rt, gw, key, f"What was site capacity at January 1, {year}, midnight UTC?")
    work = work_record(rt, key, item["id"])
    assert work["status"] == "awaiting_local", work
    metadata = work["accepted_fact_projections"]
    assert len(metadata) == 1 and set(metadata[0]) == {"entities", "predicates", "cells"}
    assert "source" not in dumps(metadata).decode() and "assertion_kind" not in dumps(metadata).decode()
    result = execute(rt, key)
    assert result["status"] == expected
    assert result["query"]["effective_at"].startswith(str(year))
    assert rt.conversations.tick()
    narration(rt, work_record(rt, key, item["id"]))
    presentation = rt.conversations.ask.get(key, work["id"])
    assert presentation["outcome"]["binding"] == (
        result["result"]["binding"] if result["result"] else result["pinned_context"]
    )
    if expected == "succeeded":
        assert result["result"]["value"]["value"] == 10
        assert result["result"]["binding"]["context"]["adm_id"] == key
        assert result["result"]["value"]["fact"]["claim"]["source"]["version_id"] == "v1"
        assert (
            presentation["outcome_text"]
            == "Model answer: 10 places.\nBased on the model's accepted historical evidence."
        )
    assert rt.learning.usage()["calls"] == 2


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
