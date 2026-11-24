"""Synthetic regressions for service-owned evidence and explicit Teach lineage."""

import copy

import pytest

from awm_adm.runtime.protocol import RuntimeFault, dumps, loads
from awm_adm.teaching.provider_format import SHARED_PROFILE

from .interaction_support import reply, respond, uploaded
from .teaching_wire import native_reply
from .test_application import app_runtime as app_runtime
from .test_direct_ask import recorded
from .test_direct_teach import finish_explanation, has_ready, pump
from .test_learning_service import rig as rig
from .test_sources import fact, lookup, profile


def facts_reply(task, ids, projection=None):
    value = native_reply(
        {
            "status": "ready",
            "message": "The supplied scope is clear.",
            "plan_json": dumps(
                {
                    "kind": "facts",
                    "summary": "Retain the supplied observations",
                    "children": [
                        {
                            "kind": "facts",
                            "objective": "Learn dated observations",
                            "input_ids": [i["id"] for i in task["inputs"]],
                            "interfaces": {},
                            "material": {"projection": projection or profile(), "sources": []},
                        }
                    ],
                }
            ).decode(),
        }
    )
    value["profile"] = SHARED_PROFILE
    value["plan"]["source_projection"] = value["plan"]["children"][0]["material"].pop("projection")
    value["plan"]["children"][0]["material"].pop("sources")
    value["plan"]["children"][0]["material"]["material_ids"] = ids
    return value


@pytest.mark.parametrize("mixed", [False, True])
def test_linked_originals_admit_without_ingesting_instruction_reply(rig, mixed):
    rt, gw = rig
    key = rt.create("Dated observations")["id"]
    recorded(rt, gw, {})
    first = clarification(rt, key, "The site had capacity 10 places in 2020 through 2023.")
    text = "The site had capacity 12 places in 2024 through 2025."
    attachment = uploaded(rt, key, content=text) if mixed else None
    second = rt.interactions.submit(
        key,
        "teach",
        {
            "text": "Also use this file." if mixed else text,
            "attachments": [attachment["id"]] if attachment else [],
            "reply_to": first["id"],
        },
    )
    assert rt.conversations.teaching.tick()
    respond(
        rt, {"status": "needs_clarification", "message": "Which finite numeric range?", "plan_json": None}
    )
    final = rt.interactions.submit(
        key, "teach", {"text": "Use whole numbers 0–20 places.", "reply_to": second["id"]}
    )
    task = rt.conversations.teaching.get(key, final["id"])
    entries = task["material_manifest"]["entries"]
    ids = [
        entries[0]["id"],
        next(e["id"] for e in entries if e["kind"] == "upload") if mixed else entries[1]["id"],
    ]
    assert rt.conversations.teaching.tick()
    respond(rt, facts_reply(task, ids))
    current = rt.conversations.teaching.get(key, final["id"])
    assert current["status"] == "queued", current
    pump(rt, key, final["id"], lambda _: has_ready(rt))
    originals = rt.sources.versions(key)
    packet = next(s for s in originals if s["content"].startswith("ADM selected material /1\n"))
    from awm_adm.sources.bundles import references

    # One immutable packet contains the original observations, selected upload,
    # and related meaning/bounds replies. Ordinary extraction still checks spans.
    assert final["text"] in packet["content"]
    assert len(references(packet["content"])) == (4 if mixed else 3)
    reply(
        rt,
        {
            "claims": [
                {**claim, "start_byte": 0, "end_byte": len(packet["content"].encode())}
                for claim in (fact(10), fact(12, 2024, 2026))
            ]
        },
    )
    done = finish_explanation(rt, key, final["id"])
    assert done["status"] == "succeeded", done
    originals = rt.sources.versions(key)
    assert {first["inputs"][0]["text"], text, final["text"]} <= {s["content"] for s in originals}
    assert len(originals) == (5 if mixed else 4)
    assert lookup(rt, key, 2021)["result"]["value"]["value"] == 10
    assert lookup(rt, key, 2025)["result"]["value"]["value"] == 12
    assert lookup(rt, key, 2027)["status"] == "needs_input"
    with rt.store.db(key) as db:
        episodes = [loads(r[0]) for r in db.execute("SELECT data FROM source_episodes")]
    assert all(e["review_authority"] == "automatic_teach" for e in episodes)
    imported = rt.create("Checked evidence copy", snapshot=rt.store.revision(key)["snapshot"])["id"]
    assert lookup(rt, imported, 2021)["result"]["value"]["value"] == 10
    assert lookup(rt, imported, 2025)["result"]["value"]["value"] == 12
    assert lookup(rt, imported, 2027)["status"] == "needs_input"
    next_work = rt.interactions.submit(
        key, "teach", {"text": "A separate teaching objective.", "reply_to": final["id"]}
    )
    assert len(rt.conversations.teaching.get(key, next_work["id"])["inputs"]) == 1


