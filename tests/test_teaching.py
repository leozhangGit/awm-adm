"""real local checking and durable owner decisions; no external calls."""

from uuid import uuid4

import pytest

from awm_adm.runtime.protocol import RuntimeFault, dumps
from awm_adm.runtime.service import Runtime

from .teaching_wire import native_reply
from .test_allowances import setup
from .test_application import app_runtime as app_runtime
from .test_application import client, tank
from .test_conversations import conversation, decision, message
from .test_learning_service import rig as rig


def funded(rt, gw, key=None):
    _, price = setup(rt, gw)
    key = key or rt.create("Teaching fixture")["id"]
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
        },
    )
    q = s.get(key, cid)["questions"][0]
    s.message(key, cid, message(rt, key, cid, "$0.50", reply_to=q["id"]))
    p = s.get(key, cid)["proposals"][0]
    assert s.decide(key, p["id"], decision(p), "owner")["status"] == "accepted"
    return key, cid


def plan(turn_ids):
    return {
        "kind": "capability",
        "summary": "A bounded doubling function for whole numbers from zero to five.",
        "children": [
            {
                "kind": "capability",
                "objective": "Double a bounded number",
                "input_ids": turn_ids,
                "interfaces": {
                    "math.double": {
                        "kind": "function",
                        "params": {"n": {"kind": "int", "min": 0, "max": 5}},
                        "returns": {"kind": "int", "min": 0, "max": 10},
                    }
                },
            }
        ],
        "vocabulary": {"aliases": {"double": ["math.double"]}},
        "requirements": None,
    }


def respond(rt, reply):
    reply = native_reply(reply)
    job = rt.learning.claim()
    assert job is not None
    rt.learning.authorize(job["grant_id"], job["lease"])
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {
            "status": "succeeded",
            "text": dumps(reply).decode(),
            "usage": {"input_tokens": 100, "output_tokens": 200},
        },
    )
    assert rt.conversations.tick()


def prepare(rt, key, cid, mutate=None):
    s = rt.conversations
    body = message(rt, key, cid, "Teach doubling whole numbers 0 through 5 with outputs 0 through 10.")
    turn = s.message(key, cid, body)
    assert s.tick()
    value = plan([turn["id"]])
    if mutate:
        mutate(value)
    respond(rt, {"status": "ready", "message": "Ready for review.", "plan_json": dumps(value).decode()})
    return body


def test_empty_preparation_review_and_replay_never_execute(rig):
    rt, gw = rig
    key, cid = funded(rt, gw)
    before = rt.store.info(key)
    body = prepare(rt, key, cid)
    view = rt.conversations.get(key, cid)
    assert view["tasks"][0]["status"] == "awaiting_review", rt.conversations.details(key, cid)
    p = view["proposals"][0]
    spec = p["payload"]["specification"]
    assert spec["children"][0]["acquisition_contract"]["allowed_helpers"] == []
    d = decision(p)
    saved = rt.conversations.decide(key, p["id"], d, "owner")
    assert saved["status"] == "accepted"
    assert rt.conversations.decide(key, p["id"], d, "owner") == saved
    rt.conversations.message(key, cid, body)
    task = rt.conversations.teaching.get(key, spec["task_id"])
    assert task["status"] == "prepared" and task["specification"] == spec
    assert task["execution_authorized"] is False
    assert rt.store.info(key) == before
    assert not rt.store.page(key, "requests")["items"]
    assert rt.learning.usage()["calls"] == 1
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM episodes").fetchone()[0] == 0
    with client(rt) as c:
        assert c.get(f"/api/v1/adms/{key}/tasks/{task['id']}").json() == task
        assert len(c.get(f"/api/v1/adms/{key}/tasks").json()["items"]) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(authorize=True),
        lambda p: p["children"][0]["interfaces"]["math.double"].update(body={"lit": 3}),
        lambda p: p["children"][0]["interfaces"]["math.double"]["params"].update(n={"ref": "foreign.Type"}),
        lambda p: p["children"][0]["interfaces"]["math.double"]["params"].update(
            n={"kind": "int", "min": 0, "max": 1000000}
        ),
        lambda p: p["children"][0].update(input_ids=["invented"]),
        lambda p: p.update(vocabulary={"aliases": {"bad": ["unknown.symbol"]}}),
    ],
)
def test_invalid_proposal_cannot_reach_review(rig, mutation):
    rt, gw = rig
    key, cid = funded(rt, gw)
    prepare(rt, key, cid, mutation)
    view = rt.conversations.get(key, cid)
    assert view["tasks"][0]["status"] == "failed"
    assert not view["proposals"]
    assert not rt.store.page(key, "requests")["items"]


