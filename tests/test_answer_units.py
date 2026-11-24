"""Checked historical meaning survives presentation; all providers are recorded."""

import copy
import json

import pytest

from awm_adm.conversations.presentation import outcome, outcome_label, packet, readable, specification
from awm_adm.learning.service import fingerprint
from awm_adm.providers.wire import make_wire

from .interaction_support import narration, proposal
from .test_application import app_runtime as app_runtime
from .test_application import client, execute
from .test_direct_ask import interpreted, recorded, work
from .test_learning_service import rig as rig
from .test_sources import fact, ingest, install, profile, project


@pytest.mark.parametrize("period", [False, True])
@pytest.mark.parametrize("unit,value", [("kilograms", 10), ("percentage points", 0), ("unitless", True)])
def test_checked_units_survive_recorded_ask_http_history_and_fallback(rig, period, unit, value):
    rt, gw = rig
    key = rt.create("Recorded quantities")["id"]
    p = profile()
    p["predicates"][0].update(unit=unit, kind="boolean" if type(value) is bool else "integer")
    start, middle, end = "2021-01-01T00:00:00Z", "2021-01-01T12:00:00Z", "2021-01-02T00:00:00Z"
    p["cells"] = (
        [
            {"kind": "interval", "granularity": "second", "effective_from": left, "effective_to": right}
            for left, right in [(start, middle), (middle, end)]
        ]
        if period
        else [{"kind": "point", "granularity": "second", "effective_from": start, "effective_to": None}]
    )
    install(rt, key, projection=p)
    typed = {"kind": "boolean" if type(value) is bool else "integer", "value": value}
    facts = [fact(typed, unit=unit, temporal_scope=cell) for cell in p["cells"]]
    assert project(rt, key, ingest(rt, key, facts))["status"] == "accepted"
    before = rt.store.info(key)
    query = {"entity_id": "site", "predicate": "site.capacity"}
    if period:
        query.update(effective_on="2021-01-01", timezone="UTC")
        expected_scope = {"kind": "interval", "effective_from": start, "effective_to": end}
    else:
        query["effective_at"] = "2021-01-01T00:00:00Z"
        expected_scope = {"kind": "point", "effective_at": query["effective_at"]}
    recorded(rt, gw, proposal("lookup fact with " + json.dumps(query)))
    # Neither vocabulary nor user wording can override the checked unit or scale.
    item = interpreted(rt, gw, key, "What was recorded? Please call the units something else.")
    request = execute(rt, key)
    assert request["status"] == "succeeded"
    saved = copy.deepcopy(request)
    assert rt.conversations.ask.tick()
    w = work(rt, key, item["id"])
    value_packet = w["packet"]
    assert value_packet["outcome"]["value_metadata"] == {"unit": unit, "query_scope": expected_scope}
    assert value_packet["outcome_digest"] == fingerprint(request["result"])
    assert value_packet["outcome"]["binding"] == request["result"]["binding"]
    assert request == saved
    assert "source_id" not in json.dumps(value_packet) and "start_byte" not in json.dumps(value_packet)
    rendered = "Yes" if value is True else str(value)
    explanation = f"The recorded value was {rendered} {unit}."
    if period:
        # A failed explanation still leaves the independently rendered unit visible.
        narration(rt, w, packet_digest="sha256:" + "0" * 64)
    else:
        narration(rt, w, explanation=explanation)
    http = client(rt)
    path = f"/api/v1/adms/{key}"
    result = http.get(path + "/interactions/" + item["id"]).json()
    assert result["outcome_label"] == f"Model answer: {rendered} {unit} · Historical evidence"
    assert result["outcome_text"].startswith(f"Model answer: {rendered} {unit}.")
    assert result["explanation"] == (None if period else explanation)
    assert http.get(path + "/chat/ask").json()["items"][0] == result
    assert rt.store.info(key) == before and rt.learning.usage()["calls"] == 2
    # Retained history and packet stay immutable; reopening does not regenerate narration.
    from awm_adm.runtime.service import Runtime

    rt.close()
    restored = Runtime(rt.config, start_scheduler=False)
    try:
        assert restored.interactions.get(key, item["id"]) == result
        assert restored.learning.usage()["calls"] == 2
    finally:
        restored.close()


