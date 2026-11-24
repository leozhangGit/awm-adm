"""Civil-time semantics, whole-period evidence and recorded chat; no live providers."""

import json
from uuid import uuid4

import pytest

from awm_adm.conversations.history import parse
from awm_adm.conversations.presentation import readable
from awm_adm.engine.artifacts import digest
from awm_adm.engine.data import encode
from awm_adm.temporal import context, day_bounds, system_timezone

from .interaction_support import narration, proposal, reply
from .test_application import app_runtime as app_runtime
from .test_application import execute
from .test_chat_followups import start
from .test_direct_ask import recorded, work
from .test_learning_service import rig as rig
from .test_sources import fact, ingest, install, profile, project


def day_command(day, zone=None):
    return "lookup fact with " + json.dumps(
        {
            "entity_id": "site",
            "predicate": "site.capacity",
            "effective_on": day,
            "timezone": zone,
        }
    )


@pytest.mark.parametrize(
    "day,zone,bounds",
    [
        ("2026-07-01", "America/New_York", ("2026-07-01T04:00:00Z", "2026-07-02T04:00:00Z")),
        ("2026-03-08", "America/New_York", ("2026-03-08T05:00:00Z", "2026-03-09T04:00:00Z")),
        ("2026-11-01", "America/New_York", ("2026-11-01T04:00:00Z", "2026-11-02T05:00:00Z")),
        ("2026-07-01", "Asia/Kolkata", ("2026-06-30T18:30:00Z", "2026-07-01T18:30:00Z")),
        ("2026-07-01", "UTC", ("2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z")),
    ],
)
def test_civil_day_keeps_whole_period_including_dst(day, zone, bounds):
    assert day_bounds(day, zone) == bounds


def test_civil_day_preserves_four_digit_years_and_rejects_range_overflow():
    assert day_bounds("0001-01-01", "UTC") == (
        "0001-01-01T00:00:00Z",
        "0001-01-02T00:00:00Z",
    )
    for day, zone in [("9999-12-31", "UTC"), ("0001-01-01", "Asia/Tokyo")]:
        with pytest.raises(ValueError, match="supported datetime range"):
            day_bounds(day, zone)


def test_out_of_range_provider_date_finishes_ask_without_crashing_worker(rig):
    rt, gateway = rig
    key = rt.create("Boundary date")["id"]
    install(rt, key)
    recorded(rt, gateway, {})
    first, _ = start(rt, key, "What was capacity on 31 December 9999?")
    reply(rt, proposal(day_command("9999-12-31", "UTC")))
    assert rt.conversations.ask.tick()
    result = rt.interactions.get(key, first["id"])
    assert result["status"] == "failed"
    assert result["request_id"] is None
    assert result["failure_code"] == "invalid_provider_reply"
    # A rejected interpretation does not prevent the next queued exchange.
    second = rt.interactions.submit(key, "ask", {"text": "What can this model do?"})
    assert rt.conversations.ask.tick()
    assert work(rt, key, second["id"])["status"] == "awaiting_provider"


def test_system_zone_handoff_and_explicit_invalid_setting_fail_closed(monkeypatch, tmp_path):
    path = tmp_path / "system-timezone"
    path.write_text("America/New_York\n")
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setenv("AWM_ADM_TIMEZONE_FILE", str(path))
    assert system_timezone() == "America/New_York"
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    assert context() == {"system_timezone": "Asia/Tokyo"}
    monkeypatch.setenv("TZ", "missing/zone")
    with pytest.raises(ValueError):
        system_timezone()


def test_date_resolution_and_explicit_zone_do_not_change_exact_instant_contract():
    for explicit, zone, hour in [(None, "America/New_York", "04"), ("UTC", "UTC", "00")]:
        value = parse(
            json.dumps(proposal(day_command("2021-07-01", explicit))),
            profile(),
            temporal_context={"system_timezone": "America/New_York"},
        )
        assert value["temporal_resolution"]["timezone"] == zone
        assert value["query"]["effective_from"] == f"2021-07-01T{hour}:00:00Z"
        assert value["query"]["op"] == "lookup_fact_period"
    instant = {"entity_id": "site", "predicate": "site.capacity", "effective_at": "2021-07-01T00:00:00Z"}
    value = parse(json.dumps(proposal("lookup fact with " + json.dumps(instant))), profile())
    assert value["query"] == {"op": "lookup_fact", **instant}
    assert "temporal_resolution" not in value
    for day, zone in [
        ("2021-02-30", None),
        ("20210701", None),
        ("2021-07-01", ""),
        ("2021-07-01", "bad/zone"),
    ]:
        with pytest.raises(ValueError):
            parse(
                json.dumps(proposal(day_command(day, zone))),
                profile(),
                temporal_context={"system_timezone": "UTC"},
            )
    skipped = parse(json.dumps(proposal(day_command("2011-12-30", "Pacific/Apia"))), profile())
    assert skipped["status"] == "needs_clarification" and skipped["query"] is None


