"""Mixed ordinary Teach/Ask using independently authored recorded temporal replies."""

import pytest

from awm_adm.runtime.protocol import dumps
from awm_adm.teaching import service
from awm_adm.teaching.prompt import specification
from awm_adm.teaching.provider_format import TEMPORAL_PROFILE, response_schema

from .interaction_support import narration, proposal, reply, respond, uploaded
from .temporal_support import catalog, fact
from .test_application import app_runtime as app_runtime
from .test_application import execute
from .test_direct_ask import recorded, work
from .test_direct_teach import finish_explanation, has_ready, pump
from .test_learning_service import rig as rig


@pytest.mark.parametrize("version", ["10", "11", "12", "14", "16"])
def test_one_original_keeps_mixed_meanings_through_ordinary_teach_and_ask(rig, monkeypatch, version):
    def dispatched_spec(*args):
        spec = specification(*args)
        spec["prompt_version"] = f"adm-teaching-preparation/{version}"
        if version not in {"14", "16"}:
            spec["schema"] = response_schema(temporal_evidence=True)
            spec["instructions"] = "Return the retained temporal reply profile with the recorded plan."

        return spec

    monkeypatch.setattr(service, "specification", dispatched_spec)
    rt, gw = rig
    key = rt.create("Synthetic mixed original")["id"]
    recorded(rt, gw, {})
    lines = [
        "The chamber reading was 7 units at 12:00 UTC on 1 March 2026.",
        "The room capacity was 3 places throughout 1 March to 8 March 2026, end excluded, UTC.",
        "The machine produced 14 items in total for that same week.",
    ]
    original = "\n".join(lines)
    attachment = uploaded(rt, key, name="measurements.md", content=original)
    item = rt.interactions.submit(
        key,
        "teach",
        {
            "text": "Learn these measurements, preserving their time meanings. Whole-number bounds are 0–20 in the stated units.",
            "attachments": [attachment["id"]],
        },
    )
    task = rt.conversations.teaching.get(key, item["id"])
    material = next(e["id"] for e in task["material_manifest"]["entries"] if e["kind"] == "upload")
    wire = {
        "profile": TEMPORAL_PROFILE,
        "status": "ready",
        "message": "Retain three temporal meanings.",
        "plan": {
            "kind": "facts",
            "summary": "Three measurements with their original temporal meaning",
            "types": [],
            "aliases": [],
            "parameters": [],
            "value_aliases": [],
            "requirements_json": None,
            "evidence_scope": catalog(),
            "children": [
                {
                    "kind": "facts",
                    "objective": "Learn the three measurements",
                    "input_ids": [i["id"] for i in task["inputs"]],
                    "interfaces": [],
                    "material": {"material_ids": [material]},
                }
            ],
        },
    }
    assert rt.conversations.teaching.tick()
    respond(rt, wire)
    prepared = rt.conversations.teaching.get(key, item["id"])
    assert prepared["status"] == "queued", prepared
    pump(rt, key, item["id"], lambda _: has_ready(rt))
    claims = []
    for i, line in enumerate(lines):
        start = len(original[: original.index(line)].encode())
        claims.append({**fact(i), "start_byte": start, "end_byte": start + len(line.encode())})
    reply(rt, {"claims": claims})
    completed = finish_explanation(rt, key, item["id"])
    assert completed["status"] == "succeeded", completed
    assert len(rt.sources.versions(key)) == 1
    assert rt.sources.versions(key)[0]["content"] == original
    assert rt.learning.usage()["calls"] == 3  # preparation, one extraction, explanation
    for i, intent in enumerate(("value_at", "value_throughout", "value_for_period")):
        scope = catalog()
        query = {
            "op": "query_evidence",
            "intent": intent,
            "entity_id": scope["entities"][i],
            "predicate": scope["predicates"][i]["symbol"],
            "scope": scope["cells"][i],
        }
        ask = rt.interactions.submit(key, "ask", {"text": "What does the accepted evidence say?"})
        assert rt.conversations.ask.tick()
        reply(rt, proposal("query evidence with " + dumps(query).decode()))
        assert rt.conversations.ask.tick()
        request = execute(rt, key)
        assert request["status"] == "succeeded", request
        assert request["result"]["value"]["value"] == [7, 3, 14][i]
        assert rt.conversations.ask.tick()
        w = work(rt, key, ask["id"])
        meta = w["packet"]["outcome"]["value_metadata"]
        assert meta["intent"] == intent and meta["unit"] == ["units", "places", "items"][i]
        narration(rt, w)
        visible = rt.interactions.get(key, ask["id"])
        assert meta["unit"] in visible["outcome_text"]
        assert visible["status"] == "completed"
    assert rt.learning.usage()["calls"] == 9
