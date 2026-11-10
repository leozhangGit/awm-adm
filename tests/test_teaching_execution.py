"""parent authority, real local admission, and offline provider accounting."""

from uuid import uuid4

import pytest

from awm_adm.runtime.protocol import RuntimeFault, dumps
from awm_adm.runtime.service import Runtime

from .ported.provider_fixtures import wire_expression
from .test_application import app_runtime as app_runtime
from .test_conversations import decision
from .test_learning_service import rig as rig
from .test_teaching import funded, prepare


def prepared(rt, gw, mutate=None):
    key, cid = funded(rt, gw)
    prepare(rt, key, cid, mutate)
    s = rt.conversations
    p = s.get(key, cid)["proposals"][0]
    s.decide(key, p["id"], decision(p), "owner")
    uid = s.get(key, cid)["tasks"][0]["id"]
    return key, cid, uid


def command(rt, key, uid, action, **kw):
    task = rt.conversations.teaching.get(key, uid)
    run = task.get("execution", {})
    body = {
        "idempotency_key": str(uuid4()),
        "context": rt.conversations.context(key),
        "specification_digest": task["specification_digest"],
        "expected_version": run.get("version", 0),
        "action": action,
        "review_digest": (run.get("review") or {}).get("digest"),
        **kw,
    }
    return rt.conversations.teaching.execution.command(key, uid, body, "owner")


def reply(rt, value):
    job = rt.learning.claim()
    assert job
    rt.learning.authorize(job["grant_id"], job["lease"])
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {
            "status": "succeeded",
            "text": dumps(value).decode(),
            "usage": {"input_tokens": 100, "output_tokens": 200},
        },
    )
    return job


def definition():
    return {
        "format": "adm-construction/1",
        "result": {
            "status": "draft",
            "definitions": {
                "math.double": {
                    "body": wire_expression(
                        {"op": "add", "args": [{"op": "var", "name": "n"}, {"op": "var", "name": "n"}]}
                    )
                }
            },
            "declarations": [],
            "discard": [],
            "retractions": [],
            "summary": "Authored doubling fixture",
        },
    }


def advance(rt, key, uid, target, count=25):
    for _ in range(count):
        task = rt.conversations.teaching.get(key, uid)
        if task["status"] == target:
            return task
        rt.conversations.tick()
        rt.learning.tick()
    raise AssertionError(rt.conversations.teaching.get(key, uid))


def acquire(rt, key, uid):
    command(rt, key, uid, "start")
    advance(rt, key, uid, "running")
    for _ in range(3):
        rt.conversations.tick()
        rt.learning.tick()
    assert rt.conversations.teaching.get(key, uid)["status"] == "running", rt.conversations.teaching.get(
        key, uid
    )
    reply(rt, definition())
    return advance(rt, key, uid, "awaiting_decision")


def test_review_admission_completion_and_separate_summary(rig):
    rt, gw = rig
    key, cid, uid = prepared(rt, gw)
    initial = rt.store.info(key)
    task = acquire(rt, key, uid)
    assert rt.store.info(key) == initial
    assert task["execution"]["review"]["preview"]["declarations"]["math.double"]
    command(rt, key, uid, "approve")
    for _ in range(10):
        rt.learning.tick()
        rt.conversations.tick()
        task = rt.conversations.teaching.get(key, uid)
        if task["execution"]["phase"] == "narration":
            break
    run = task["execution"]
    assert run["steps"][0]["status"] == "accepted", task
    assert run["context"]["revision_id"] != initial["revision_id"]
    assert run.get("narration_grant_id"), task
    reply(
        rt,
        {
            "packet_digest": run["packet_digest"],
            "accepted_ids": run["summary"]["accepted_ids"],
            "unresolved_ids": [],
            "explanation": "The bounded doubling capability is ready.",
            "authority": "explanation_only",
        },
    )
    task = advance(rt, key, uid, "succeeded")
    assert task["execution"]["narration"]["explanation"]
    assert task["execution"]["summary"]["spend"]["unresolved_calls"] == 0
    assert rt.learning.usage()["calls"] == 3
    before = rt.conversations.get(key, cid)
    for _ in range(3):
        assert not rt.conversations.tick()
    assert rt.conversations.get(key, cid) == before


