"""Workspace recovery regressions: offline authority, retained preparations and imported history."""

import pytest

from awm_adm.conversations.history import options
from awm_adm.runtime.protocol import RuntimeFault, loads

from .test_application import app_runtime as app_runtime
from .test_application import client
from .test_conversations import decision, message
from .test_learning_service import rig as rig
from .test_luna_price import fund_chat, setup_luna
from .test_sources import ingest, install, lookup, project
from .test_teaching import funded, prepare
from .test_teaching_execution import command


def retained(rt, gw, monkeypatch, *, accepted=False):
    key, cid = funded(rt, gw)
    s = rt.conversations
    prepare(rt, key, cid)
    proposal = s.get(key, cid)["proposals"][0]
    if accepted:
        s.decide(key, proposal["id"], decision(proposal), "owner")
    uid = proposal["payload"]["task_id"]
    task = s.teaching.get(key, uid)
    now = task["budget"]["expires_at_ms"] + 1
    monkeypatch.setattr(s, "now", lambda: now)
    monkeypatch.setattr(rt.learning, "now", lambda: now / 1000)
    return key, cid, uid, proposal


@pytest.mark.parametrize("accepted", [False, True])
def test_renewal_retains_meaning_usage_caps_and_requires_separate_start(rig, monkeypatch, accepted):
    rt, gw = rig
    key, cid, uid, original = retained(rt, gw, monkeypatch, accepted=accepted)
    s, finance = rt.conversations, rt.learning.allowances
    renewal = s.teaching.renewal
    task = s.teaching.get(key, uid)
    before = finance.view(task["allowance_id"])
    usage = rt.learning.usage()
    body = renewal.preview(key, uid)["command"]
    result = renewal.confirm(key, uid, body, "owner")
    assert result["status"] == "renewed"
    assert renewal.confirm(key, uid, body, "owner") == result
    after = finance.view(task["allowance_id"])
    for k in before.keys() - {"state", "expires_at_ms"}:
        assert before[k] == after[k], k
    assert after["expires_at_ms"] == body["expires_at_ms"]
    assert rt.learning.usage() == usage
    task = s.teaching.get(key, uid)
    assert not task.get("execution") and len(task["renewals"]) == 1
    if not accepted:
        p = s.get(key, cid)["proposals"][0]
        assert p["payload"] == original["payload"] and p["id"] != original["id"]
        assert s.decide(key, p["id"], decision(p), "owner")["status"] == "accepted"
    task = s.teaching.get(key, uid)
    assert task["specification"] == original["payload"]["specification"]
    command(rt, key, uid, "start")
    run = s.teaching.get(key, uid)["execution"]
    assert run["deadline_ms"] == body["expires_at_ms"]
    assert rt.learning.usage() == usage


def test_renewal_registry_commit_recovers_once_without_dispatch(rig, monkeypatch):
    rt, gw = rig
    key, cid, uid, _ = retained(rt, gw, monkeypatch)
    renewal = rt.conversations.teaching.renewal
    body = renewal.preview(key, uid)["command"]
    original = renewal.apply

    def crash(*_):
        raise OSError("authored crash after registry commit")

    monkeypatch.setattr(renewal, "apply", crash)
    with pytest.raises(OSError):
        renewal.confirm(key, uid, body, "owner")
    monkeypatch.setattr(renewal, "apply", original)
    usage = rt.learning.usage()
    renewal.recover(key)
    renewal.recover(key)
    assert renewal.confirm(key, uid, body, "owner")["status"] == "renewed"
    assert len(rt.conversations.teaching.get(key, uid)["renewals"]) == 1
    assert len(rt.conversations.get(key, cid)["proposals"]) == 1
    assert rt.learning.usage() == usage


