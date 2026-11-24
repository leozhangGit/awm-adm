"""Offline Teach→Ask: subject knowledge is queryable apart from its provenance."""

from copy import deepcopy

from awm_adm.runtime.protocol import dumps
from awm_adm.teaching.provider_format import TEMPORAL_PROFILE
from awm_adm.temporal_evidence.models import Catalog

from .interaction_support import narration, proposal, reply, respond, uploaded
from .temporal_support import cell
from .test_application import app_runtime as app_runtime
from .test_application import execute
from .test_direct_ask import recorded, work
from .test_direct_teach import finish_explanation, has_ready, pump
from .test_learning_service import rig as rig


def test_teach_event_and_supplied_calculation_then_recall_without_inspection_date(rig):
    rt, gateway = rig
    key = rt.create("Archive notebook")["id"]
    recorded(rt, gateway, {})
    original = (
        "The register, issued at 09:00 UTC on 14 May 2004, reports the gallery opening on 12 May 2004 (UTC calendar date).\n"
        "The archivist recorded an earlier calculation of 9 calendar days between two register dates.\n"
        "These two records were inspected at 10:00 UTC on 3 February 2026; the calculation was recorded then."
    )
    evidence = uploaded(rt, key, name="register.md", content=original)
    item = rt.interactions.submit(
        key,
        "teach",
        {
            "text": "Remember the reported opening date and the archivist's earlier calculation. For the count use whole calendar days from 0 through 31. Preserve their provenance.",
            "attachments": [evidence["id"]],
        },
    )
    task = rt.conversations.teaching.get(key, item["id"])
    material_id = next(e["id"] for e in task["material_manifest"]["entries"] if e["kind"] == "upload")
    event_scope = cell("occurrence", "2004-05-12T00:00:00Z", "2004-05-13T00:00:00Z", precision="day")
    recording_scope = cell(start="2026-02-03T10:00:00Z")
    p = Catalog.model_validate(
        {
            "namespace": "archive",
            "entities": ["gallery", "comparison"],
            "predicates": [
                {
                    "symbol": "gallery.opened",
                    "kind": "boolean",
                    "unit": "unitless",
                    "meaning": "The register reports that the gallery opened within the subject scope",
                    "scope_kinds": ["occurrence"],
                    "statement_level": "reported",
                    "actor": "Register",
                    "modality": "reported",
                },
                {
                    "symbol": "comparison.recorded_difference",
                    "kind": "integer",
                    "minimum": 0,
                    "maximum": 31,
                    "unit": "calendar days",
                    "meaning": "The archivist's earlier calendar-day calculation, retained as a supplied result, not an ADM derivation",
                    "scope_kinds": ["instant"],
                    "qualifiers": [{"name": "calculator", "value": "archivist"}],
                },
            ],
            "cells": [event_scope, recording_scope],
        }
    ).model_dump()
    prepared = {
        "profile": TEMPORAL_PROFILE,
        "status": "ready",
        "message": "Recall the reported event scope and the supplied calculation separately.",
        "plan": {
            "kind": "facts",
            "summary": "Reported opening date and earlier calculated count, with separate observation times",
            "types": [],
            "aliases": [],
            "parameters": [],
            "value_aliases": [],
            "requirements_json": None,
            "evidence_scope": p,
            "children": [
                {
                    "kind": "facts",
                    "objective": "Keep the event and earlier calculation queryable with attribution",
                    "input_ids": [i["id"] for i in task["inputs"]],
                    "interfaces": [],
                    "material": {"material_ids": [material_id]},
                }
            ],
        },
    }
    assert rt.conversations.teaching.tick()
    respond(rt, prepared)
    pump(rt, key, item["id"], lambda _: has_ready(rt))
    anchor = {**recording_scope, "kind": "exact"}
    claims = []
    for i, value in enumerate((True, 9)):
        pred = p["predicates"][i]
        claims.append(
            {
                "entity_id": p["entities"][i],
                "predicate": pred["symbol"],
                "value": {"kind": pred["kind"], "value": value},
                "unit": pred["unit"],
                "temporal_scope": p["cells"][i],
                "observed_time": anchor,
                "reported_time": {**cell(start="2004-05-14T09:00:00Z"), "kind": "exact"}
                if i == 0
                else {"kind": "unknown"},
                "assertion_kind": "assertion",
                "start_byte": 0,
                "end_byte": len(original.encode()),
            }
        )
    reply(rt, {"claims": claims})
    completion = finish_explanation(rt, key, item["id"])
    assert completion["status"] == "succeeded", completion
    accepted = rt.store.snapshot(key)
    assert len(rt.store.info(key)["theory_version"]) > 0
    assert rt.learning.usage()["calls"] == 3
    questions = (
        "When did the gallery open according to the register?",
        "What calendar-day difference did the archivist record?",
    )
    for i, text in enumerate(questions):
        ask = rt.interactions.submit(key, "ask", {"text": text})
        assert rt.conversations.ask.tick()
        query = {
            "op": "recall_evidence",
            "selectors": [{"entity_id": p["entities"][i], "predicate": p["predicates"][i]["symbol"]}],
        }
        reply(rt, proposal("recall evidence with " + dumps(query).decode()))
        assert rt.conversations.ask.tick()
        result = execute(rt, key)
        assert result["status"] == "succeeded", result
        body = result["result"]["value"]
        assert body["scope"]["complete"] is True and "value" not in body
        row = body["items"][0]
        assert row["value"] == (True if i == 0 else 9)
        assert row["unit"] == ("unitless" if i == 0 else "calendar days")
        assert row["scope"] == (event_scope if i == 0 else recording_scope)
        assert row["observed_time"] == anchor
        assert row["reported_time"]["kind"] == ("exact" if i == 0 else "unknown")
        if i == 0:
            assert row["reported_time"]["effective_from"] == "2004-05-14T09:00:00Z"
        assert row["attribution"]["actor"] == ("Register" if i == 0 else None)
        assert [c["claim"] for c in body["assurance"]["claims"]] == ["accepted_collection"]
        assert rt.conversations.ask.tick()
        w = work(rt, key, ask["id"])
        packet = w["packet"]
        assert packet["outcome"]["values"]["items"] == body["items"]
        narration(rt, w)
        visible = rt.interactions.get(key, ask["id"])
        assert visible["status"] == "completed" and visible["result_id"] == result["result"]["result_id"]
        assert "not a new calculation" in visible["outcome_text"]
    assert rt.store.snapshot(key) == accepted
    assert rt.learning.usage()["calls"] == 7


def test_old_observation_only_meaning_is_not_promoted_to_a_typed_subject_answer(rig):
    from .temporal_support import catalog, fact
    from .test_evidence_recall import recall
    from .test_sources import ingest, install, project

    rt, _ = rig
    key = rt.create("Preserved reading record")["id"]
    p = catalog()
    p["predicates"][0].update(
        kind="boolean",
        meaning="The reader saw a statement that a gallery opened on 12 May 2004.",
        unit="unitless",
    )
    install(rt, key, projection=p)
    f = deepcopy(fact())
    f.update(value={"kind": "boolean", "value": True}, unit="unitless")
    assert project(rt, key, ingest(rt, key, [f]))["status"] == "accepted"
    before = rt.store.snapshot(key)
    row = recall(rt, key)["result"]["value"]["items"][0]
    assert row["value"] is True
    assert row["scope"] == p["cells"][0]  # Retains the reading's 2026 time, not the prose's 2004 date.
    assert "2004" in row["meaning"]
    assert "subject_value" not in row and "date" not in row
    assert rt.store.snapshot(key) == before