def test_cancel_while_dispatched_fences_late_publication(rig):
    rt, gw = rig
    key, cid, uid = prepared(rt, gw)
    command(rt, key, uid, "start")
    for _ in range(5):
        rt.conversations.tick()
        rt.learning.tick()
    job = rt.learning.claim()
    assert job
    rt.learning.authorize(job["grant_id"], job["lease"])
    before = rt.store.info(key)
    command(rt, key, uid, "cancel")
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {
            "status": "succeeded",
            "text": dumps(definition()).decode(),
            "usage": {"input_tokens": 100, "output_tokens": 200},
        },
    )
    for _ in range(5):
        rt.conversations.tick()
        rt.learning.tick()
    assert rt.store.info(key) == before
    assert rt.conversations.teaching.get(key, uid)["status"] == "cancelled"
    assert not rt.learning.claim()


def test_pause_holds_known_candidate_and_resume_does_not_reacquire(rig):
    rt, gw = rig
    key, cid, uid = prepared(rt, gw)
    acquire(rt, key, uid)
    command(rt, key, uid, "pause")
    calls = rt.learning.usage()["calls"]
    for _ in range(3):
        rt.conversations.tick()
        rt.learning.tick()
    assert rt.learning.usage()["calls"] == calls
    command(rt, key, uid, "resume")
    assert rt.conversations.teaching.get(key, uid)["status"] == "awaiting_decision"
    command(rt, key, uid, "approve")
    rt.learning.tick()
    assert rt.conversations.teaching.get(key, uid)["execution"]["steps"][0]["status"] == "accepted"


def test_command_exact_replay_and_stale_spec_context_and_version(rig):
    rt, gw = rig
    key, _, uid = prepared(rt, gw)
    x = rt.conversations.teaching.execution
    task = rt.conversations.teaching.get(key, uid)
    body = {
        "idempotency_key": str(uuid4()),
        "context": rt.conversations.context(key),
        "specification_digest": task["specification_digest"],
        "expected_version": 0,
        "action": "start",
    }
    ack = x.command(key, uid, body, "owner")
    assert x.command(key, uid, body, "owner") == ack
    with pytest.raises(RuntimeFault):
        x.command(key, uid, {**body, "action": "cancel"}, "owner")
    with pytest.raises(RuntimeFault):
        x.command(
            key,
            uid,
            {**body, "idempotency_key": str(uuid4()), "specification_digest": "sha256:" + "0" * 64},
            "owner",
        )
    with pytest.raises(RuntimeFault):
        command(rt, key, uid, "pause", expected_version=0)
    assert rt.learning.usage()["calls"] == 1


@pytest.mark.parametrize(
    "phase", ["queued", "creating", "ready_grant", "dispatched", "received", "review", "approved", "accepted"]
)
def test_restart_reconciles_known_local_work_without_repeating_dispatch(rig, phase):
    rt, gw = rig
    key, _, uid = prepared(rt, gw)
    command(rt, key, uid, "start")
    x = rt.conversations.teaching.execution
    if phase != "queued":
        assert x.tick()  # durable child intent
    if phase not in {"queued", "creating"}:
        assert x.tick()  # episode created
        assert rt.learning.tick()  # grant ready
    if phase in {"dispatched", "received", "review", "approved", "accepted"}:
        job = rt.learning.claim()
        assert job
        rt.learning.authorize(job["grant_id"], job["lease"])
    if phase in {"received", "review", "approved", "accepted"}:
        rt.learning.outcome(
            job["grant_id"],
            job["lease"],
            {
                "status": "succeeded",
                "text": dumps(definition()).decode(),
                "usage": {"input_tokens": 100, "output_tokens": 200},
            },
        )
    if phase in {"review", "approved", "accepted"}:
        advance(rt, key, uid, "awaiting_decision")
    if phase in {"approved", "accepted"}:
        command(rt, key, uid, "approve")
    if phase == "accepted":
        assert rt.learning.tick()
    before_calls = rt.learning.usage()["calls"]
    config = rt.config
    rt.close()
    recovered = Runtime(config, start_scheduler=False)
    try:
        for _ in range(7):
            recovered.conversations.tick()
            recovered.learning.tick()
        task = recovered.conversations.teaching.get(key, uid)
        eps = recovered.learning.episodes(key)
        assert len(eps) == 1
        if phase == "dispatched":
            assert recovered.learning.allowances.view(task["allowance_id"])["unresolved_calls"] >= 1
            assert task["execution"]["steps"][0]["status"] == "unresolved"
        elif phase == "ready_grant":
            assert task["execution"]["steps"][0]["status"] == "unresolved"
        elif phase in {"received", "review"}:
            assert task["status"] == "awaiting_decision", task
        elif phase in {"approved", "accepted"}:
            assert task["execution"]["steps"][0]["status"] == "accepted", task
        # A completion call may be newly reserved, but the acquisition is never duplicated.
        with recovered.store.db() as db:
            assert db.execute("SELECT count(*) FROM grants WHERE episode IS NOT NULL").fetchone()[0] <= 1
        assert recovered.learning.usage()["calls"] >= before_calls - (phase == "ready_grant")
    finally:
        recovered.close()