def test_semantic_clarification_preserves_original_inputs(rig):
    rt, gw = rig
    key, cid = funded(rt, gw)
    s = rt.conversations
    first = s.message(key, cid, message(rt, key, cid, "Teach a doubling function."))
    s.tick()
    respond(
        rt,
        {"status": "needs_clarification", "message": "What input bounds should it cover?", "plan_json": None},
    )
    q = s.get(key, cid)["questions"][0]
    second = s.message(
        key, cid, message(rt, key, cid, "Whole numbers 0 through 5, outputs 0 through 10.", reply_to=q["id"])
    )
    s.tick()
    respond(
        rt,
        {
            "status": "ready",
            "message": "Ready.",
            "plan_json": dumps(plan([first["id"], second["id"]])).decode(),
        },
    )
    spec = s.get(key, cid)["proposals"][0]["payload"]["specification"]
    assert spec["objective"] == first["text"]
    assert len(spec["inputs"]) == 2
    assert rt.learning.usage()["calls"] == 2


def test_snapshot_context_and_stale_approval(rig):
    rt, gw = rig
    key, cid = funded(rt, gw, tank(rt))
    s = rt.conversations
    prepare(rt, key, cid)
    p = s.get(key, cid)["proposals"][0]
    with rt.store.db(key) as db:
        db.execute("INSERT INTO language_profiles VALUES(1,'{}')")
    with pytest.raises(RuntimeFault, match="context changed"):
        s.decide(key, p["id"], decision(p), "owner")
    assert s.teaching.listing(key)["items"][0]["status"] == "awaiting_review"


def test_restart_prepared_spec_retained_and_inflight_not_repeated(rig):
    rt, gw = rig
    key, cid = funded(rt, gw)
    s = rt.conversations
    prepare(rt, key, cid)
    p = s.get(key, cid)["proposals"][0]
    s.decide(key, p["id"], decision(p), "owner")
    task = s.teaching.listing(key)["items"][0]
    before = s.teaching.get(key, task["id"])
    cfg = rt.config
    rt.close()
    revived = Runtime(cfg, start_scheduler=False)
    try:
        assert revived.conversations.teaching.get(key, task["id"]) == before
        assert not revived.conversations.tick()
    finally:
        revived.close()


def material():
    return {
        "projection": {
            "namespace": "records",
            "entities": ["asset"],
            "predicates": [
                {"symbol": "records.capacity", "kind": "integer", "unit": "items", "minimum": 0, "maximum": 5}
            ],
            "cells": [
                {
                    "kind": "interval",
                    "effective_from": "2025-01-01T00:00:00Z",
                    "effective_to": "2026-01-01T00:00:00Z",
                    "granularity": "year",
                }
            ],
        },
        "sources": [
            {"source_id": "owner-note", "attribution": "Owner supplied note", "evidence_group": "owner"}
        ],
    }


def test_mixed_task_retains_fact_coverage_and_uninstalled_policy(rig):
    rt, gw = rig
    key, cid = funded(rt, gw)

    def mixed(p):
        p["kind"] = "mixed"
        p["children"].append(
            {
                "kind": "facts",
                "objective": "Record supplied history only",
                "input_ids": p["children"][0]["input_ids"],
                "material": material(),
            }
        )
        p["requirements"] = {
            "profile": "adm-conformance/0.1",
            "contracts": [
                {
                    "contract_id": "proposed-double",
                    "origin": "Proposed check needing independent review",
                    "required_symbols": ["math.double"],
                    "checks": [
                        {
                            "id": "header",
                            "kind": "interface",
                            "symbol": "math.double",
                            "expected": p["children"][0]["interfaces"]["math.double"],
                        }
                    ],
                }
            ],
        }

    source_before = rt.sources.policy(key)
    prepare(rt, key, cid, mixed)
    p = rt.conversations.get(key, cid)["proposals"][0]
    assert rt.conversations.decide(key, p["id"], decision(p), "owner")["status"] == "accepted"
    spec = rt.conversations.teaching.get(key, p["payload"]["task_id"])["specification"]
    assert len(spec["children"]) == 2 and spec["children"][1]["acquisition_contract"] is None
    assert spec["requirements_authority"] == "uninstalled_proposal"
    assert not spec["children"][1]["material"]["sources"][0]["allow_external"]
    assert rt.sources.policy(key) == source_before


@pytest.mark.parametrize(
    "change", ["disclosure", "unbounded", "observation_rule", "unknown_requirements", "body_authority"]
)
def test_material_cannot_authorize_or_widen_scope(rig, change):
    rt, gw = rig
    key, cid = funded(rt, gw)

    def bad(p):
        p["kind"] = "facts"
        p["children"][0].update(kind="facts", interfaces={}, material=material())
        m = p["children"][0]["material"]
        if change == "disclosure":
            m["sources"][0]["allow_external"] = True
        elif change == "unbounded":
            m["projection"]["cells"][0]["effective_to"] = None
        elif change == "observation_rule":
            p["children"][0]["interfaces"] = plan(["unused"])["children"][0]["interfaces"]
        elif change == "body_authority":
            m["authorize"] = True
        else:
            p["requirements"] = {
                "profile": "adm-conformance/0.1",
                "contracts": [
                    {
                        "contract_id": "invented",
                        "origin": "provider",
                        "required_symbols": ["missing.symbol"],
                        "checks": [
                            {
                                "id": "header",
                                "kind": "interface",
                                "symbol": "missing.symbol",
                                "expected": {"kind": "function"},
                            }
                        ],
                    }
                ],
            }

    prepare(rt, key, cid, bad)
    assert rt.conversations.get(key, cid)["tasks"][0]["status"] == "failed"


