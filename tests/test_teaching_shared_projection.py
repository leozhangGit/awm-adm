"""One explicit provider projection, unchanged evidence/admission boundaries."""

import copy
from uuid import uuid4

import pytest

from awm_adm.engine.budget import Budget
from awm_adm.runtime.protocol import dumps, loads
from awm_adm.teaching import service
from awm_adm.teaching.compute import compute
from awm_adm.teaching.prompt import specification
from awm_adm.teaching.provider_format import MATERIAL_PROFILE, SHARED_PROFILE, response_schema

from .interaction_support import reply, respond, uploaded
from .test_application import app_runtime as app_runtime
from .test_application import execute
from .test_direct_ask import recorded
from .test_direct_teach import finish_explanation, has_ready, pump
from .test_learning_service import rig as rig
from .test_sources import fact, profile
from .test_teaching_format import task as compute_task
from .test_teaching_materials import facts_reply


@pytest.fixture(autouse=True)
def retained_shared_contract(monkeypatch):
    """Exercise retained /9 work through its own contract, not the new producer."""

    def prior(*args):
        spec = specification(*args)
        spec.update(
            prompt_version="adm-teaching-preparation/9", schema=response_schema(shared_projection=True)
        )
        return spec

    monkeypatch.setattr(service, "specification", prior)


def query(rt, key, entity, predicate):
    rt.coordinator.submit(
        key,
        {
            "idempotency_key": str(uuid4()),
            "query": {
                "op": "lookup_fact",
                "entity_id": entity,
                "predicate": predicate,
                "effective_at": "2021-01-01T00:00:00Z",
            },
        },
    )
    return execute(rt, key)


def test_shared_scope_admits_distinct_child_evidence_without_inventing_cross_product_facts(rig):
    rt, gw = rig
    key = rt.create("Mixed supplied observations")["id"]
    recorded(rt, gw, {})
    texts = [
        "The site had 10 places during 2020 through 2023.",
        "Annex access was enabled during 2020 through 2023.",
    ]
    attachments = [
        uploaded(rt, key, name=f"observation-{i}.md", content=text) for i, text in enumerate(texts)
    ]
    item = rt.interactions.submit(
        key,
        "teach",
        {
            "text": "Learn these two supplied observations. Counts use 0–20 places; access is Boolean.",
            "attachments": [a["id"] for a in attachments],
        },
    )
    task = rt.conversations.teaching.get(key, item["id"])
    ids = [e["id"] for e in task["material_manifest"]["entries"] if e["kind"] == "upload"]
    projection = profile()
    projection["entities"].append("annex")
    projection["predicates"].append(
        {
            "symbol": "access.enabled",
            "kind": "boolean",
            "unit": "unitless",
            "minimum": 0,
            "maximum": 100,
            "values": [],
        }
    )
    value = facts_reply(task, [ids[0]], projection)
    child = copy.deepcopy(value["plan"]["children"][0])
    child["objective"] = "Learn the separate access observation"
    child["material"]["material_ids"] = [ids[1]]
    value["plan"]["children"].append(child)
    before = copy.deepcopy(value)
    assert rt.conversations.teaching.tick()
    respond(rt, value)
    assert value == before
    prepared = rt.conversations.teaching.get(key, item["id"])
    assert prepared["status"] == "queued", prepared
    children = prepared["specification"]["children"]
    assert [c["material"]["projection"] for c in children] == [projection, projection]
    assert [c["material_ids"] for c in children] == [[ids[0]], [ids[1]]]
    claims = [
        fact(10),
        fact(
            {"kind": "boolean", "value": True}, entity_id="annex", predicate="access.enabled", unit="unitless"
        ),
    ]
    for text, claim in zip(texts, claims, strict=True):
        pump(rt, key, item["id"], lambda _: has_ready(rt))
        reply(rt, {"claims": [{**claim, "start_byte": 0, "end_byte": len(text.encode())}]})
    done = finish_explanation(rt, key, item["id"])
    assert done["status"] == "succeeded", done
    assert {s["content"] for s in rt.sources.versions(key)} == set(texts)
    with rt.store.db(key) as db:
        accepted = [loads(r[0]) for r in db.execute("SELECT data FROM source_claims WHERE status='accepted'")]
    assert len(accepted) == 2
    for entry in accepted:
        assert entry["excerpt"] in texts
        assert entry["claim"]["unit"] in {"places", "unitless"}
    imported = rt.create("Independent copy", snapshot=rt.store.revision(key)["snapshot"])["id"]
    for model in (key, imported):
        assert query(rt, model, "site", "site.capacity")["result"]["value"]["value"] == 10
        assert query(rt, model, "annex", "access.enabled")["result"]["value"]["value"] is True
        assert query(rt, model, "annex", "site.capacity")["status"] == "needs_input"
        assert query(rt, model, "site", "access.enabled")["status"] == "needs_input"
    assert rt.learning.usage()["calls"] == 4


