"""authored source workflow through the actual preparation/feed/admission services."""

from uuid import uuid4

import pytest

from awm_adm.runtime.protocol import RuntimeFault, dumps

from .test_allowances import setup
from .test_application import app_runtime as app_runtime
from .test_application import client, envelope, execute
from .test_conversations import conversation, decision, message
from .test_learning_service import rig as rig
from .test_sources import fact, profile
from .test_teaching import funded, respond
from .test_teaching_execution import command, reply

TEXT = "The site has capacity ten places from 2020 through the end of 2023."


def uploaded(rt, key, **kw):
    return rt.conversations.intake.upload(
        key,
        {
            "idempotency_key": str(uuid4()),
            "name": "history.md",
            "media_type": "text/markdown",
            "content": TEXT,
            "source_id": "records",
            **kw,
        },
    )


def material_task(rt, gw, *, queue=False, key=None, content=TEXT, supersedes=None, mutate=None, attach=True):
    if not queue and key is None:
        key, cid = funded(rt, gw)
    else:
        _, price = setup(rt, gw)
        key = key or rt.create("Source queue")["id"]
        cid = conversation(rt, key, "teach")
        s = rt.conversations
        s.setup(
            key,
            cid,
            {
                "idempotency_key": str(uuid4()),
                "context": s.context(key),
                "price_id": price["id"],
                "purpose": "teach",
                "source_queue": queue,
            },
        )
        q = s.get(key, cid)["questions"][0]
        s.message(key, cid, message(rt, key, cid, "$0.50", reply_to=q["id"]))
        p = s.get(key, cid)["proposals"][0]
        s.decide(key, p["id"], decision(p), "owner")
    meta = uploaded(rt, key, content=content, supersedes_version=supersedes) if attach else None
    s = rt.conversations
    turn = s.message(
        key,
        cid,
        {
            **message(
                rt,
                key,
                cid,
                "Learn the attached site capacity history. Preserve the 2020–2024 and 2024–2026 cells, integer places 0–20.",
            ),
            "attachment_ids": [meta["id"]] if meta else [],
            "disclose_attachments": True,
        },
    )
    assert s.tick()
    plan = {
        "kind": "facts",
        "summary": "Historical site capacity",
        "children": [
            {
                "kind": "facts",
                "objective": "Retain historical capacity",
                "input_ids": [turn["id"]],
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
        mutate(plan)
    respond(
        rt, {"status": "ready", "message": "Check historical coverage.", "plan_json": dumps(plan).decode()}
    )
    view = s.get(key, cid)
    assert view["proposals"], view
    proposal = view["proposals"][0]
    s.decide(key, proposal["id"], decision(proposal), "owner")
    return key, cid, view["tasks"][0]["id"], meta


def ticks(rt, key, uid, predicate, count=40):
    for _ in range(count):
        task = rt.conversations.teaching.get(key, uid)
        if predicate(task):
            return task
        rt.conversations.tick()
        rt.sources.tick()
        rt.learning.tick()
    raise AssertionError(rt.conversations.teaching.get(key, uid))


def test_markdown_to_checked_admission_and_completion(rig):
    rt, gw = rig
    key, cid, uid, meta = material_task(rt, gw)
    with pytest.raises(RuntimeFault):
        command(rt, key, uid, "start")
    command(rt, key, uid, "start", source_consent=True)
    task = ticks(rt, key, uid, lambda t: bool(t["execution"]["steps"][0].get("feed_id")))
    for _ in range(5):
        rt.sources.tick()
    reply(rt, {"claims": [{**fact(), "start_byte": 0, "end_byte": len(TEXT.encode())}]})
    task = ticks(rt, key, uid, lambda t: t["status"] == "awaiting_decision")
    assert task["execution"]["review"]["kind"] == "source"
    command(rt, key, uid, "approve")
    task = ticks(rt, key, uid, lambda t: t["execution"]["phase"] == "narration")
    run = task["execution"]
    reply(
        rt,
        {
            "packet_digest": run["packet_digest"],
            "accepted_ids": run["summary"]["accepted_ids"],
            "unresolved_ids": [],
            "explanation": "The dated capacity was accepted.",
            "authority": "explanation_only",
        },
    )
    task = ticks(rt, key, uid, lambda t: t["status"] == "succeeded")
    assert rt.learning.usage()["calls"] == 3
    assert task["execution"]["summary"]["accepted"] == ["Retain historical capacity"]
    assert rt.sources.versions(key)[0]["content"] == TEXT
    assert all(r["status"] == "active" for r in rt.sources.overview(key)["support"])


def started(rt, gw, *, queue=False, mode=None):
    key = rt.create("Forward history", mode=mode)["id"] if mode else None
    key, cid, uid, meta = material_task(rt, gw, queue=queue, key=key)
    command(rt, key, uid, "start", source_consent=True)
    task = ticks(rt, key, uid, lambda t: bool(t["execution"]["steps"][0].get("feed_id")))
    return key, cid, uid, meta, task


def extracted(rt, key, uid, value=10, content=TEXT):
    for _ in range(5):
        rt.sources.tick()
    with rt.store.db() as db:
        ready = db.execute("SELECT count(*) FROM grants WHERE status='ready'").fetchone()[0]
    assert ready, str(
        {
            "context_matches": rt.conversations.teaching.get(key, uid)["execution"]["context"]
            == rt.conversations.context(key),
            "status": rt.conversations.teaching.get(key, uid)["status"],
            "feeds": [
                {k: f[k] for k in ("enabled", "cursor", "stall_reason", "counts", "backlog")}
                for f in rt.sources.feeds.overview(key)["feeds"]
            ],
            "jobs": [
                {k: j.get(k) for k in ("status", "error", "grant_id")}
                for j in rt.sources.history(key)["jobs"]
            ],
        }
    )
    reply(rt, {"claims": [{**fact(value), "start_byte": 0, "end_byte": len(content.encode())}]})
    return ticks(rt, key, uid, lambda t: t["status"] == "awaiting_decision")


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
    key, cid = funded(rt, gw)
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
        rt.conversations.message(
            key, cid, {**message(rt, key, cid, "Read the file"), "attachment_ids": [a["id"]]}
        )
    assert rt.learning.usage()["calls"] == 0
    assert not rt.sources.versions(key)
    other = rt.create("other")["id"]
    with pytest.raises(RuntimeFault):
        rt.conversations.intake.material(other, a["id"])
    assert rt.conversations.intake.material(key, a["id"])["source"]["content"] == body["content"]


def test_append_scope_replay_pause_and_revocation(rig):
    rt, gw = rig
    key, _, uid, _, _ = started(rt, gw, queue=True)
    access = append_credential(rt, key, uid)
    path = access["endpoint"]
    auth = {"Authorization": "Bearer " + access["token"]}
    body = pushed()
    with client(rt) as c:
        response = c.post(path, json=body, headers=auth)
        assert response.status_code == 202, response.text
        saved = response.json()
        assert c.post(path, json=body, headers=auth).json() == saved
        assert (
            c.post(
                path, json={**body, "items": [{**body["items"][0], "content": "changed"}]}, headers=auth
            ).status_code
            == 409
        )
        assert c.post(path, json=pushed(source_id="foreign"), headers=auth).status_code == 403
        for suffix in ("model", "sources", "requests", "conversations?channel=teach"):
            assert c.get(f"/api/v1/adms/{key}/{suffix}", headers=auth).status_code == 403
        assert (
            c.post(
                "/api/v1/auth/tokens", json={"adms": [key], "permissions": ["read"]}, headers=auth
            ).status_code
            == 403
        )
        status = c.get(f"/api/v1/adms/{key}/intake/{uid}/receipts/{body['idempotency_key']}", headers=auth)
        assert status.status_code == 200 and "content" not in str(status.json())
        command(rt, key, uid, "pause")
        assert c.post(path, json=body, headers=auth).json() == saved
        assert c.post(path, json=pushed("blocked"), headers=auth).status_code in (409, 403)
        c.delete("/api/v1/auth/tokens/" + access["id"])
        assert c.post(path, json=body, headers=auth).status_code == 401
    assert len(rt.sources.versions(key)) == 2


def test_pause_before_source_dispatch_holds_grant_and_local_serving(rig):
    rt, gw = rig
    key, _, uid, _, _ = started(rt, gw)
    for _ in range(5):
        rt.sources.tick()
    command(rt, key, uid, "pause")
    assert rt.learning.claim() is None
    rid = rt.coordinator.submit(key, envelope("serve-during-source"))
    result = execute(rt, key)
    assert result["status"] == "succeeded" and result["request_id"] == rid["request_id"]
    calls = rt.learning.usage()["calls"]
    command(rt, key, uid, "resume")
    task = extracted(rt, key, uid)
    assert task["status"] == "awaiting_decision"
    assert rt.learning.usage()["calls"] == calls


def test_source_review_cannot_bypass_parent_and_cancellation_fences(rig):
    rt, gw = rig
    key, _, uid, _, _ = started(rt, gw)
    task = extracted(rt, key, uid)
    ep = task["execution"]["review"]["receipt_id"]
    with pytest.raises(RuntimeFault):
        rt.sources.review(key, ep, {"expected_revision": rt.store.info(key)["revision_id"], "approve": True})
    command(rt, key, uid, "cancel")
    for _ in range(6):
        rt.sources.tick()
        rt.conversations.tick()
    assert not rt.sources.overview(key)["support"]
    assert rt.sources.get(key, "source_episodes", ep)["status"] == "cancelled"


def test_ambiguous_extraction_is_held_without_partial_admission(rig):
    rt, gw = rig
    key, _, uid, _, _ = started(rt, gw)
    for _ in range(5):
        rt.sources.tick()
    reply(
        rt,
        {
            "claims": [
                {**fact(), "start_byte": 0, "end_byte": len(TEXT.encode())},
                {**fact(9, entity_id="unknown"), "start_byte": 0, "end_byte": len(TEXT.encode())},
            ]
        },
    )
    task = ticks(rt, key, uid, lambda t: bool(t["execution"].get("summary")))
    assert not task["execution"]["summary"]["accepted"]
    assert task["execution"]["summary"]["unresolved"]
    attention = task["execution"]["steps"][0]["source_progress"]["attention_items"]
    assert attention[0]["label"] == "history.md" and attention[0]["reason"]
    assert not rt.sources.overview(key)["support"]


def test_corrected_push_holds_support_until_replacement_and_resolves_notice(rig):
    from .test_sources import lookup

    rt, gw = rig
    key, _, uid, meta, _ = started(rt, gw, queue=True, mode="forward")
    extracted(rt, key, uid)
    command(rt, key, uid, "approve")
    ticks(rt, key, uid, lambda t: t["execution"]["steps"][0].get("source_progress", {}).get("accepted") == 1)
    original = lookup(rt, key, 2021)
    assert original["result"]["value"]["value"] == 10
    access = append_credential(rt, key, uid)
    content = "The site capacity was corrected to nine places from 2020 through 2023."
    body = pushed(meta["item_id"], "v2", content=content, supersedes_version=meta["version_id"])
    with client(rt) as c:
        pushed_result = c.post(
            access["endpoint"], json=body, headers={"Authorization": "Bearer " + access["token"]}
        )
        assert pushed_result.status_code == 202, pushed_result.text
    held = lookup(rt, key, 2021)
    assert held["status"] == "needs_input" and held["result"] is None
    task = extracted(rt, key, uid, value=9, content=content)
    assert task["execution"]["review"]["kind"] == "source"
    command(rt, key, uid, "approve")
    ticks(rt, key, uid, lambda t: t["execution"]["steps"][0].get("source_progress", {}).get("accepted") == 2)
    new = lookup(rt, key, 2021)
    assert new["result"]["value"]["value"] == 9
    assert rt.store.request(key, original["request_id"])["result"] == original["result"]
    notice = rt.sources.overview(key)["revalidations"][-1]
    assert notice["status"] == "needs_evidence" and notice["current_status"] == "resolved"
    assert notice["resolution"]["revision_id"] == rt.store.info(key)["revision_id"]
    assert notice["resolution"]["claims"]
    feed = rt.sources.feeds.overview(key)["feeds"][0]
    assert feed["stall_reason"] is None
    command(rt, key, uid, "finish")
    ticks(rt, key, uid, lambda t: t["execution"]["phase"] == "narration")


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


@pytest.mark.parametrize("phase", ["ready", "dispatched", "review", "approved", "paused"])
def test_restart_source_authority_and_unknown_reservations(rig, phase):
    from awm_adm.runtime.service import Runtime

    rt, gw = rig
    key, _, uid, _, _ = started(rt, gw, queue=True)
    if phase in {"review", "approved", "paused"}:
        extracted(rt, key, uid)
    else:
        for _ in range(5):
            rt.sources.tick()
    if phase == "dispatched":
        job = rt.learning.claim()
        rt.learning.authorize(job["grant_id"], job["lease"])
    if phase == "approved":
        command(rt, key, uid, "approve")
    if phase == "paused":
        command(rt, key, uid, "pause")
    calls = rt.learning.usage()["calls"]
    feed = rt.sources.feeds.overview(key)["feeds"][0]
    config = rt.config
    rt.close()
    recovered = Runtime(config, start_scheduler=False)
    try:
        for _ in range(10):
            recovered.conversations.tick()
            recovered.sources.tick()
        task = recovered.conversations.teaching.get(key, uid)
        after = recovered.sources.feeds.overview(key)["feeds"][0]
        assert after["reserved"] == feed["reserved"]
        if phase == "paused":
            assert task["status"] == "paused"
            assert after["stall_reason"] == "parent_paused"
        if phase == "review":
            assert task["status"] == "awaiting_decision"
        if phase == "approved":
            assert all(x["status"] == "active" for x in recovered.sources.overview(key)["support"])
        if phase == "dispatched":
            assert recovered.learning.allowances.view(task["allowance_id"])["unresolved_calls"] >= 1
        with recovered.store.db() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM grants WHERE json_extract(body,'$.purpose')='extraction'"
                ).fetchone()[0]
                == 1
            )
        assert recovered.learning.usage()["calls"] <= calls
    finally:
        recovered.close()


def test_source_review_after_active_deadline_is_local_only(rig, monkeypatch):
    rt, gw = rig
    key, _, uid, _, _ = started(rt, gw)
    task = extracted(rt, key, uid)
    now = task["execution"]["deadline_ms"] + 1
    before = rt.learning.usage()["calls"]
    monkeypatch.setattr(rt.conversations, "now", lambda: now)
    monkeypatch.setattr(rt.learning, "now", lambda: now / 1000)
    command(rt, key, uid, "approve")
    for _ in range(10):
        rt.sources.tick()
        rt.conversations.tick()
    task = rt.conversations.teaching.get(key, uid)
    assert task["execution"]["summary"]["accepted"]
    assert rt.sources.overview(key)["support"][0]["status"] == "active"
    assert rt.learning.usage()["calls"] == before
    assert task["status"] == "succeeded"
    assert not task["execution"]["summary"]["unresolved"]
    assert task["execution"]["summary"]["vocabulary"] == "installed"
    assert task["execution"]["summary"]["completion_explanation"] == "unavailable"


def test_finish_drains_received_cutoff_and_refuses_later_push(rig):
    rt, gw = rig
    key, _, uid, _, _ = started(rt, gw, queue=True)
    access = append_credential(rt, key, uid)
    with client(rt) as c:
        headers = {"Authorization": "Bearer " + access["token"]}
        assert c.post(access["endpoint"], json=pushed("delayed"), headers=headers).status_code == 202
        command(rt, key, uid, "finish")
        assert c.post(access["endpoint"], json=pushed("too-late"), headers=headers).status_code == 409
    # Authored failure avoids spending a call on either record; both durable items still get dispositions.
    for _ in range(20):
        rt.sources.tick()
        jobs = rt.sources.history(key)["jobs"]
        for j in jobs:
            if j["status"] in {"queued", "awaiting_provider"}:
                rt.sources.cancel(key, "jobs", j["id"])
        rt.conversations.tick()
    task = rt.conversations.teaching.get(key, uid)
    assert task["execution"]["steps"][0]["source_progress"]["received"] == 2
    assert task["execution"]["summary"]["unresolved"]
    assert len(rt.sources.versions(key)) == 2


def test_stopped_queue_reports_partial_accepted_facts(rig):
    rt, gw = rig
    key, _, uid, _, _ = started(rt, gw, queue=True)
    extracted(rt, key, uid)
    command(rt, key, uid, "approve")
    rt.sources.tick()  # Publication can precede the feed/parent acknowledgement.
    command(rt, key, uid, "cancel")
    rt.conversations.tick()
    task = rt.conversations.teaching.get(key, uid)
    assert task["execution"]["summary"]["accepted"]
    assert task["execution"]["summary"]["unresolved"]
    assert rt.sources.overview(key)["support"][0]["status"] == "active"


def test_empty_queue_and_pasted_source_are_supported(rig):
    rt, gw = rig
    key, _, uid, _ = material_task(rt, gw, queue=True, attach=False)
    command(rt, key, uid, "start", source_consent=True)
    ticks(rt, key, uid, lambda t: bool(t["execution"]["steps"][0].get("feed_id")))
    assert rt.sources.versions(key) == []
    assert append_credential(rt, key, uid)["scope"]["source_ids"] == ["records"]
    command(rt, key, uid, "finish")
    ticks(rt, key, uid, lambda t: bool(t["execution"].get("summary")))
    key2, _, uid2, _ = material_task(rt, gw, attach=False)
    command(rt, key2, uid2, "start", source_consent=True)
    ticks(rt, key2, uid2, lambda t: bool(t["execution"]["steps"][0].get("feed_id")))
    assert len(rt.sources.versions(key2)) == 1
    assert rt.sources.versions(key2)[0]["record"]["origin"].startswith("conversation:")


def test_mixed_capability_and_source_children_share_parent_budget(rig):
    from .test_teaching import plan
    from .test_teaching_execution import definition

    rt, gw = rig

    def mixed(p):
        rule = plan(p["children"][0]["input_ids"])["children"][0]
        p["kind"] = "mixed"
        p["children"].insert(0, rule)

    key, _, uid, _ = material_task(rt, gw, mutate=mixed)
    command(rt, key, uid, "start", source_consent=True)
    for _ in range(5):
        rt.conversations.tick()
        rt.learning.tick()
    reply(rt, definition())
    ticks(rt, key, uid, lambda t: t["status"] == "awaiting_decision")
    command(rt, key, uid, "approve")
    ticks(rt, key, uid, lambda t: bool(t["execution"]["steps"][1].get("feed_id")))
    extracted(rt, key, uid)
    command(rt, key, uid, "approve")
    task = ticks(rt, key, uid, lambda t: t["execution"]["phase"] == "narration")
    assert len(task["execution"]["summary"]["accepted"]) == 2
    with rt.store.db() as db:
        assert len(db.execute("SELECT DISTINCT allowance_id FROM charges").fetchall()) == 1
    assert task["budget"]["cap_micro_usd"] == 500000


def test_parent_cancel_during_source_check_cannot_publish(rig, monkeypatch):
    rt, gw = rig
    key, _, uid, _, _ = started(rt, gw)
    extracted(rt, key, uid)
    command(rt, key, uid, "approve")
    compute = rt.sources.compute

    def raced(key, operation, *args, **kwargs):
        result = compute(key, operation, *args, **kwargs)
        if operation == "source_admit":
            command(rt, key, uid, "cancel")
        return result

    monkeypatch.setattr(rt.sources, "compute", raced)
    rt.sources.tick()
    assert not rt.sources.overview(key)["support"]
    assert rt.conversations.teaching.get(key, uid)["status"] == "cancelled"


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


def test_processing_exhaustion_closes_scope_without_losing_received_originals(rig):
    rt, gw = rig
    key, _, uid, _, task = started(rt, gw, queue=True)
    extracted(rt, key, uid)
    command(rt, key, uid, "approve")
    ticks(rt, key, uid, lambda t: t["execution"]["steps"][0].get("source_progress", {}).get("accepted") == 1)
    access = append_credential(rt, key, uid)
    with client(rt) as c:
        assert (
            c.post(
                access["endpoint"],
                json=pushed("retained-after-cap"),
                headers={"Authorization": "Bearer " + access["token"]},
            ).status_code
            == 202
        )
    # Authored lifetime exhaustion: the item was durably acknowledged before room ran out.
    feed_id = task["execution"]["steps"][0]["feed_id"]
    feed = rt.sources.feeds.get(key, feed_id)
    feed["reserved"]["items"] = feed["body"]["budget"]["max_items"]
    with rt.store.db(key) as db:
        rt.sources.feeds.save(db, feed)
    task = ticks(rt, key, uid, lambda t: bool(t["execution"].get("summary")))
    assert task["execution"]["summary"]["accepted"] and task["execution"]["summary"]["unresolved"]
    assert len(rt.sources.versions(key)) == 2
    assert rt.learning.usage(lane="interaction")["calls"] == 0


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
    task = extracted(rt, key, uid)
    episode = rt.sources.get(key, "source_episodes", task["execution"]["review"]["receipt_id"])
    assert episode["work_reserved"] == 2000000
    feed = rt.sources.feeds.overview(key)["feeds"][0]
    assert feed["reserved"]["work"] == 3000000
    assert rt.sources.history(key)["jobs"][0]["work_reserved"] == 1000000