@pytest.mark.parametrize("period", [False, True])
@pytest.mark.parametrize("case", ["missing", "disputed"])
def test_unknown_or_disputed_history_cannot_present_an_observed_unit(app_runtime, period, case):
    rt = app_runtime
    key = rt.create("Unresolved observations")["id"]
    install(rt, key)
    original = ingest(rt, key)
    assert project(rt, key, original)["status"] == "accepted"
    if case == "disputed":
        ingest(rt, key, item=original["item_id"], version_id="v2", supersedes_version="v1")
    year = 2027 if case == "missing" else 2021
    q = {
        "op": "lookup_fact",
        "entity_id": "site",
        "predicate": "site.capacity",
        "effective_at": f"{year}-01-01T00:00:00Z",
    }
    if period:
        q.update(
            op="lookup_fact_period",
            effective_from=q.pop("effective_at"),
            effective_to=f"{year}-02-01T00:00:00Z",
        )
    rt.coordinator.submit(key, {"idempotency_key": "unknown-unit", "query": q})
    request = execute(rt, key)
    assert request["status"] == "needs_input"
    value_packet, body = packet({}, request)
    assert "value_metadata" not in body and outcome_label(body) is None
    assert "places" not in readable(body)
    assert value_packet["outcome"] == body


def test_missing_or_inconsistent_legacy_units_are_not_inferred_and_packet_stays_bounded():
    request = {
        "request_id": "request",
        "status": "succeeded",
        "query": {
            "op": "lookup_fact_period",
            "effective_from": "2020-01-01T00:00:00Z",
            "effective_to": "2021-01-01T00:00:00Z",
        },
        "result": {
            "result_id": "result",
            "value": {"value": 10},
            "binding": {},
            "claims": ["value"],
            "lean_kernel": "not_requested",
            "exhaustive_finite": "not_checked",
            "empirical_fidelity": "not_established",
        },
    }
    for facts in (
        [],
        [{"claim": {"unit": "kg"}}, {"claim": {"unit": "g"}}],
        [{"claim": {"unit": "x" * 101}}],
    ):
        request["result"]["value"]["facts"] = facts
        body = outcome(request)
        assert body["value_metadata"]["unit"] is None
        assert outcome_label(body) == "Model answer: 10 · Historical evidence"
    request["result"]["value"]["facts"] = [{"claim": {"unit": "kg"}}]
    value_packet, body = packet({}, request, question="x" * 33000)
    assert value_packet is None and readable(body).startswith("Model answer: 10 kg.")
    # A saved older outcome without metadata is readable and is not reinterpreted.
    body.pop("value_metadata")
    before = copy.deepcopy(body)
    assert outcome_label(body) == "Model answer: 10 · Historical evidence"
    assert body == before


def test_unit_guidance_is_model_neutral_with_unchanged_reply_schema():
    spec = specification({"outcome": {"value_metadata": {"unit": None}}})
    wires = [
        json.loads(
            make_wire({"provider": "openai", "model": m, "capabilities": ["json_schema"]}, spec, 4096)[0]
        )
        for m in ("configured-one", "configured-two")
    ]
    for wire in wires:
        wire.pop("model")
    assert wires[0] == wires[1]
    assert spec["prompt_version"] == "adm-ask-explanation/5"
    assert "does not mean the value is" in spec["instructions"]
    assert list(spec["schema"]["properties"]) == [
        "packet_digest",
        "outcome_digest",
        "status",
        "claim_ids",
        "support_ids",
        "explanation",
        "authority",
    ]