@pytest.mark.parametrize(
    "bad", ["missing", "child_override", "mixed_time", "grid", "unit", "unselected", "profile"]
)
def test_shared_projection_failures_publish_nothing_and_never_retry(rig, bad):
    rt, gw = rig
    key = rt.create("Invalid shared scope")["id"]
    recorded(rt, gw, {})
    item = rt.interactions.submit(key, "teach", {"text": "One supplied observation."})
    task = rt.conversations.teaching.get(key, item["id"])
    value = facts_reply(task, [task["material_manifest"]["entries"][0]["id"]])
    p = value["plan"]["source_projection"]
    if bad == "missing":
        value["plan"]["source_projection"] = None
    if bad == "child_override":
        value["plan"]["children"][0]["material"]["projection"] = p
    if bad == "mixed_time":
        p["cells"][1].update(kind="point", effective_to=None)
    if bad == "grid":
        p["entities"] = [f"e{i}" for i in range(128)]
        p["predicates"] = [{**p["predicates"][0], "symbol": f"facts.p{i}"} for i in range(32)]
    if bad == "unit":
        p["predicates"][0]["unit"] = ""
    if bad == "unselected":
        value["plan"]["children"][0]["material"]["material_ids"] = ["foreign"]
    if bad == "profile":
        value["profile"] = MATERIAL_PROFILE
    before = rt.store.info(key)
    assert rt.conversations.teaching.tick()
    reply(rt, value)
    assert rt.conversations.tick()
    result = rt.interactions.get(key, item["id"])
    assert result["status"] == "failed" and result["failure_code"] == "invalid_preparation"
    if bad == "missing":
        assert result["failure_diagnostics"]["code"] == "shared_projection_required"
    if bad == "unit":
        assert "source_projection" in result["failure_diagnostics"]["issues"][0]["path"]
    assert rt.store.info(key) == before
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM source_versions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM chat_questions").fetchone()[0] == 0
    for _ in range(3):
        rt.conversations.tick()
    assert rt.learning.claim() is None and rt.learning.usage()["calls"] == 1


@pytest.mark.parametrize("conflicting", [False, True])
def test_previous_format_decodes_and_remains_inspectable_after_restart(rig, monkeypatch, conflicting):
    from awm_adm.runtime.service import Runtime

    def previous(*args):
        spec = specification(*args)
        spec.update(prompt_version="adm-teaching-preparation/8", schema=response_schema(material_refs=True))
        return spec

    monkeypatch.setattr(service, "specification", previous)
    rt, gw = rig
    key = rt.create("Retained preparation")["id"]
    recorded(rt, gw, {})
    item = rt.interactions.submit(key, "teach", {"text": "A supplied observation."})
    task = rt.conversations.teaching.get(key, item["id"])
    value = facts_reply(task, [task["material_manifest"]["entries"][0]["id"]])
    value["profile"] = MATERIAL_PROFILE
    projection = value["plan"].pop("source_projection")
    value["plan"]["children"][0]["material"]["projection"] = projection
    if conflicting:
        child = copy.deepcopy(value["plan"]["children"][0])
        child["material"]["projection"]["namespace"] = "different"
        value["plan"]["children"].append(child)
    assert rt.conversations.teaching.tick()
    before = rt.store.info(key)
    respond(rt, value)
    result = rt.conversations.teaching.get(key, item["id"])
    if conflicting:
        assert result["status"] == "failed"
        assert result["failure_diagnostics"]["code"] == "multiple_projections"
        assert "different evidence mappings" in result["failure_diagnostics"]["message"]
        assert (
            result["failed_specification"]["children"][1]["material"]["projection"]["namespace"]
            == "different"
        )
    else:
        assert result["status"] == "queued", result
    assert rt.store.info(key) == before
    rt.close()
    restored = Runtime(rt.config, start_scheduler=False)
    try:
        retained = restored.conversations.teaching.get(key, item["id"])
        field = "failed_specification" if conflicting else "specification"
        assert retained[field] == result[field]
        assert restored.store.info(key) == before
        assert restored.learning.usage()["calls"] == 1
        assert restored.learning.claim() is None
    finally:
        restored.close()


def test_unused_scope_is_refused_without_changing_capability_meaning():
    from .teaching_wire import shared_reply
    from .test_teaching_format import proposed

    value = shared_reply(proposed(), {"entries": []})
    assert value["plan"]["source_projection"] is None
    task = compute_task(value)
    task["reply_format"] = SHARED_PROFILE
    good = compute(task, Budget(1000000, 5))
    assert "plan" in good
    value["plan"]["source_projection"] = profile()
    task["provider_text"] = dumps(value).decode()
    rejected = compute(task, Budget(1000000, 5))
    assert rejected["failure"]["code"] == "unused_shared_projection"
