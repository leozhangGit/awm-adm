"""Related material, timing and diagnostics through the existing local validators."""

import base64
import json
from uuid import uuid4

import pytest

from awm_adm.runtime.protocol import RuntimeFault, loads
from awm_adm.sources.bundles import PREFIX, references

from .interaction_support import reply, respond, uploaded
from .test_application import app_runtime as app_runtime
from .test_direct_ask import recorded
from .test_direct_teach import finish_explanation, has_ready, pump
from .test_learning_service import rig as rig
from .test_sources import fact, ingest, install, lookup
from .test_teaching_materials import clarification, facts_reply


def continued(rt, gw, *, file=False):
    key = rt.create("Clarified supplied knowledge")["id"]
    recorded(rt, gw, {})
    unused = uploaded(rt, key, content="Unselected secret fixture; never disclose.")
    first = clarification(rt, key, "The café had capacity 10 places; I will specify the period.")
    data = uploaded(rt, key, content="The café had capacity 10 places.") if file else None
    follow = rt.interactions.submit(
        key,
        "teach",
        {
            "text": "The observation covers 2020 through 2023; use whole numbers 0–20 places.",
            "reply_to": first["id"],
            "attachments": [data["id"]] if data else [],
        },
    )
    task = rt.conversations.teaching.get(key, follow["id"])
    selected = [
        e["id"]
        for e in task["material_manifest"]["entries"]
        if e["kind"] == "upload" or e["id"] == "text_" + first["inputs"][0]["id"]
    ]
    assert rt.conversations.teaching.tick()
    respond(rt, facts_reply(task, selected))
    pump(rt, key, task["id"], lambda _: has_ready(rt))
    with rt.store.db() as db:
        grant = loads(db.execute("SELECT body FROM grants WHERE status='ready'").fetchone()[0])
    wire = json.loads(base64.b64decode(grant["wire"]))
    context = json.loads(wire["input"][0]["content"])
    packet = context["source"]["content"]
    assert first["inputs"][0]["text"] in packet and follow["text"] in packet
    assert unused["content_digest"] not in packet and "Unselected secret fixture" not in packet
    assert references(packet)
    return key, task["id"], packet, data


@pytest.mark.parametrize("file", [False, True])
def test_joint_context_keeps_exact_originals_and_corrections_hold_snapshot_support(rig, file):
    rt, gw = rig
    key, uid, packet, data = continued(rt, gw, file=file)
    reply(rt, {"claims": [{**fact(), "start_byte": 0, "end_byte": len(packet.encode())}]})
    done = finish_explanation(rt, key, uid)
    assert done["status"] == "succeeded", done["execution"]["summary"]
    assert lookup(rt, key, 2021)["result"]["value"]["value"] == 10
    copied = rt.create("Snapshot retains original context", snapshot=rt.store.revision(key)["snapshot"])["id"]
    assert lookup(rt, copied, 2021)["result"]["value"]["value"] == 10
    sources = rt.sources.versions(key)
    original = (
        next(s for s in sources if s["record"]["media_type"] == "text/markdown")
        if file
        else next(s for s in sources if s["content"].startswith("The café"))
    )
    body = {
        k: original["record"][k]
        for k in ("source_id", "item_id", "version_id", "media_type", "origin", "supersedes_version")
    }
    body["content"] = original["content"]
    rt.sources.ingest(copied, {"idempotency_key": "original", "items": [body]})
    replacement = {
        **body,
        "version_id": "v2",
        "supersedes_version": body["version_id"],
        "content": "This observation is withdrawn.",
    }
    for model in (key, copied):
        rt.sources.ingest(model, {"idempotency_key": "correction", "items": [replacement]})
        assert lookup(rt, model, 2021)["status"] == "needs_input"
    assert rt.conversations.teaching.get(key, uid)["execution"]["summary"]["status"] == "succeeded"


def test_packet_span_validation_and_byte_limits_are_not_relaxed(rig):
    rt, gw = rig
    key, uid, packet, _ = continued(rt, gw)
    reply(rt, {"claims": [{**fact(), "start_byte": 0, "end_byte": len(packet.encode()) + 1}]})
    done = finish_explanation(rt, key, uid)
    assert done["status"] == "failed"
    assert lookup(rt, key, 2021)["status"] == "needs_input"
    assert not rt.sources.overview(key)["claims"]
    assert references(packet.replace("café", "cafe", 1)) == []
    header, payload = packet[len(PREFIX) :].split("\n\n", 1)
    malformed = json.loads(header)
    malformed["parts"][0]["source_id"] = ["not-a-source-identity"]
    assert references(PREFIX + json.dumps(malformed) + "\n\n" + payload) == []


