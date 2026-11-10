"""Workspace tests: real SQLite/gateway boundaries, synthetic responses only."""

import base64
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from awm_adm.conversations.service import money
from awm_adm.runtime.protocol import RuntimeFault, loads
from awm_adm.runtime.service import Runtime

from .test_allowances import setup
from .test_application import app_runtime as app_runtime
from .test_application import client
from .test_learning_service import dispatch
from .test_learning_service import rig as rig


def conversation(rt, key, channel="ask"):
    return rt.conversations.create(key, {"idempotency_key": str(uuid4()), "channel": channel})["id"]


def message(rt, key, cid, text="Hello", **kw):
    view = rt.conversations.get(key, cid)
    return {
        "idempotency_key": str(uuid4()),
        "channel": view["channel"],
        "context": view["context"],
        "text": text,
        **kw,
    }


def propose(rt, key, cid, price):
    s = rt.conversations
    s.setup(key, cid, {"idempotency_key": str(uuid4()), "context": s.context(key), "price_id": price["id"]})
    q = s.get(key, cid)["questions"][0]
    s.message(key, cid, message(rt, key, cid, "$0.50", reply_to=q["id"]))
    return s.get(key, cid)["proposals"][0]


def decision(proposal, answer="accept"):
    return {
        "idempotency_key": str(uuid4()),
        "proposal_id": proposal["id"],
        "proposal_digest": proposal["payload_digest"],
        "context": proposal["context"],
        "answer": answer,
    }


def funded(rt, gw, *, reply=None):
    _, p = setup(
        rt, gw, replies=[reply or {"kind": "clarification", "text": "Which time period do you mean?"}]
    )
    key = rt.create("workspace")["id"]
    cid = conversation(rt, key)
    prop = propose(rt, key, cid, p)
    d = rt.conversations.decide(key, prop["id"], decision(prop), "owner")
    assert d["status"] == "accepted"
    return key, cid, p


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$0.50", 500000),
        ("0.000001 USD", 1),
        ("about $1", None),
        ("$1–$2", None),
        ("yes", None),
        ("1e2", None),
        ("-1", None),
        ("1001", None),
        ("0", None),
        ("1.0000001", None),
    ],
)
def test_exact_bootstrap_money(text, expected):
    assert money(text) == expected


def test_atomic_message_replay_channels_context_and_restart(app_runtime):
    rt = app_runtime
    key = rt.create("one")["id"]
    other = rt.create("two")["id"]
    ask, teach = conversation(rt, key), conversation(rt, key, "teach")
    body = message(rt, key, ask, "owner data <script>alert(1)</script>")
    with ThreadPoolExecutor(4) as pool:
        turns = list(pool.map(lambda _: rt.conversations.message(key, ask, body), range(8)))
    assert len({v["id"] for v in turns}) == 1
    assert len(rt.conversations.get(key, ask)["items"]) == 3
    assert len(rt.conversations.get(key, teach)["items"]) == 1
    for target, changed in ((ask, {**body, "text": "changed"}), (teach, body)):
        with pytest.raises(RuntimeFault):
            rt.conversations.message(key, target, changed)
    with pytest.raises(RuntimeFault):
        rt.conversations.get(other, ask)
    before = rt.conversations.details(key, ask)
    config = rt.config
    rt.close()
    revived = Runtime(config, start_scheduler=False)
    try:
        assert revived.conversations.details(key, ask) == before
        assert revived.conversations.message(key, ask, body) == turns[0]
        assert revived.learning.usage()["calls"] == 0
    finally:
        revived.close()