@pytest.mark.parametrize("change", ["context", "duration", "spending", "closed", "unknown", "room"])
def test_renewal_rejects_changed_scope_unknown_usage_and_overcommit(rig, monkeypatch, change):
    rt, gw = rig
    key, _, uid, _ = retained(rt, gw, monkeypatch)
    s = rt.conversations
    renewal = s.teaching.renewal
    body = renewal.preview(key, uid)["command"]
    task = s.teaching.get(key, uid)
    before = s.finance.view(task["allowance_id"])["expires_at_ms"]
    if change == "context":
        body["context"]["policy_epoch"] += 1
    elif change == "duration":
        body["expires_at_ms"] += 3600001
    elif change == "spending":
        body["spending_generation"] += 1
    elif change == "closed":
        s.finance.close(task["allowance_id"], "active")
    elif change == "unknown":
        with rt.store.db() as db, rt.store.transaction(db):
            db.execute(
                "UPDATE charges SET settled=NULL,state='unknown' WHERE allowance_id=?",
                (task["allowance_id"],),
            )
    elif change == "room":
        # Another allocation consumes the room released by the expired task.
        from .test_allowances import fund

        with rt.store.db() as db:
            price = s.finance.price(db, task["budget"]["price_id"])
        fund(
            rt,
            price,
            key,
            scope="task",
            cap=700000,
            max_calls=3,
            max_input_tokens=100000,
            max_output_tokens=20000,
            max_children=4,
        )
    with pytest.raises(RuntimeFault):
        renewal.confirm(key, uid, body, "owner")
    assert s.finance.view(task["allowance_id"])["expires_at_ms"] == before
    assert not s.teaching.get(key, uid).get("renewals")


def test_readiness_reports_remote_off_and_expiry_without_creating_work(rig, tmp_path, monkeypatch):
    rt, gw = rig
    _, price, transport = setup_luna(rt, gw, tmp_path)
    key = rt.create("Readiness fixture")["id"]
    cid = fund_chat(rt, key, price)
    s = rt.conversations
    before = s.details(key, cid)
    rt.learning.configure(
        {"expected_generation": rt.learning.settings()["generation"], "remote_calls_enabled": False}
    )
    view = s.get(key, cid)
    assert view["readiness_issues"][0]["code"] == "remote_calls_disabled"
    assert s.options(key, "ask")["issues"][0]["code"] == "remote_calls_disabled"
    with client(rt) as c:
        response = c.post(
            f"/api/v1/adms/{key}/conversations/{cid}/messages", json=message(rt, key, cid, "Check readiness")
        )
        assert response.status_code == 403
        assert response.json()["code"] == "remote_calls_disabled"
    with pytest.raises(RuntimeFault, match="Remote AI calls are disabled"):
        s.message(key, cid, message(rt, key, cid, "What can you do?"))
    assert s.details(key, cid)["work"] == before["work"]
    assert not transport
    allowance = s.finance.view(view["preferences"]["allowance_id"])
    monkeypatch.setattr(s, "now", lambda: allowance["expires_at_ms"] + 1)
    codes = {i["code"] for i in s.get(key, cid)["readiness_issues"]}
    assert {"remote_calls_disabled", "allowance_expired"} <= codes


def test_imported_history_options_are_local_without_new_source_authority(app_runtime):
    rt = app_runtime
    key = rt.create("Historical metadata")["id"]
    install(rt, key)
    project(rt, key, ingest(rt, key))
    clone = rt.create("Independent copy", snapshot=rt.store.revision(key)["snapshot"])["id"]
    assert rt.sources.policy(clone).get("projection") is None
    before = rt.learning.usage()
    chosen = options(rt.conversations, clone)
    assert chosen["context"] == rt.conversations.context(clone)
    assert chosen["projections"][0]["entities"] == ["site"]
    assert chosen["projections"][0]["predicates"][0]["symbol"] == "site.capacity"
    assert lookup(rt, clone, 2021)["status"] == "succeeded"
    assert rt.learning.usage() == before
    with client(rt) as c:
        response = c.get(f"/api/v1/adms/{clone}/history-options")
        assert response.status_code == 200
        assert response.json() == chosen
    with rt.store.db(clone) as db:
        assert not db.execute("SELECT 1 FROM source_versions").fetchone()
    assert rt.sources.policy(clone).get("projection") is None


def test_renewal_replay_after_adm_commit_never_duplicates_turn(rig, monkeypatch):
    rt, gw = rig
    key, cid, uid, _ = retained(rt, gw, monkeypatch)
    s = rt.conversations
    body = s.teaching.renewal.preview(key, uid)["command"]
    result = s.teaching.renewal.confirm(key, uid, body, "owner")
    before = s.get(key, cid)["items"]
    with rt.store.db() as db, rt.store.transaction(db):
        db.execute(
            "UPDATE operations SET status='committed',result=NULL WHERE id=?", (result["operation_id"],)
        )
    s.teaching.renewal.recover(key)
    assert s.get(key, cid)["items"] == before
    with rt.store.db() as db:
        journal = loads(
            db.execute("SELECT body FROM operations WHERE id=?", (result["operation_id"],)).fetchone()[0]
        )
    assert journal["allowance_before"]["expires_at_ms"] != journal["allowance_after"]["expires_at_ms"]