def test_superseded_original_prevents_packet_reprocessing_and_new_projection(rig):
    rt, gw = rig
    key, _, packet, _ = continued(rt, gw)
    reply(rt, {"claims": [{**fact(), "start_byte": 0, "end_byte": len(packet.encode())}]})
    assert rt.sources.tick()
    overview = rt.sources.overview(key)
    job = overview["jobs"][0]
    claims = overview["claims"]
    assert claims and all(c["status"] == "candidate" for c in claims)
    original = next(s for s in rt.sources.versions(key) if s["content"].startswith("The café"))
    body = {k: original["record"][k] for k in ("source_id", "item_id", "media_type", "origin")}
    rt.sources.ingest(
        key,
        {
            "idempotency_key": "withdraw-original",
            "items": [
                {
                    **body,
                    "version_id": "v2",
                    "supersedes_version": original["record"]["version_id"],
                    "content": "This observation is withdrawn.",
                }
            ],
        },
    )
    current = rt.store.info(key)["revision_id"]
    with pytest.raises(RuntimeFault, match="Selected original source was superseded"):
        rt.sources.create_projection(
            key,
            {
                "idempotency_key": "project-old-packet",
                "expected_revision": current,
                "expected_generation": rt.sources.policy(key)["generation"],
                "claim_ids": [c["claim"]["claim_id"] for c in claims],
            },
        )
    with pytest.raises(RuntimeFault, match="Selected original source was superseded"):
        rt.sources.create_job(
            key,
            {
                **job["body"],
                "idempotency_key": "reextract-old-packet",
                "reprocess_id": "fresh",
                "expected_revision": current,
            },
        )
    assert rt.learning.claim() is None


def extraction_jobs(rt, gw):
    key = rt.create("Queued source work")["id"]
    recorded(rt, gw, {})
    install(rt, key)
    sources = [ingest(rt, key), ingest(rt, key)]
    jobs = []
    for source in sources:
        job = rt.sources.create_job(
            key,
            {
                "idempotency_key": str(uuid4()),
                "expected_revision": rt.store.info(key)["revision_id"],
                "expected_generation": rt.sources.policy(key)["generation"],
                **{k: source[k] for k in ("source_id", "item_id", "version_id")},
                "extractor": "external",
                "connection_id": rt.learning.connection_manager.control()["connection_id"],
                "connection_version": rt.learning.connection(
                    rt.learning.connection_manager.control()["connection_id"]
                )["version"],
                "call_limits": {
                    "max_duration_ms": 60000,
                    "max_input_tokens": 32000,
                    "max_output_tokens": 8192,
                },
            },
        )
        # The scheduler normally supplies these retained source/policy fields.
        rt.sources.prepare_external(key, job)
        jobs.append(rt.sources.get(key, "source_jobs", job["id"]))
    return key, jobs


def test_queue_wait_does_not_consume_call_window_or_repeat_unknown_dispatch(rig, monkeypatch):
    rt, gw = rig
    clock = [rt.learning.now()]
    monkeypatch.setattr(rt.learning, "now", lambda: clock[0])
    key, jobs = extraction_jobs(rt, gw)
    first = rt.learning.claim()
    assert rt.learning.claim() is None
    rt.learning.authorize(first["grant_id"], first["lease"])
    clock[0] += 41
    rt.learning.outcome(
        first["grant_id"],
        first["lease"],
        {"status": "succeeded", "text": '{"claims":[]}', "usage": {"input_tokens": 5, "output_tokens": 5}},
    )
    second = rt.learning.claim()
    dispatched = rt.learning.authorize(second["grant_id"], second["lease"])
    assert dispatched["expires"] - clock[0] == pytest.approx(60)
    assert dispatched["expires"] <= jobs[1]["deadline"]
    rt.learning.outcome(
        second["grant_id"],
        second["lease"],
        {"status": "outcome_unknown", "error": "provider_timeout", "usage": None, "text": None},
    )
    assert rt.learning.claim() is None
    assert rt.learning.provider_failure(second["grant_id"])["unresolved"]
    assert len(rt.sources.overview(key)["jobs"]) == 2