def test_bounded_provider_context_and_exact_question_binding(rig):
    rt, gw = rig
    key, cid, _ = funded(rt, gw)
    teach = conversation(rt, key, "teach")
    rt.conversations.message(key, teach, message(rt, key, teach, "SECRET OTHER CHANNEL"))
    body = message(rt, key, cid, "How much can I borrow?")
    rt.conversations.message(key, cid, body)
    assert rt.conversations.tick()
    item = rt.conversations.get(key, cid)["work"][0]
    assert item["status"] == "awaiting_provider"
    with rt.store.db() as db:
        grant = loads(db.execute("SELECT body FROM grants WHERE id=?", (item["grant_id"],)).fetchone()[0])
    wire = loads(base64.b64decode(grant["wire"]))
    assert "SECRET OTHER CHANNEL" not in str(wire)
    assert grant["purpose"] == "clarification"
    dispatch(rt, gw)
    assert rt.conversations.tick()
    view = rt.conversations.get(key, cid)
    assert view["work"][0]["status"] == "needs_input"
    assert view["questions"][0]["question"] == "Which time period do you mean?"
    assert rt.learning.usage()["calls"] == 1
    rt.conversations.message(key, cid, body)
    assert rt.learning.usage()["calls"] == 1
    with pytest.raises(RuntimeFault):
        rt.conversations.message(key, cid, message(rt, key, cid, "2026", reply_to="wrong"))
    reply = message(rt, key, cid, "2026", reply_to=view["questions"][0]["id"])
    rt.conversations.message(key, cid, reply)
    assert rt.conversations.tick()
    work = rt.conversations.details(key, cid)["work"][-1]
    assert work["question"] == "Which time period do you mean?"
    assert len(work["selected_context"]) <= 6
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 0


def test_authority_ambiguity_and_replayed_decision(rig):
    rt, gw = rig
    _, p = setup(rt, gw)
    key = rt.create("decisions")["id"]
    cid = conversation(rt, key)
    s = rt.conversations
    s.setup(key, cid, {"idempotency_key": "setup", "context": s.context(key), "price_id": p["id"]})
    q = s.get(key, cid)["questions"][0]
    s.message(key, cid, message(rt, key, cid, "maybe $1 or $2", reply_to=q["id"]))
    assert not s.get(key, cid)["proposals"]
    assert not rt.learning.allowances.listing("allowances")["items"]
    q2 = s.get(key, cid)["questions"][0]
    with pytest.raises(RuntimeFault):
        s.message(key, cid, message(rt, key, cid, "$0.50", reply_to=q["id"]))
    s.message(key, cid, message(rt, key, cid, "$0.50", reply_to=q2["id"]))
    prop = s.get(key, cid)["proposals"][0]
    with pytest.raises(RuntimeFault):
        s.message(key, cid, message(rt, key, cid, "yes"))
    d = decision(prop)
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: s.decide(key, prop["id"], d, "owner"), range(8)))
    assert len({r["id"] for r in results}) == 1
    assert len(rt.learning.allowances.listing("allowances")["items"]) == 1
    assert rt.learning.usage()["calls"] == 0
    assert s.details(key, cid)["decisions"][0]["principal_id"] == "owner"


def test_stale_proposal_and_vocabulary_fences(rig):
    rt, gw = rig
    _, p = setup(rt, gw)
    key = rt.create("fences")["id"]
    cid = conversation(rt, key)
    prop = propose(rt, key, cid, p)
    with rt.store.db(key) as db:
        db.execute("INSERT INTO language_profiles VALUES(1,'{}')")
    with pytest.raises(RuntimeFault):
        rt.conversations.decide(key, prop["id"], decision(prop), "owner")
    assert not rt.learning.allowances.listing("allowances")["items"]


def test_provider_cannot_invent_decision_or_raise_cap(rig):
    rt, gw = rig
    key, cid, _ = funded(rt, gw, reply={"kind": "allowance", "text": "approved", "cap_micro_usd": 99999999})
    rt.conversations.message(key, cid, message(rt, key, cid))
    rt.conversations.tick()
    dispatch(rt, gw)
    rt.conversations.tick()
    details = rt.conversations.details(key, cid)
    assert details["work"][0]["status"] == "failed"
    assert len(details["decisions"]) == 1
    assert details["allowance"]["cap_micro_usd"] == 500000


def test_pending_restart_retains_usage_never_repeats(rig):
    rt, gw = rig
    key, cid, _ = funded(rt, gw)
    rt.conversations.message(key, cid, message(rt, key, cid))
    rt.conversations.tick()
    lease = rt.learning.claim()
    rt.learning.authorize(lease["grant_id"], lease["lease"])
    config = rt.config
    rt.close()
    revived = Runtime(config, start_scheduler=False)
    try:
        assert revived.conversations.get(key, cid)["work"][0]["status"] == "interrupted"
        assert not revived.conversations.tick()
        assert not revived.learning.claim()
        assert revived.conversations.details(key, cid)["allowance"]["reserved_micro_usd"] > 0
    finally:
        revived.close()


