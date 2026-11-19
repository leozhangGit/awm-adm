"""Supplied material and explicit managed push queues share checked automatic intake."""

from uuid import uuid4

import pytest

from awm_adm.runtime.protocol import RuntimeFault, dumps

from .interaction_support import TEXT, respond, uploaded
from .test_application import app_runtime as app_runtime
from .test_application import client, envelope, execute
from .test_direct_ask import recorded, work
from .test_direct_teach import pump as ticks
from .test_learning_service import rig as rig
from .test_sources import profile


def material_task(rt, gw, *, queue=False, key=None, content=TEXT, supersedes=None, mutate=None, attach=True):
    key = key or rt.create("Supplied history")["id"]
    if not rt.learning.connection_manager.control()["connection_id"]:
        recorded(rt, gw, {})
    meta = uploaded(rt, key, content=content, supersedes_version=supersedes) if attach else None
    item = rt.interactions.submit(
        key,
        "teach",
        {
            "text": "Learn site capacity history in whole-number places 0–20, with dated 2020–2024 and 2024–2026 intervals.",
            "attachments": [meta["id"]] if meta else [],
        },
        source_queue=queue,
    )
    uid = item["id"]
    current = work(rt, key, uid)
    assert rt.conversations.teaching.tick()
    value = {
        "kind": "facts",
        "summary": "Historical site capacity",
        "children": [
            {
                "kind": "facts",
                "objective": "Retain historical capacity",
                "input_ids": [current["turn_id"]],
                "material": {
                    "projection": profile(),
                    "sources": [
                        {
                            "source_id": "records",
                            "attribution": "Owner history document",
                            "evidence_group": "owner",
                            "allow_external": False,
                        }
                    ],
                },
            }
        ],
    }
    if mutate:
        mutate(value)
    respond(
        rt, {"status": "ready", "message": "The dated scope is clear.", "plan_json": dumps(value).decode()}
    )
    return key, current["conversation_id"], uid, meta


def started(rt, gw, *, queue=False, mode=None):
    key = rt.create("Forward history", mode=mode)["id"] if mode else None
    key, cid, uid, meta = material_task(rt, gw, queue=queue, key=key)
    task = ticks(rt, key, uid, lambda t: bool(t["execution"]["steps"][0].get("feed_id")))
    return key, cid, uid, meta, task


def append_credential(rt, key, uid):
    task = rt.conversations.teaching.get(key, uid)
    with client(rt) as c:
        result = c.post(
            f"/api/v1/adms/{key}/intake/{uid}/credentials",
            json={
                "context": rt.conversations.context(key),
                "specification_digest": task["specification_digest"],
                "expected_version": task["execution"]["version"],
            },
        )
        assert result.status_code == 201, result.text
        return result.json()


def pushed(item="later", version="v1", **kw):
    return {
        "idempotency_key": str(uuid4()),
        "items": [
            {
                "source_id": "records",
                "item_id": item,
                "version_id": version,
                "media_type": "text/markdown",
                "content": TEXT,
                "origin": "Synthetic local producer",
                **kw,
            }
        ],
    }


@pytest.mark.parametrize(
    "mutation",
    [
        {"name": "../bad.md"},
        {"name": "bad\x00.md"},
        {"content": "x\x00y"},
        {"content": "é" * 131073},
        {"media_type": "application/pdf"},
    ],
)
def test_upload_bounds_and_no_remote_work(rig, mutation):
    rt, _ = rig
    key = rt.create("upload checks")["id"]
    with client(rt) as c:
        result = c.post(
            f"/api/v1/adms/{key}/attachments",
            json={
                "idempotency_key": "bad-upload",
                "name": "a.md",
                "media_type": "text/markdown",
                "content": "data",
                **mutation,
            },
        )
        assert result.status_code == 422
    assert rt.learning.usage()["calls"] == 0
    assert not rt.conversations.intake.attachments(key)["items"]


def test_upload_replay_content_and_no_implicit_disclosure(rig):
    rt, gw = rig
    key = rt.create("Upload only")["id"]
    recorded(rt, gw, {})
    body = {
        "idempotency_key": "upload",
        "name": "passage.md",
        "media_type": "text/markdown",
        "content": "α historical data <script>bad()</script>",
    }
    a = rt.conversations.intake.upload(key, body)
    assert rt.conversations.intake.upload(key, body) == a
    with pytest.raises(RuntimeFault):
        rt.conversations.intake.upload(key, {**body, "content": "different"})
    with pytest.raises(RuntimeFault):
        rt.interactions.submit(key, "ask", {"text": "Read the file", "attachments": [a["id"]]})
    assert rt.learning.usage()["calls"] == 0
    assert not rt.sources.versions(key)
    other = rt.create("other")["id"]
    with pytest.raises(RuntimeFault):
        rt.conversations.intake.material(other, a["id"])
    assert rt.conversations.intake.material(key, a["id"])["source"]["content"] == body["content"]