def test_lost_child_ack_reattaches_same_episode(rig, monkeypatch):
    rt, gw = rig
    key, _, uid = prepared(rt, gw)
    command(rt, key, uid, "start")
    x = rt.conversations.teaching.execution
    x.tick()
    original = rt.learning.create

    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("authored lost acknowledgement")

    monkeypatch.setattr(rt.learning, "create", lost)
    with pytest.raises(OSError):
        x.tick()
    monkeypatch.setattr(rt.learning, "create", original)
    assert x.tick()
    assert len(rt.learning.episodes(key)) == 1


def test_changed_mode_fences_semantic_review_and_old_approval(rig):
    rt, gw = rig
    key, _, uid = prepared(rt, gw)
    task = acquire(rt, key, uid)
    old = task["execution"]["review"]["digest"]
    info = rt.store.info(key)
    rt.store.change(key, info["policy_epoch"], mode="forward")
    with pytest.raises(RuntimeFault):
        command(rt, key, uid, "approve", review_digest=old)
    for _ in range(4):
        rt.conversations.tick()
        rt.learning.tick()
    task = rt.conversations.teaching.get(key, uid)
    assert task["status"] == "needs_input"
    assert not any(s["status"] == "accepted" for s in task["execution"]["steps"])


def test_v2_review_cannot_bypass_parent_decision(rig):
    rt, gw = rig
    key, _, uid = prepared(rt, gw)
    task = acquire(rt, key, uid)
    with pytest.raises(RuntimeFault, match="teaching task"):
        rt.learning.review(
            key,
            task["execution"]["review"]["receipt_id"],
            {"expected_revision": rt.store.info(key)["revision_id"], "approve": True},
        )


def test_pause_after_ready_grant_keeps_it_unissued(rig):
    rt, gw = rig
    key, _, uid = prepared(rt, gw)
    command(rt, key, uid, "start")
    for _ in range(4):
        rt.conversations.tick()
        rt.learning.tick()
    command(rt, key, uid, "pause")
    assert rt.learning.claim() is None
    command(rt, key, uid, "resume")
    assert rt.learning.claim() is not None


def test_checked_auto_uses_independent_policy_and_installs_checked_vocabulary(rig):
    from awm_adm.engine import Instance
    from awm_adm.runtime.protocol import pack

    from .test_conversations import decision
    from .test_instance import capacity_policy
    from .test_teaching import funded, prepare

    rt, gw = rig
    policy = capacity_policy(10)
    contract = policy["contracts"][0]
    contract["required_symbols"] = ["math.double"]
    contract["checks"][0]["expression"] = {
        "op": "call",
        "function": "math.double",
        "args": {"n": {"op": "literal", "value": 5}},
    }
    key = rt.create("Independent doubling", snapshot=pack(Instance(policy=policy).export_snapshot()))["id"]
    key, cid = funded(rt, gw, key)
    prepare(rt, key, cid)
    p = rt.conversations.get(key, cid)["proposals"][0]
    rt.conversations.decide(key, p["id"], decision(p), "owner")
    uid = rt.conversations.get(key, cid)["tasks"][0]["id"]
    command(rt, key, uid, "start")
    for _ in range(4):
        rt.conversations.tick()
        rt.learning.tick()
    reply(rt, definition())
    for _ in range(10):
        rt.learning.tick()
        rt.conversations.tick()
    task = rt.conversations.teaching.get(key, uid)
    assert task["execution"]["publication"] == "checked_auto"
    assert task["execution"]["steps"][0]["status"] == "accepted", rt.learning.episode(
        key, task["execution"]["steps"][0]["episode_id"]
    )
    assert rt.language.vocabulary(key)["vocabulary"]["aliases"]["double"] == ["math.double"]
    assert task["execution"]["vocabulary"] == "installed"


