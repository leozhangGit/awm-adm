"""Accepted evidence recall across domains, with no provider or core exceptions."""

from copy import deepcopy
from uuid import uuid4

import pytest

from awm_adm.conversations.history import parse
from awm_adm.conversations.presentation import outcome, packet, readable
from awm_adm.runtime.protocol import dumps
from awm_adm.temporal_evidence.types import RecallQuery

from .interaction_support import proposal
from .temporal_support import catalog, cell, fact
from .test_application import app_runtime as app_runtime
from .test_application import execute
from .test_sources import ingest, install, project


def recall(rt, key, selectors=None, **kw):
    query = {
        "op": "recall_evidence",
        "selectors": selectors or [{"entity_id": "chamber", "predicate": "chamber.reading"}],
        **kw,
    }
    rt.coordinator.submit(key, {"idempotency_key": str(uuid4()), "query": query})
    return execute(rt, key)


def test_recall_multiple_meanings_keeps_checked_values_units_scopes_and_sources(app_runtime):
    rt = app_runtime
    key = rt.create("Independent measurements")["instance_id"]
    p = catalog()
    install(rt, key, projection=p)
    assert project(rt, key, ingest(rt, key, [fact(i) for i in range(3)]))["status"] == "accepted"
    before = rt.store.snapshot(key)
    selectors = [{"entity_id": p["entities"][i], "predicate": p["predicates"][i]["symbol"]} for i in range(3)]
    result = recall(rt, key, selectors)
    assert result["status"] == "succeeded", result
    value = result["result"]["value"]
    by_predicate = {v["predicate"]: v for v in value["items"]}
    for i, expected in enumerate((7, 3, 14)):
        row = by_predicate[p["predicates"][i]["symbol"]]
        assert row["value"] == expected
        assert row["unit"] == p["predicates"][i]["unit"]
        assert row["scope"] == p["cells"][i]
        assert row["meaning"] == p["predicates"][i]["meaning"]
        assert row["source"]["source_id"] == "records"
        assert row["source"]["start_byte"] < row["source"]["end_byte"]
    assert value["scope"]["complete"] is True
    assert value["scope"]["subject_scope"] is None
    assert value["scope"]["unmatched_selectors"] == []
    assert "value" not in value
    assert [c["claim"] for c in value["assurance"]["claims"]] == ["accepted_collection"]
    assert value["binding"]["query"]["op"] == "recall_evidence"
    assert rt.store.snapshot(key) == before
    assert rt.learning.usage()["calls"] == 0
    # The result/packet expose original references and typed data, never original source bytes.
    disclosed, body = packet({}, result)
    assert disclosed and body["values"]["items"] == value["items"]

    def field_names(node):
        if isinstance(node, dict):
            return set(node) | set().union(*(field_names(v) for v in node.values()))
        if isinstance(node, list):
            return set().union(*(field_names(v) for v in node))
        return set()

    assert not {"content", "excerpt", "source_text"} & field_names(disclosed)
    copy = rt.create("Copied evidence", snapshot=before)["instance_id"]
    assert recall(rt, copy, selectors)["result"]["value"]["items"] == value["items"]


def test_recall_paging_is_bound_to_selector_set_context_and_support(app_runtime):
    rt = app_runtime
    key = rt.create("Observation journal")["instance_id"]
    p = catalog()
    scope = cell("occurrence", "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z", precision="day")
    p["cells"].append(scope)
    install(rt, key, projection=p)
    for v in (7, 9):
        assert (
            project(rt, key, ingest(rt, key, [{**fact(0, v), "temporal_scope": scope}]))["status"]
            == "accepted"
        )
    first = recall(rt, key, limit=1)["result"]["value"]
    cursor = first["scope"]["next_cursor"]
    assert first["scope"]["complete"] is False and cursor
    second = recall(rt, key, limit=1, cursor=cursor)["result"]["value"]
    assert {first["items"][0]["value"], second["items"][0]["value"]} == {7, 9}
    assert second["scope"]["enumeration_complete"] is True
    assert second["scope"]["complete"] is False
    changed = [{"entity_id": "room", "predicate": "room.capacity"}]
    assert recall(rt, key, changed, limit=1, cursor=cursor)["status"] != "succeeded"
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    assert recall(rt, key, limit=1, cursor=cursor)["status"] != "succeeded"