@pytest.mark.parametrize("bad", ["unknown", "duplicate", "foreign", "unselected", "unit", "entity"])
def test_invalid_provider_material_is_failure_not_user_question(rig, bad):
    rt, gw = rig
    key = rt.create("Bound material")["id"]
    other = rt.create("Unrelated material")["id"]
    recorded(rt, gw, {})
    unused = uploaded(rt, key)
    foreign = uploaded(rt, other)
    item = rt.interactions.submit(key, "teach", {"text": "A supplied dated observation."})
    task = rt.conversations.teaching.get(key, item["id"])
    material_id = task["material_manifest"]["entries"][0]["id"]
    value = facts_reply(task, [material_id])
    material = value["plan"]["children"][0]["material"]
    if bad == "unknown":
        material["material_ids"] = ["invented"]
    if bad == "duplicate":
        material["material_ids"] = [material_id, material_id]
    if bad == "foreign":
        material["material_ids"] = ["upload_" + foreign["id"]]
    if bad == "unselected":
        material["material_ids"] = ["upload_" + unused["id"]]
    if bad == "unit":
        value["plan"]["source_projection"]["predicates"][0]["unit"] = ""
    if bad == "entity":
        value["plan"]["source_projection"]["entities"] = ["a display name"]
    before = rt.store.info(key)["revision_id"]
    assert rt.conversations.teaching.tick()
    respond(rt, value)
    failed = rt.interactions.get(key, item["id"])
    assert failed["status"] == "failed"
    assert failed["failure_code"] == "invalid_preparation"
    assert failed["failure_diagnostics"]["stage"] == ("sources" if bad in {"unit", "entity"} else "materials")
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM chat_questions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM source_versions").fetchone()[0] == 0
    assert rt.store.info(key)["revision_id"] == before
    assert rt.learning.claim() is None
    assert rt.learning.usage()["calls"] == 1


def test_manifest_revalidation_detects_changed_digest_and_retains_failed_spec(rig):
    rt, gw = rig
    key = rt.create("Recheck")["id"]
    recorded(rt, gw, {})
    item = rt.interactions.submit(key, "teach", {"text": "A supplied dated observation."})
    task = rt.conversations.teaching.get(key, item["id"])
    assert rt.conversations.teaching.tick()
    altered = copy.deepcopy(task)
    altered["material_manifest"]["entries"][0]["content_digest"] = "sha256:" + "0" * 64
    with rt.store.db(key) as db:
        rt.conversations.teaching.save(db, altered)
    respond(rt, facts_reply(task, [task["material_manifest"]["entries"][0]["id"]]))
    failed = rt.conversations.teaching.get(key, item["id"])
    assert failed["status"] == "failed" and failed["specification"] is None
    assert failed["failed_specification"]["children"][0]["material_ids"]
    assert failed["failure_diagnostics"]["code"] == "manifest_mismatch"


def test_lineage_limit_does_not_silently_drop_original_inputs(rig):
    rt, gw = rig
    key = rt.create("Bounded context")["id"]
    recorded(rt, gw, {})
    task = clarification(rt, key, "Retain this original observation.", status="unsupported")
    for _ in range(3):
        task = clarification(rt, key, "More supplied meaning.", reply_to=task["id"], status="unsupported")
    with pytest.raises(RuntimeFault, match="restate"):
        rt.interactions.submit(key, "teach", {"text": "One more detail", "reply_to": task["id"]})
    assert len(rt.conversations.teaching.get(key, task["id"])["inputs"]) == 4


def test_restart_preserves_lineage_and_new_request_does_not_inherit_it(rig):
    from awm_adm.runtime.service import Runtime

    rt, gw = rig
    key = rt.create("Restarted context")["id"]
    recorded(rt, gw, {})
    prior = clarification(rt, key, "An original observation that needs a finite carrier.")
    usage = rt.learning.usage()
    rt.close()
    restored = Runtime(rt.config, start_scheduler=False)
    try:
        item = restored.interactions.submit(
            key, "teach", {"text": "Use integers 0–20.", "reply_to": prior["id"]}
        )
        current = restored.conversations.teaching.get(key, item["id"])
        assert current["material_manifest"]["entries"][0] == prior["material_manifest"]["entries"][0]
        assert restored.learning.usage() == usage
        independent = restored.interactions.submit(key, "teach", {"text": "A different rule."})
        assert len(restored.conversations.teaching.get(key, independent["id"])["inputs"]) == 1
        restored.interactions.cancel(key, item["id"], "local")
        later = restored.interactions.submit(
            key, "teach", {"text": "New intended work.", "reply_to": item["id"]}
        )
        assert len(restored.conversations.teaching.get(key, later["id"])["inputs"]) == 1
    finally:
        restored.close()


def test_current_wire_contract_is_closed_published_and_model_neutral():
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator

    from awm_adm.providers.wire import make_wire
    from awm_adm.teaching.prompt import specification
    from awm_adm.teaching.provider_format import response_schema

    schema = response_schema(material_refs=True)
    assert schema == json.loads(
        (Path(__file__).parents[1] / "contracts/teaching-material-reply.schema.json").read_text()
    )
    Draft202012Validator.check_schema(schema)
    spec = specification(
        {"objective": "Supplied observations", "inputs": [], "material_manifest": {"entries": []}}, {}, {}, {}
    )
    assert spec["prompt_version"] == "adm-teaching-preparation/16"
    assert response_schema(shared_projection=True) == json.loads(
        (Path(__file__).parents[1] / "contracts/teaching-shared-reply.schema.json").read_text()
    )
    wires = []
    for model in ("configured-a", "configured-b"):
        raw, _ = make_wire(
            {"provider": "openai", "model": model, "capabilities": ["json_schema"]}, spec, 8192
        )
        wire = json.loads(raw)
        wire.pop("model")
        wires.append(wire)
    assert wires[0] == wires[1]