def test_queue_throttle_backpressure_and_unrelated_model_serving(rig, monkeypatch):
    rt, gw = rig
    key, _, uid, _, _ = started(rt, gw, queue=True)
    access = append_credential(rt, key, uid)
    auth = {"Authorization": "Bearer " + access["token"]}
    clock = rt.conversations.now
    original_usage = rt.learning.usage()
    with client(rt) as c:
        for i in range(60):
            response = c.post(access["endpoint"], json=pushed(f"item{i}"), headers=auth)
            assert response.status_code == 202, response.text
        blocked = pushed("item60")
        response = c.post(access["endpoint"], json=blocked, headers=auth)
        assert response.status_code == 429, response.text
        monkeypatch.setattr(rt.conversations, "now", lambda: clock() + 61000)
        assert c.post(access["endpoint"], json=blocked, headers=auth).status_code == 202
        for i in range(61, 99):
            response = c.post(access["endpoint"], json=pushed(f"item{i}"), headers=auth)
            assert response.status_code == 202, response.text
        response = c.post(access["endpoint"], json=pushed("overflow"), headers=auth)
        assert response.status_code in (409, 429, 503), response.text
    assert len(rt.sources.versions(key)) == 100
    other = rt.create("Independent serving")["id"]
    rt.coordinator.submit(other, envelope("serve-other"))
    assert execute(rt, other)["status"] == "succeeded"
    assert rt.learning.usage() == original_usage


def test_lost_append_ack_replays_committed_receipt(rig, monkeypatch):
    rt, gw = rig
    key, _, uid, _, _ = started(rt, gw, queue=True)
    access = append_credential(rt, key, uid)
    body = pushed("lost-ack")
    ingest = rt.sources.ingest

    def lost(*args, **kwargs):
        ingest(*args, **kwargs)
        raise RuntimeError("authored lost HTTP acknowledgement")

    with client(rt) as c:
        monkeypatch.setattr(rt.sources, "ingest", lost)
        with pytest.raises(RuntimeError):
            c.post(access["endpoint"], json=body, headers={"Authorization": "Bearer " + access["token"]})
        monkeypatch.setattr(rt.sources, "ingest", ingest)
        response = c.post(
            access["endpoint"], json=body, headers={"Authorization": "Bearer " + access["token"]}
        )
        assert response.status_code == 202 and response.json()["added"] == 1
    assert len(rt.sources.versions(key)) == 2


def test_upload_content_dedup_preserves_each_submission_identity(rig):
    rt, gw = rig
    key = rt.create("Upload identity")["id"]
    a = uploaded(rt, key, idempotency_key="one")
    b = uploaded(rt, key, idempotency_key="two")
    assert a == b
    with pytest.raises(RuntimeFault, match="different content"):
        uploaded(rt, key, idempotency_key="two", content="changed")
    assert len(rt.conversations.intake.attachments(key)["items"]) == 1


def test_changed_owner_context_fences_append_without_acknowledgement(rig):
    rt, gw = rig
    key, _, uid, _, _ = started(rt, gw, queue=True)
    access = append_credential(rt, key, uid)
    before = len(rt.sources.versions(key))
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    with client(rt) as c:
        result = c.post(
            access["endpoint"], json=pushed("fenced"), headers={"Authorization": "Bearer " + access["token"]}
        )
        assert result.status_code == 409
    assert len(rt.sources.versions(key)) == before
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM intake_receipts").fetchone()[0] == 0


def test_managed_local_compute_caps_cannot_grow_with_operator_defaults(rig):
    rt, gw = rig
    # Managed work uses the contract's 1M/5s ceiling even if the runtime allows more.
    rt.config = rt.config.model_copy(
        update={
            "request": rt.config.request.model_copy(update={"max_work": 5000000, "max_duration_ms": 20000})
        }
    )
    assert rt.sources.managed_limits(parent="bounded")["max_work"] == 1000000
    assert rt.sources.managed_limits(parent="bounded")["max_duration_ms"] == 5000
    assert rt.sources.managed_limits()["max_work"] == 5000000

    key, _, uid, _, _ = started(rt, gw)
    from .interaction_support import reply
    from .test_direct_teach import has_ready
    from .test_sources import fact

    ticks(rt, key, uid, lambda _: has_ready(rt))
    reply(rt, {"claims": [{**fact(10), "start_byte": 0, "end_byte": len(TEXT.encode())}]})
    ticks(rt, key, uid, lambda t: t["execution"]["steps"][0]["status"] == "accepted")
    episode = rt.sources.history(key)["episodes"][0]
    assert episode["work_reserved"] == 2000000
    feed = rt.sources.feeds.overview(key)["feeds"][0]
    assert feed["reserved"]["work"] == 3000000
    assert rt.sources.history(key)["jobs"][0]["work_reserved"] == 1000000