def test_recall_preserves_disagreement_report_time_and_missing_records(app_runtime):
    rt = app_runtime
    key = rt.create("Forecast record")["instance_id"]
    p = catalog()
    p["predicates"][2].update(statement_level="reported", actor="Planner", modality="forecast")
    install(rt, key, projection=p)
    for day, v in ((1, 14), (2, 16)):
        f = {
            **fact(2, v),
            "reported_time": {
                "kind": "exact",
                "effective_from": f"2026-02-0{day}T12:00:00Z",
                "effective_to": None,
                "precision": "second",
                "timezone_basis": "UTC",
            },
        }
        assert project(rt, key, ingest(rt, key, [f]))["status"] == "accepted"
    selectors = [
        {"entity_id": "machine", "predicate": "machine.output"},
        {"entity_id": "room", "predicate": "room.capacity"},
    ]
    result = recall(rt, key, selectors)
    value = result["result"]["value"]
    assert {i["value"] for i in value["items"]} == {14, 16}
    assert len({i["reported_time"]["effective_from"] for i in value["items"]}) == 2
    assert all(
        i["attribution"] == {"statement_level": "reported", "actor": "Planner", "modality": "forecast"}
        for i in value["items"]
    )
    assert value["scope"]["unmatched_selectors"] == [selectors[1]]
    assert "Some requested subjects" in readable(outcome(result))
    assert "value" not in value  # No latest, averaging or scalar consensus rule.


def test_recall_correction_holds_and_legacy_snapshot_do_not_resurrect_support(app_runtime):
    from .test_sources import fact as old_fact

    rt = app_runtime
    key = rt.create("Legacy inventory")["instance_id"]
    install(rt, key)
    source = ingest(rt, key, [old_fact()], item="inventory")
    assert project(rt, key, source)["status"] == "accepted"
    selectors = [{"entity_id": "site", "predicate": "site.capacity"}]
    before = rt.store.snapshot(key)
    item = recall(rt, key, selectors)["result"]["value"]["items"][0]
    assert item["value"] == 10 and item["unit"] == "places"
    assert item["scope"]["precision"] == "legacy"
    assert item["scope"]["timezone_basis"] == "legacy_unrecorded"
    assert rt.store.snapshot(key) == before
    ingest(rt, key, [old_fact(12)], item="inventory", version_id="v2", supersedes_version="v1")
    blocked = recall(rt, key, selectors)
    assert blocked["status"] == "needs_input", blocked
    copy = rt.create("Copy with hold", snapshot=rt.store.snapshot(key))["instance_id"]
    assert recall(rt, copy, selectors)["status"] == "needs_input"


def test_recall_empty_collection_is_not_an_answer_or_proof_of_absence(app_runtime):
    rt = app_runtime
    key = rt.create("Empty configured evidence")["instance_id"]
    install(rt, key, projection=catalog())
    result = recall(rt, key)
    assert result["status"] == "succeeded"
    value = result["result"]["value"]
    assert value["items"] == [] and value["scope"]["complete"] is True
    assert value["scope"]["unmatched_selectors"]
    assert "does not establish that no event occurred" in readable(outcome(result))
    assert "value" not in value


@pytest.mark.parametrize(
    "change",
    [
        {"selectors": []},
        {"selectors": [{"entity_id": "x", "predicate": "x.value"}] * 2},
        {"selectors": [{"entity_id": f"x{i}", "predicate": "x.value"} for i in range(33)]},
        {"limit": 101},
        {"scope": None},
        {"intent": "latest"},
        {"entity_id": "*"},
    ],
)
def test_recall_rejects_unbounded_or_implicit_selection_contract(change):
    query = {"op": "recall_evidence", "selectors": [{"entity_id": "x", "predicate": "x.value"}]}
    with pytest.raises(ValueError):
        RecallQuery.model_validate({**query, **change})


def test_conversation_recall_requires_disclosed_semantic_selectors_without_a_time():
    p = catalog()
    query = {"op": "recall_evidence", "selectors": [{"entity_id": "chamber", "predicate": "chamber.reading"}]}
    original = deepcopy(query)
    parsed = parse(dumps(proposal("recall evidence with " + dumps(query).decode())).decode(), p)
    assert parsed["status"] == "ready" and parsed["query"]["op"] == "recall_evidence"
    assert "scope" not in parsed["query"] and query == original
    query["selectors"][0]["predicate"] = "other.not_disclosed"
    parsed = parse(dumps(proposal("recall evidence with " + dumps(query).decode())).decode(), p)
    assert parsed["status"] == "needs_clarification" and parsed["query"] is None


def test_long_recall_display_retains_abbreviation_notice_without_changing_records():
    from awm_adm.temporal_evidence.conversation import readable as render

    body = {
        "status": "succeeded",
        "values": {
            "items": [
                {"value": i, "unit": "units", "scope": cell(), "attribution": {}, "meaning": "A" * 1000}
                for i in range(40)
            ],
            "scope": {"kind": "accepted_evidence_recall", "complete": False},
        },
    }
    before = deepcopy(body)
    text = render(body, str)
    assert len(text) <= 16000
    assert "omitted from this summary" in text[-300:]
    assert body == before and len(body["values"]["items"]) == 40