def test_invalid_definition_has_two_bounded_attempts_no_partial_publication(rig):
    rt, gw = rig
    key, _, uid = prepared(rt, gw)
    before = rt.store.info(key)
    command(rt, key, uid, "start")
    for _ in range(4):
        rt.conversations.tick()
        rt.learning.tick()
    for _ in range(2):
        bad = definition()
        bad["result"]["definitions"]["math.double"]["body"] = {"op": "literal", "value": 9999}
        reply(rt, bad)
        for _ in range(5):
            rt.learning.tick()
            rt.conversations.tick()
    task = rt.conversations.teaching.get(key, uid)
    assert task["execution"]["steps"][0]["status"] == "unresolved", task
    assert rt.store.info(key) == before
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants WHERE episode IS NOT NULL").fetchone()[0] == 2


def test_control_route_owner_only_and_exact_body(rig):
    from .test_application import client

    rt, gw = rig
    key, cid, uid = prepared(rt, gw)
    t = rt.conversations.teaching.get(key, uid)
    body = {
        "idempotency_key": str(uuid4()),
        "action": "start",
        "context": rt.conversations.context(key),
        "specification_digest": t["specification_digest"],
        "expected_version": 0,
    }
    with client(rt) as c:
        r = c.post(f"/api/v1/adms/{key}/tasks/{uid}/commands", json=body)
        assert r.status_code == 200, r.text
        assert c.post(f"/api/v1/adms/{key}/tasks/{uid}/commands", json=body).json() == r.json()
        assert (
            c.post(
                f"/api/v1/adms/{key}/tasks/{uid}/commands", json={**body, "publication": "unchecked"}
            ).status_code
            == 422
        )
        c.headers.pop("Authorization")
        assert c.post(f"/api/v1/adms/{key}/tasks/{uid}/commands", json=body).status_code in {401, 403}


@pytest.mark.parametrize("mode,expected", [("backward", "unresolved"), ("forward", "accepted")])
def test_correction_uses_receipt_precedence_and_never_retries_rejection(rig, mode, expected):
    from awm_adm.engine import Instance
    from awm_adm.runtime.protocol import pack

    from .test_teaching import plan

    rt, gw = rig
    header = plan(["fixture"])["children"][0]["interfaces"]["math.double"]
    instance = Instance(
        {
            "profile": "finite-v0",
            "declarations": {"math.double": {**header, "body": {"op": "literal", "value": 0}}},
        }
    )
    key = rt.create("Correction fixture", mode=mode, snapshot=pack(instance.export_snapshot()))["id"]
    key, cid = funded(rt, gw, key)

    def correction(p):
        p["kind"] = p["children"][0]["kind"] = "correction"

    prepare(rt, key, cid, correction)
    p = rt.conversations.get(key, cid)["proposals"][0]
    rt.conversations.decide(key, p["id"], decision(p), "owner")
    uid = rt.conversations.get(key, cid)["tasks"][0]["id"]
    acquire(rt, key, uid)
    command(rt, key, uid, "approve")
    for _ in range(9):
        rt.learning.tick()
        rt.conversations.tick()
    task = rt.conversations.teaching.get(key, uid)
    assert task["execution"]["steps"][0]["status"] == expected, task
    if mode == "backward":
        assert task["execution"]["steps"][0]["reason"] == "backward_precedence"
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants WHERE episode IS NOT NULL").fetchone()[0] == 1