def test_queue_expiry_is_not_dispatched(rig, monkeypatch):
    rt, gw = rig
    clock = [rt.learning.now()]
    monkeypatch.setattr(rt.learning, "now", lambda: clock[0])
    key, jobs = extraction_jobs(rt, gw)
    clock[0] += 61
    assert rt.learning.claim() is None
    with rt.store.db() as db:
        rows = db.execute("SELECT status,calls,outcome FROM grants WHERE adm=?", (key,)).fetchall()
    assert len(rows) == 2
    assert all(
        r["status"] == "not_dispatched"
        and r["calls"] == 0
        and loads(r["outcome"])["error"] == "queue_timeout"
        for r in rows
    )


def test_empty_extraction_reports_actual_child_outcome_and_skipped_language(rig):
    rt, gw = rig
    key, uid, _, _ = continued(rt, gw)
    reply(rt, {"claims": []})
    done = finish_explanation(rt, key, uid)
    assert done["status"] == "failed"
    view = rt.interactions.get(key, uid)
    assert view["failure_code"] == "source_processing_failed"
    detail = view["failure_diagnostics"]["items"][0]["diagnostic"]
    assert detail["code"] == "empty_extraction" and detail["job_id"] and detail["grant_id"]
    assert "no explanation" in view["reply"]
    assert "skipped because learning did not complete" in view["reply"]
    assert not rt.sources.overview(key)["claims"]


def test_two_source_failures_preserve_empty_and_timeout_diagnostics(rig):
    from awm_adm.providers.failures import uncertain

    rt, gw = rig
    key = rt.create("Independent material outcomes")["id"]
    recorded(rt, gw, {})
    files = [
        uploaded(rt, key, name=f"part-{i}.md", content=text)
        for i, text in enumerate(("One original.", "Another original."))
    ]
    item = rt.interactions.submit(
        key,
        "teach",
        {
            "text": "Learn these two selected documents.",
            "attachments": [f["id"] for f in files],
        },
    )
    task = rt.conversations.teaching.get(key, item["id"])
    ids = [e["id"] for e in task["material_manifest"]["entries"] if e["kind"] == "upload"]
    assert rt.conversations.teaching.tick()
    respond(rt, facts_reply(task, ids))
    pump(rt, key, item["id"], lambda _: has_ready(rt))
    reply(rt, {"claims": []})
    pump(rt, key, item["id"], lambda _: has_ready(rt))
    second = rt.learning.claim()
    rt.learning.authorize(second["grant_id"], second["lease"])
    rt.learning.outcome(second["grant_id"], second["lease"], uncertain("timeout", "gateway_wait"))
    done = finish_explanation(rt, key, item["id"])
    assert done["status"] == "failed"
    view = rt.interactions.get(key, item["id"])
    failures = view["failure_diagnostics"]
    assert failures["complete"]
    by_code = {f["diagnostic"]["code"]: f["diagnostic"] for f in failures["items"]}
    assert set(by_code) == {"empty_extraction", "provider_timeout"}
    timeout = by_code["provider_timeout"]["provider_failure"]
    assert timeout["unresolved"] and timeout["calls"] == 1
    assert timeout["outcome"]["diagnostics"]["failure_stage"] == "gateway_wait"
    assert "timed out" in view["reply"] and "no claims" in view["reply"]
    before = rt.learning.usage()
    for _ in range(3):
        assert rt.interactions.get(key, item["id"])["status"] == "failed"
        rt.sources.tick()
    assert rt.learning.usage() == before and rt.learning.claim() is None


def test_legacy_task_selection_stays_per_item(rig):
    rt, gw = rig
    key = rt.create("Retained task selection")["id"]
    recorded(rt, gw, {})
    first = clarification(rt, key, "An original observation.")
    item = rt.interactions.submit(key, "teach", {"text": "Its clarification.", "reply_to": first["id"]})
    task = rt.conversations.teaching.get(key, item["id"])
    task.pop("source_context_profile")
    with rt.store.db(key) as db:
        rt.conversations.teaching.save(db, task)
    assert rt.conversations.teaching.tick()
    respond(rt, facts_reply(task, [e["id"] for e in task["material_manifest"]["entries"]]))
    pump(rt, key, item["id"], lambda _: has_ready(rt))
    assert all(not s["content"].startswith(PREFIX) for s in rt.sources.versions(key))
    rt.interactions.cancel(key, item["id"], "local")
    assert rt.learning.claim() is None