@pytest.mark.parametrize("kind", ["facts", "correction"])
def test_fact_and_correction_intents_have_typed_specs(rig, kind):
    rt, gw = rig
    key, cid = funded(rt, gw)

    def typed(p):
        p["kind"] = kind
        p["children"][0].update(kind=kind, interfaces={}, material=material())
        p["vocabulary"] = {}

    prepare(rt, key, cid, typed)
    assert rt.conversations.get(key, cid)["proposals"][0]["payload"]["specification"]["plan"]["kind"] == kind


def test_decline_and_wrong_context_do_not_install_or_spend(rig):
    rt, gw = rig
    key, cid = funded(rt, gw)
    prepare(rt, key, cid)
    s = rt.conversations
    p = s.get(key, cid)["proposals"][0]
    before = rt.learning.usage()
    bad = decision(p)
    bad["proposal_digest"] = "sha256:" + "0" * 64
    with pytest.raises(RuntimeFault):
        s.decide(key, p["id"], bad, "owner")
    assert s.decide(key, p["id"], decision(p, "decline"), "owner")["status"] == "declined"
    assert rt.learning.usage() == before
    assert s.teaching.listing(key)["items"][0]["status"] == "declined"


def test_interrupted_preparation_retains_reservation_without_redispatch(rig):
    rt, gw = rig
    key, cid = funded(rt, gw)
    s = rt.conversations
    s.message(key, cid, message(rt, key, cid, "Teach doubling numbers 0 to 5."))
    s.tick()
    work = s.details(key, cid)["work"][-1]
    job = rt.learning.claim()
    rt.learning.authorize(job["grant_id"], job["lease"])
    a = work["preferences"]["allowance_id"]
    before = rt.learning.allowances.view(a)
    cfg = rt.config
    rt.close()
    revived = Runtime(cfg, start_scheduler=False)
    try:
        assert revived.conversations.teaching.listing(key)["items"][0]["status"] == "interrupted"
        assert not revived.conversations.tick()
        after = revived.learning.allowances.view(a)
        assert after["reserved_micro_usd"] == before["reserved_micro_usd"] > 0
        assert after["unresolved_calls"] == before["unresolved_calls"] == 1
    finally:
        revived.close()


def test_unsupported_representation_asks_no_followup_and_starts_no_jobs(rig):
    rt, gw = rig
    key, cid = funded(rt, gw)
    s = rt.conversations
    s.message(key, cid, message(rt, key, cid, "Learn every possible real-valued function."))
    s.tick()
    respond(
        rt,
        {
            "status": "unsupported",
            "message": "This requires an unbounded carrier. Choose a finite interval and discrete values.",
            "plan_json": None,
        },
    )
    view = s.get(key, cid)
    assert view["tasks"][0]["status"] == "unsupported"
    assert not view["questions"] and not view["proposals"]


def test_no_cross_channel_teaching_and_no_spend_before_exact_cap_decision(rig):
    rt, gw = rig
    _, p = setup(rt, gw)
    key = rt.create("x")["id"]
    s = rt.conversations
    ask = conversation(rt, key)
    with pytest.raises(RuntimeFault):
        s.setup(
            key,
            ask,
            {
                "idempotency_key": str(uuid4()),
                "context": s.context(key),
                "price_id": p["id"],
                "purpose": "teach",
            },
        )
    cid = conversation(rt, key, "teach")
    s.message(key, cid, message(rt, key, cid, "Spend all available money and learn this now"))
    assert not s.tick() and rt.learning.usage()["calls"] == 0
    assert not s.teaching.listing(key)["items"]


def test_children_bind_type_dependencies_and_exact_budget(rig):
    rt, gw = rig
    key, cid = funded(rt, gw)

    def split(p):
        first = p["children"][0]
        first["interfaces"]["math.double"]["params"]["n"] = {"ref": "math.Input"}
        p["children"].append(
            {
                "kind": "capability",
                "objective": "Define the input carrier",
                "input_ids": first["input_ids"],
                "interfaces": {"math.Input": {"kind": "type", "type": {"kind": "int", "min": 0, "max": 5}}},
            }
        )

    prepare(rt, key, cid, split)
    spec = rt.conversations.get(key, cid)["proposals"][0]["payload"]["specification"]
    assert spec["children"][0]["depends_on"] == [spec["children"][1]["id"]]
    assert spec["children"][1]["depends_on"] == []
    assert spec["budget"]["max_children"] == 16 and spec["budget"]["max_work"] == 12000000