def test_missing_price_reserve_stops_without_spending_ask_lane(rig):
    rt, gw = rig
    key, _, uid = prepared(rt, gw)
    command(rt, key, uid, "start")
    task = rt.conversations.teaching.get(key, uid)
    # Authored accounting fault: retain almost all parent cap as an unknown hold.
    with rt.store.db() as db:
        db.execute("UPDATE charges SET settled='499999' WHERE allowance_id=?", (task["allowance_id"],))
    before = rt.store.info(key)
    for _ in range(8):
        rt.conversations.tick()
        rt.learning.tick()
    task = rt.conversations.teaching.get(key, uid)
    assert not any(s["status"] == "accepted" for s in task["execution"]["steps"])
    assert rt.store.info(key) == before
    assert rt.learning.usage(lane="interaction")["calls"] == 0
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants WHERE episode IS NOT NULL").fetchone()[0] == 0


def test_pending_local_query_followup_keeps_original_attempt_and_notifies_both_channels(rig):
    from .test_application import envelope, execute
    from .test_conversations import conversation

    rt, gw = rig
    key, cid, uid = prepared(rt, gw)
    original_id = rt.store.submit(
        key,
        envelope(
            "gap",
            {
                "op": "evaluate",
                "module": "math",
                "expression": {
                    "op": "call",
                    "function": "math.double",
                    "args": {"n": {"op": "literal", "value": 3}},
                },
            },
            limits=rt.limits(),
        ),
    )
    original = execute(rt, key)
    assert original["status"] == "needs_input", original
    # Authored bridge fixture represents an existing durable Ask gap with an executable
    # query. It does not claim the interpreter can typecheck an absent symbol.
    ask = conversation(rt, key, "ask")
    from awm_adm.runtime.protocol import loads

    with rt.store.db(key) as db:
        work = {"id": "authored-gap", "conversation_id": ask}
        db.execute(
            "INSERT INTO chat_work(id,conversation,status,body) VALUES(?,?,?,?)",
            (work["id"], ask, "completed", dumps(work)),
        )
        task = rt.conversations.teaching.get(key, uid)
        gap = {
            "work_id": work["id"],
            "request_id": original_id,
            "context": rt.conversations.context(key),
            "text": "Double three",
            "authority": "none",
        }
        # Test fixture predates the start command; the saved task owns this exact link.
        task["ask_gap"] = gap
        task["specification"]["ask_gap"] = gap
        from awm_adm.learning.service import fingerprint

        task["specification_digest"] = fingerprint(task["specification"])
        rt.conversations.teaching.save(db, task)
    acquire(rt, key, uid)
    command(rt, key, uid, "approve")
    for _ in range(12):
        rt.learning.tick()
        rt.conversations.tick()
        task = rt.conversations.teaching.get(key, uid)
        if (task["execution"].get("followup") or {}).get("status") == "pending":
            break
    followup = task["execution"]["followup"]
    assert followup["request_id"] != original_id
    fresh = execute(rt, key)
    assert fresh["result"]["value"]["value"] == 6
    preserved = rt.store.request(key, original_id)
    assert {k: v for k, v in preserved.items() if k != "current_context"} == {
        k: v for k, v in original.items() if k != "current_context"
    }
    for _ in range(4):
        rt.conversations.tick()
    task = rt.conversations.teaching.get(key, uid)
    run = task["execution"]
    reply(
        rt,
        {
            "packet_digest": run["packet_digest"],
            "accepted_ids": run["summary"]["accepted_ids"],
            "unresolved_ids": [],
            "explanation": "The local follow-up computed six.",
            "authority": "explanation_only",
        },
    )
    task = advance(rt, key, uid, "succeeded")
    assert task["execution"]["summary"]["followup"]["outcome"]["attempt_id"] == fresh["attempt_id"]
    with rt.store.db(key) as db:
        texts = [
            loads(r[0])["text"]
            for r in db.execute("SELECT body FROM chat_turns WHERE conversation=?", (ask,))
        ]
    assert any("Local follow-up" in text and "6" in text for text in texts)


@pytest.mark.parametrize("change", ["cancel", "pause", "policy"])
def test_parent_change_during_admission_blocks_publication(rig, monkeypatch, change):
    rt, gw = rig
    key, _, uid = prepared(rt, gw)
    acquire(rt, key, uid)
    command(rt, key, uid, "approve")
    before = rt.store.info(key)
    compute = rt.learning._compute

    def raced(*args, **kwargs):
        value = compute(*args, **kwargs)
        if args[2] == "learning_admit":
            if change == "policy":
                rt.store.change(key, before["policy_epoch"])
            else:
                command(rt, key, uid, change)
        return value

    monkeypatch.setattr(rt.learning, "_compute", raced)
    rt.learning.tick()
    after = rt.store.info(key)
    assert after["theory_version"] == before["theory_version"]
    assert after["support_root"] == before["support_root"]
    assert not any(
        s["status"] == "accepted" for s in rt.conversations.teaching.get(key, uid)["execution"]["steps"]
    )