def test_routes_are_owner_only_and_inputs_are_closed(app_runtime):
    rt = app_runtime
    key = rt.create("api")["id"]
    with client(rt) as c:
        base = f"/api/v1/adms/{key}"
        response = c.post(base + "/conversations", json={"idempotency_key": "c", "channel": "ask"})
        assert response.status_code == 201
        cid = response.json()["id"]
        path = base + f"/conversations/{cid}"
        assert c.get(path).status_code == 200
        assert c.get(path + "?limit=101").status_code == 422
        assert (
            c.post(path + "/messages", json={**message(rt, key, cid), "author": "assistant"}).status_code
            == 422
        )
        assert c.post(path + "/messages", json=message(rt, key, cid, "é" * 8193)).status_code == 422
        token = c.app.state.authority.issue(adms=[key], permissions=["read", "submit"])
        c.headers["Authorization"] = "Bearer " + token["token"]
        assert c.get(path).status_code == 403
        assert c.post(path + "/messages", json=message(rt, key, cid)).status_code == 403


def test_decision_handoff_recovers_allocated_allowance_once(rig, monkeypatch):
    rt, gw = rig
    _, price = setup(rt, gw)
    key = rt.create("handoff")["id"]
    cid = conversation(rt, key)
    proposal = propose(rt, key, cid, price)
    body = decision(proposal)
    create = rt.learning.allowances.create

    def interrupted(value):
        create(value)
        raise OSError("Authored interruption after committed ledger allocation")

    monkeypatch.setattr(rt.learning.allowances, "create", interrupted)
    with pytest.raises(OSError):
        rt.conversations.decide(key, proposal["id"], body, "owner")
    assert len(rt.learning.allowances.listing("allowances")["items"]) == 1
    cfg = rt.config
    rt.close()
    new = Runtime(cfg, start_scheduler=False)
    try:
        assert len(new.learning.allowances.listing("allowances")["items"]) == 1
        assert new.conversations.details(key, cid)["decisions"][0]["status"] == "accepted"
        assert new.conversations.decide(key, proposal["id"], body, "owner")["status"] == "accepted"
        assert new.learning.usage()["calls"] == 0
    finally:
        new.close()


def test_metadata_is_not_content_and_cannot_leak_to_other_model(app_runtime):
    rt = app_runtime
    key, other = rt.create("attachments")["id"], rt.create("other")["id"]
    cid = conversation(rt, key, "teach")
    from awm_adm.learning.service import fingerprint
    from awm_adm.runtime.protocol import dumps

    value = {
        "idempotency_key": "meta",
        "name": "notes.md",
        "media_type": "text/markdown",
        "byte_count": 123,
        "content_digest": "sha256:" + "1" * 64,
    }
    meta = {**value, "id": str(uuid4()), "content_stored": False, "status": "metadata_only"}
    # Existing records retain their meaning after the public creation endpoint is retired.
    with rt.store.db(key) as db:
        db.execute(
            "INSERT INTO chat_attachments VALUES(?,?,?,?)",
            (meta["id"], value["idempotency_key"], fingerprint(value), dumps(meta)),
        )
    rt.conversations.message(key, cid, message(rt, key, cid, "Learn from this", attachment_ids=[meta["id"]]))
    details = rt.conversations.details(key, cid)
    assert details["attachments"][0]["content_stored"] is False
    assert not details["work"]
    other_cid = conversation(rt, other)
    with pytest.raises(RuntimeFault):
        rt.conversations.message(other, other_cid, message(rt, other, other_cid, attachment_ids=[meta["id"]]))


def test_dispatch_fenced_by_changed_vocabulary_and_context_selection(rig):
    rt, gw = rig
    key, cid, _ = funded(rt, gw)
    rt.conversations.message(key, cid, message(rt, key, cid, "Do something"))
    rt.conversations.tick()
    with rt.store.db(key) as db:
        db.execute("INSERT INTO language_profiles VALUES(1,'{}')")
    assert rt.learning.claim() is None
    rt.conversations.tick()
    assert rt.conversations.get(key, cid)["work"][0]["status"] == "failed"
    with rt.store.db(key) as db:
        assert rt.conversations.selected_context(db, cid, rt.conversations.context(key)) == []
    assert rt.learning.usage()["calls"] == 0