@pytest.mark.parametrize(
    "case,expected",
    [
        ("same", "succeeded"),
        ("change", "needs_input"),
        ("gap", "needs_input"),
        ("partial", "needs_input"),
        ("disputed", "needs_input"),
        ("snapshot", "succeeded"),
        ("point", "needs_input"),
        ("unknown", "needs_input"),
    ],
)
def test_period_requires_complete_unique_active_same_value_support(app_runtime, case, expected):
    rt = app_runtime
    key = rt.create("Period evidence")["id"]
    begin, middle, end = "2021-07-01T00:00:00Z", "2021-07-01T12:00:00Z", "2021-07-02T00:00:00Z"
    p = profile()
    cells = [
        {"kind": "interval", "granularity": "second", "effective_from": left, "effective_to": right}
        for left, right in [(begin, middle), (middle, end)]
    ]
    if case == "gap":
        cells[1]["effective_from"] = "2021-07-01T13:00:00Z"
    if case == "point":
        cells = [{"kind": "point", "granularity": "second", "effective_from": begin, "effective_to": None}]
    p["cells"] = cells
    install(rt, key, projection=p)
    facts = [fact(10 if i == 0 or case != "change" else 11, temporal_scope=c) for i, c in enumerate(cells)]
    source = ingest(rt, key, facts[:1] if case == "partial" else facts)
    assert project(rt, key, source)["status"] == "accepted"
    if case == "disputed":
        ingest(rt, key, facts, item=source["item_id"], version_id="v2", supersedes_version="v1")
    if case == "snapshot":
        key = rt.create("Independent period snapshot", snapshot=rt.store.revision(key)["snapshot"])["id"]
    q = {
        "op": "lookup_fact_period",
        "entity_id": "site",
        "predicate": "site.capacity",
        "effective_from": begin,
        "effective_to": end,
    }
    if case == "unknown":
        q.update(effective_from="2027-07-01T00:00:00Z", effective_to="2027-07-02T00:00:00Z")
    rt.coordinator.submit(key, {"idempotency_key": str(uuid4()), "query": q})
    result = execute(rt, key)
    assert result["status"] == expected
    if expected == "succeeded":
        bound = result["result"]
        assert bound["value"]["value"] == 10
        assert len(bound["value"]["facts"]) == 2
        assert bound["value"]["binding"]["query"] == q
        assert bound["binding"]["query_digest"] == digest(encode(q))
        assert bound["binding"]["context"]["adm_id"] == key
        assert bound["empirical_fidelity"] == "conditional_on_declared_sources"
    else:
        assert result["result"] is None
        reason = result["error"]["details"]["local_result"]["error"]["message"]
        if case == "change":
            assert reason == "value_varies_within_period"
        if case == "disputed":
            assert reason == "disputed_source_support"
    assert rt.learning.usage()["calls"] == 0


def test_recorded_followup_reaches_local_unknown_and_pins_default_before_dispatch(rig, monkeypatch):
    rt, gw = rig
    key = rt.create("Historical conversation")["id"]
    install(rt, key)
    assert project(rt, key, ingest(rt, key))["status"] == "accepted"
    recorded(rt, gw, {})
    before = rt.store.info(key)
    monkeypatch.setenv("TZ", "America/New_York")
    first, wire = start(rt, key, "What was site capacity on 1 July 2021?")
    assert "America/New_York" in json.dumps(wire["input"])
    # Restart/config changes cannot reinterpret this already-dispatched work.
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    reply(rt, proposal(day_command("2021-07-01")))
    assert rt.conversations.ask.tick()
    result = execute(rt, key)
    assert result["query"]["effective_from"] == "2021-07-01T04:00:00Z"
    assert result["result"]["value"]["value"] == 10
    assert rt.conversations.ask.tick()
    narration(rt, work(rt, key, first["id"]))
    answer = rt.interactions.get(key, first["id"])
    assert answer["outcome_label"] == "Model answer: 10 places · Historical evidence"
    assert answer["outcome"]["binding"] == result["result"]["binding"]
    assert work(rt, key, first["id"])["packet"]["temporal_resolution"]["timezone"] == "America/New_York"
    second, wire = start(rt, key, "And on 1 July 2027?", reply_to=first["id"])
    assert first["text"] in json.dumps(wire["input"])
    reply(rt, proposal(day_command("2027-07-01")))
    assert rt.conversations.ask.tick()
    result = execute(rt, key)
    assert result["status"] == "needs_input" and result["result"] is None
    assert result["query"]["effective_from"] == "2027-06-30T15:00:00Z"
    assert rt.conversations.ask.tick()
    narration(rt, work(rt, key, second["id"]))
    answer = rt.interactions.get(key, second["id"])
    assert answer["request_id"] and answer["outcome"]["status"] == "needs_input"
    assert "no supported answer" in readable(answer["outcome"])
    assert rt.store.info(key) == before
    assert rt.learning.usage()["calls"] == 4