def test_stale_candidate_bytes_cannot_reuse_review(rig):
    from awm_adm.runtime.protocol import loads

    rt, gw = rig
    key, _, uid = prepared(rt, gw)
    task = acquire(rt, key, uid)
    receipt = task["execution"]["review"]["receipt_id"]
    with rt.store.db(key) as db:
        data = loads(db.execute("SELECT data FROM learning_receipts WHERE id=?", (receipt,)).fetchone()[0])
        data["package"]["envelope"] = "aW52YWxpZA=="
        db.execute("UPDATE learning_receipts SET data=? WHERE id=?", (dumps(data), receipt))
    with pytest.raises(RuntimeFault, match="Candidate no longer"):
        command(rt, key, uid, "approve")
    assert rt.conversations.teaching.get(key, uid)["status"] == "awaiting_decision"


def test_expired_pause_stops_without_refill(rig, monkeypatch):
    rt, gw = rig
    key, _, uid = prepared(rt, gw)
    command(rt, key, uid, "start")
    command(rt, key, uid, "pause")
    task = rt.conversations.teaching.get(key, uid)
    monkeypatch.setattr(rt.conversations, "now", lambda: task["execution"]["deadline_ms"] + 1)
    rt.conversations.teaching.execution.tick()
    assert rt.conversations.teaching.get(key, uid)["status"] == "exhausted"
    assert rt.learning.usage()["calls"] == 1


def test_review_can_admit_after_active_deadline_without_new_provider_call(rig, monkeypatch):
    rt, gw = rig
    key, _, uid = prepared(rt, gw)
    task = acquire(rt, key, uid)
    before = rt.learning.usage()["calls"]
    now = task["execution"]["deadline_ms"] + 1
    monkeypatch.setattr(rt.conversations, "now", lambda: now)
    monkeypatch.setattr(rt.learning, "now", lambda: now / 1000)
    command(rt, key, uid, "approve")
    rt.learning.tick()
    task = rt.conversations.teaching.get(key, uid)
    assert task["execution"]["steps"][0]["status"] == "accepted"
    for _ in range(4):
        rt.conversations.tick()
    assert rt.learning.usage()["calls"] == before


def test_forged_completion_does_not_hide_accepted_outcome(rig):
    rt, gw = rig
    key, _, uid = prepared(rt, gw)
    acquire(rt, key, uid)
    command(rt, key, uid, "approve")
    for _ in range(9):
        rt.learning.tick()
        rt.conversations.tick()
    task = rt.conversations.teaching.get(key, uid)
    run = task["execution"]
    reply(
        rt,
        {
            "packet_digest": run["packet_digest"],
            "accepted_ids": [],
            "unresolved_ids": [],
            "explanation": "Everything failed",
            "authority": "explanation_only",
        },
    )
    task = advance(rt, key, uid, "succeeded")
    assert task["execution"]["narration_failure"] == "invalid_or_failed_narration"
    assert task["execution"]["summary"]["accepted"]
    assert "narration" not in task["execution"]