def test_uncertain_preparation_is_not_replayed_as_continuation(rig):
    rt, gw = rig
    key = rt.create("Uncertain preparation")["id"]
    recorded(rt, gw, {})
    first = rt.interactions.submit(key, "teach", {"text": "Original factual material."})
    assert rt.conversations.teaching.tick()
    job = rt.learning.claim()
    rt.learning.authorize(job["grant_id"], job["lease"])
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {"status": "outcome_unknown", "error": "timeout", "usage": None, "text": None},
    )
    assert rt.conversations.teaching.tick()
    later = rt.interactions.submit(key, "teach", {"text": "An explicit new task.", "reply_to": first["id"]})
    task = rt.conversations.teaching.get(key, later["id"])
    assert len(task["inputs"]) == 1 and task["previous_task_id"] is None
    with rt.store.db() as db:
        assert (
            db.execute("SELECT status FROM grants WHERE id=?", (job["grant_id"],)).fetchone()[0]
            == "outcome_unknown"
        )


def test_reselected_upload_discloses_original_once_and_keeps_both_input_links(rig):
    rt, gw = rig
    key = rt.create("Retained file")["id"]
    recorded(rt, gw, {})
    meta = uploaded(rt, key)
    first = rt.interactions.submit(key, "teach", {"text": "Learn this record.", "attachments": [meta["id"]]})
    assert rt.conversations.teaching.tick()
    respond(rt, {"status": "needs_clarification", "message": "Which finite carrier?", "plan_json": None})
    second = rt.interactions.submit(
        key, "teach", {"text": "Use integers 0–20.", "attachments": [meta["id"]], "reply_to": first["id"]}
    )
    task = rt.conversations.teaching.get(key, second["id"])
    uploads = [e for e in task["material_manifest"]["entries"] if e["kind"] == "upload"]
    assert len(uploads) == 1 and len(uploads[0]["input_ids"]) == 2
    disclosed = rt.conversations.intake.disclosed(key, task)
    assert len(disclosed) == 1 and disclosed[0]["material_id"] == uploads[0]["id"]


def clarification(rt, key, text, *, reply_to=None, status="needs_clarification"):
    item = rt.interactions.submit(key, "teach", {"text": text, "reply_to": reply_to})
    assert rt.conversations.teaching.tick()
    respond(rt, {"status": status, "message": "Which finite carrier is intended?", "plan_json": None})
    return rt.conversations.teaching.get(key, item["id"])


def test_answered_question_branch_retains_original_meaning(rig):
    rt, gw = rig
    key = rt.create("Materials branch")["id"]
    recorded(rt, gw, {})
    first = clarification(rt, key, "The instrument reading was 7. Learn this observation.")
    clarification(rt, key, "Use an unbounded carrier", reply_to=first["id"], status="unsupported")
    final = rt.interactions.submit(
        key, "teach", {"text": "Use whole numbers 0 through 20, unit counts.", "reply_to": first["id"]}
    )
    task = rt.conversations.teaching.get(key, final["id"])
    assert [i["text"] for i in task["inputs"]] == [first["inputs"][0]["text"], final["text"]]
    assert task["previous_task_id"] == first["id"]
    assert task["material_manifest"]["lineage_id"] == first["id"]
    assert task["material_manifest"]["entries"][0] == first["material_manifest"]["entries"][0]


def test_pasted_inputs_have_service_owned_stable_originals(rig):
    rt, gw = rig
    key = rt.create("Exact originals")["id"]
    recorded(rt, gw, {})
    first = clarification(rt, key, "Reading: 7 µm.\nCitation: https://example.org/report\n")
    item = rt.interactions.submit(
        key, "teach", {"text": "Use integers 0–20 µm.", "reply_to": first["id"], "idempotency_key": "again"}
    )
    task = rt.conversations.teaching.get(key, item["id"])
    entries = task["material_manifest"]["entries"]
    assert len(entries) == 2
    assert len({e["source_id"] for e in entries}) == 1
    assert len({e["item_id"] for e in entries}) == 2
    assert entries[0]["origin"] == f"conversation:{first['conversation_id']}/turn:{first['inputs'][0]['id']}"
    assert entries[0]["byte_count"] == len(first["inputs"][0]["text"].encode())
    again = rt.interactions.submit(
        key, "teach", {"text": "Use integers 0–20 µm.", "reply_to": first["id"], "idempotency_key": "again"}
    )
    assert again["id"] == item["id"]
    assert dumps(rt.conversations.teaching.get(key, item["id"])["material_manifest"]) == dumps(
        task["material_manifest"]
    )