def test_expired_proposal_can_be_replaced_without_acceptance(rig):
    rt, gw = rig
    _, price = setup(rt, gw)
    key = rt.create("expired")["id"]
    cid = conversation(rt, key)
    prop = propose(rt, key, cid, price)
    old_now = rt.learning.now()
    rt.learning.now = lambda: old_now + 601
    with pytest.raises(RuntimeFault):
        rt.conversations.decide(key, prop["id"], decision(prop), "owner")
    rt.conversations.setup(
        key,
        cid,
        {"idempotency_key": "new-setup", "context": rt.conversations.context(key), "price_id": price["id"]},
    )
    assert not rt.conversations.get(key, cid)["proposals"]
    assert not rt.learning.allowances.listing("allowances")["items"]


def test_context_byte_bound_and_pagination(app_runtime):
    rt = app_runtime
    key = rt.create("pages")["id"]
    cid = conversation(rt, key)
    for i in range(8):
        rt.conversations.message(key, cid, message(rt, key, cid, str(i) + "é" * 2000))
    with rt.store.db(key) as db:
        chosen = rt.conversations.selected_context(db, cid, rt.conversations.context(key))
    assert len(chosen) == 1
    assert [r["text"][0] for r in chosen] == ["7"]
    first = rt.conversations.get(key, cid, limit=5)
    second = rt.conversations.get(key, cid, after=first["next_cursor"], limit=5)
    assert not {t["id"] for t in first["items"]} & {t["id"] for t in second["items"]}
    events = rt.store.events(key)["items"]
    assert all(e["kind"] == "conversation.turn" for e in events)


def test_saved_v2_result_links_never_inherit_execution_consent(app_runtime):
    from .test_application import execute

    rt = app_runtime
    key = rt.create("links")["id"]
    cid = conversation(rt, key)
    turn = rt.conversations.message(key, cid, message(rt, key, cid, "Reference this result"))
    request = rt.coordinator.submit(key, {"idempotency_key": "local", "query": {"op": "capabilities"}})
    done = execute(rt, key)
    body = {
        "idempotency_key": "link",
        "turn_id": turn["id"],
        "kind": "result",
        "resource_id": done["result"]["result_id"],
    }
    linked = rt.conversations.link(key, cid, body)
    assert linked["binding"]["revision_id"] == request["revision_id"]
    assert rt.conversations.link(key, cid, body) == linked
    assert linked["authority"] == "none"
    assert rt.learning.usage()["calls"] == 0
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 1
    other = conversation(rt, key, "teach")
    with pytest.raises(RuntimeFault):
        rt.conversations.link(key, other, {**body, "idempotency_key": "cross"})


def test_paired_restore_preserves_turns_and_disables_funding(rig, tmp_path):
    from awm_adm.operations.backup import backup, restore

    from .test_application import configuration

    rt, gw = rig
    key, cid, _ = funded(rt, gw)
    rt.conversations.message(key, cid, message(rt, key, cid))
    rt.conversations.tick()
    dispatch(rt, gw)
    rt.conversations.tick()
    before = rt.conversations.details(key, cid)
    app_path, gateway_path = rt.store.root, gw.store.root
    rt.close()
    gw.store.close()
    bundle, restored = tmp_path / "bundle", tmp_path / "restored"
    backup(app_path, gateway_path, bundle)
    restore(bundle, restored)
    new = Runtime(configuration(restored / "app"), start_scheduler=False)
    try:
        after = new.conversations.details(key, cid)
        assert before["turns"] == after["turns"]
        assert before["decisions"] == after["decisions"]
        assert before["provider_usage"] == after["provider_usage"]
        assert not new.learning.allowances.settings()["enabled"]
        assert new.conversations.get(key, cid)["readiness"] == "needs_setup"
        assert not new.learning.claim()
    finally:
        new.close()


def test_runtime_records_match_core_contracts(rig):
    from awm_adm.conversations.models import MessageInput

    from .test_workflow_contracts import oracle

    rt, gw = rig
    key, cid, _ = funded(rt, gw)
    body = MessageInput.model_validate(message(rt, key, cid)).model_dump()
    # The core oracle remains an immutable specification baseline. Optional disclosure
    # is validated by the live OpenAPI/Pydantic contract and intake tests.
    assert body.pop("disclose_attachments") is False
    oracle.validate("MessageInput", body)
    rt.conversations.message(key, cid, body)
    details = rt.conversations.details(key, cid)
    for turn in details["turns"]:
        oracle.validate("Turn", turn)
    for proposal in details["proposals"]:
        oracle.validate("Proposal", {k: v for k, v in proposal.items() if k not in {"payload", "status"}})
    for record in details["decisions"]:
        oracle.validate("DecisionRecord", record)