def test_independent_partial_success_survives_later_child_exhaustion(rig):
    from copy import deepcopy

    rt, gw = rig

    def extra(plan):
        child = deepcopy(plan["children"][0])
        child["objective"] = "Triple a bounded number"
        header = child["interfaces"].pop("math.double")
        header["returns"]["max"] = 15
        child["interfaces"]["math.triple"] = header
        plan["children"].append(child)

    key, _, uid = prepared(rt, gw, extra)
    acquire(rt, key, uid)
    command(rt, key, uid, "approve")
    for _ in range(6):
        rt.learning.tick()
        rt.conversations.tick()
    for _ in range(2):
        bad = definition()
        bad["result"]["definitions"] = {"math.triple": {"body": {"op": "literal", "value": 9999}}}
        reply(rt, bad)
        for _ in range(5):
            rt.learning.tick()
            rt.conversations.tick()
    task = rt.conversations.teaching.get(key, uid)
    run = task["execution"]
    assert [s["status"] for s in run["steps"]] == ["accepted", "unresolved"], task
    assert run["summary"]["status"] == "partially_succeeded"
    assert len(run["summary"]["accepted"]) == len(run["summary"]["unresolved"]) == 1
    reply(
        rt,
        {
            "packet_digest": run["packet_digest"],
            "accepted_ids": run["summary"]["accepted_ids"],
            "unresolved_ids": run["summary"]["unresolved_ids"],
            "explanation": "Doubling was accepted; tripling remains unresolved.",
            "authority": "explanation_only",
        },
    )
    advance(rt, key, uid, "partially_succeeded")
    result = rt.query(
        key,
        {
            "op": "evaluate",
            "module": "math",
            "expression": {
                "op": "call",
                "function": "math.double",
                "args": {"n": {"op": "literal", "value": 3}},
            },
        },
    )
    assert result["result"]["value"] == 6


def test_simultaneous_tasks_require_fresh_authority_after_first_publication(rig):
    from .test_conversations import conversation, message

    rt, gw = rig
    key, _, first = prepared(rt, gw)
    s = rt.conversations
    second_conversation = conversation(rt, key, "teach")
    allowance = rt.learning.allowances.view(s.teaching.get(key, first)["allowance_id"])
    s.setup(
        key,
        second_conversation,
        {
            "idempotency_key": str(uuid4()),
            "context": s.context(key),
            "price_id": allowance["price_id"],
            "purpose": "teach",
        },
    )
    q = s.get(key, second_conversation)["questions"][0]
    s.message(key, second_conversation, message(rt, key, second_conversation, "$0.50", reply_to=q["id"]))
    p = s.get(key, second_conversation)["proposals"][0]
    s.decide(key, p["id"], decision(p), "owner")
    prepare(rt, key, second_conversation)
    p = s.get(key, second_conversation)["proposals"][0]
    s.decide(key, p["id"], decision(p), "owner")
    second = s.get(key, second_conversation)["tasks"][0]["id"]
    acquire(rt, key, first)
    acquire(rt, key, second)
    command(rt, key, first, "approve")
    rt.learning.tick()
    with pytest.raises(RuntimeFault):
        command(rt, key, second, "approve")
    for _ in range(8):
        s.tick()
        rt.learning.tick()
    assert s.teaching.get(key, second)["status"] == "needs_input"
    assert s.teaching.get(key, first)["execution"]["steps"][0]["status"] == "accepted"
    with rt.store.db(key) as db:
        receipts = list(db.execute("SELECT seq,status FROM learning_receipts ORDER BY seq"))
    assert receipts[0]["status"] == "accepted"
    assert len([r for r in receipts if r["status"] == "accepted"]) == 1


def test_runtime_publishes_conversation_service_before_starting_recovery_worker(tmp_path, monkeypatch):
    from threading import Event

    from awm_adm.conversations.service import Conversations

    from .test_application import configuration

    seen, valid = Event(), []

    def run(service):
        valid.append(getattr(service.runtime, "conversations", None) is service)
        seen.set()

    monkeypatch.setattr(Conversations, "loop", run)
    rt = Runtime(configuration(tmp_path / "startup"))
    try:
        assert seen.wait(2)
        assert valid == [True]
    finally:
        rt.close()


def test_gap_without_executable_query_reports_need_for_ask_clarification(rig):
    rt, gw = rig
    key, _, uid = prepared(rt, gw)
    task = rt.conversations.teaching.get(key, uid)
    command(rt, key, uid, "start")
    task = rt.conversations.teaching.get(key, uid)
    # Authored missing-query bridge; completion must not pretend a query was answered.
    task["ask_gap"] = {"request_id": None}
    task["execution"]["phase"] = "followup"
    task["execution"]["status"] = "running"
    rt.conversations.teaching.execution.followup(key, task)
    saved = rt.conversations.teaching.get(key, uid)
    followup = saved["execution"]["followup"]
    assert followup["status"] == "needs_input"
    assert "no confirmed local query" in followup["text"]
    assert "request_id" not in followup
    assert not rt.store.page(key, "requests")["items"]
