"""Unchanged rules use local checked candidates, retaining adoption and old evidence."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from awm_adm.engine import Budget, validate_snapshot
from awm_adm.interaction.knowledge import search
from awm_adm.runtime.protocol import pack
from awm_adm.teaching.dependencies import preserve_dependents
from awm_adm.teaching.diagnostics import PreparationError, diagnostic
from awm_adm.teaching.models import ReaffirmingPlan, TemporalPlan
from awm_adm.teaching.provider_format import response_schema
from awm_adm.teaching.reaffirmation import candidate, pins

from .interaction_support import command, plan
from .test_application import app_runtime as app_runtime
from .test_direct_teach import finish_explanation, preparation, pump, task
from .test_learning_service import rig as rig
from .test_teaching_revision import correction, instance, query


def reuse(p):
    p.update(kind="reaffirmation", vocabulary={})
    p["children"][0].update(
        kind="reaffirmation",
        objective="Keep the accepted eligibility rule unchanged",
        interfaces={},
        reuse_symbols=["quota.permits"],
    )


def start(rt, gw, **extra):
    key = rt.create("Independent unchanged rule", snapshot=pack(instance().export_snapshot()))["id"]
    return (
        *preparation(
            rt, gw, key, mutate=reuse, text="Reaffirm the accepted eligibility rule unchanged.", **extra
        ),
    )


@pytest.mark.parametrize("mode", ["backward", "forward"])
def test_reaffirmation_preserves_definitions_old_evidence_and_snapshots_without_acquisition(rig, mode):
    rt, gw = rig
    key = rt.create("Reaffirmation", snapshot=pack(instance().export_snapshot()))["id"]
    if mode == "forward":
        rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    before = rt.store.info(key)
    old = {r["name"]: r for r in search(rt, key, kind="declaration")["items"]}
    extra = {
        "knowledge_intent": {"role": "adopted_rule", "basis": "Agreed plan, section 2"},
        "idempotency_key": "same-reaffirmation",
    }
    key, uid = preparation(
        rt, gw, key, mutate=reuse, text="Keep the eligibility rule exactly as accepted.", **extra
    )
    done = finish_explanation(rt, key, uid)
    assert done["status"] == "succeeded", done
    after = rt.store.info(key)
    assert after["theory_version"] == before["theory_version"]
    assert after["support_root"] != before["support_root"]
    assert after["policy_epoch"] == before["policy_epoch"] and after["mode"] == mode
    assert query(rt, key, "quota.permits", n=2)["value"] is True
    assert query(rt, key, "quota.permits", n=3)["value"] is False
    rows = {r["name"]: r for r in search(rt, key, kind="declaration")["items"]}
    for symbol, row in rows.items():
        assert row["definition"] == old[symbol]["definition"]
        if symbol != "quota.permits":
            assert row["evidence"] == old[symbol]["evidence"]
    for e in old["quota.permits"]["evidence"]:
        assert e in rows["quota.permits"]["evidence"]
    intents = [e["teaching_intent"] for e in rows["quota.permits"]["evidence"] if "teaching_intent" in e]
    assert intents[-1]["inputs"][0]["knowledge_intent"] == extra["knowledge_intent"]
    assert intents[-1]["human_review"] == "not_established"
    summary = done["execution"]["summary"]
    assert summary["reaffirmed"][0]["definitions_unchanged"]
    assert summary["reaffirmed"][0]["acquisition_calls"] == 0
    view = rt.interactions.get(key, uid)
    assert view["teaching"]["admissions"][0]["classification"] == "accepted"
    assert not summary["unresolved"]
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants WHERE episode IS NOT NULL").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == 2  # preparation and narration
    usage = rt.learning.usage()
    replay = rt.interactions.submit(
        key, "teach", {"text": "Keep the eligibility rule exactly as accepted.", **extra}
    )
    assert replay["id"] == uid
    assert rt.learning.usage() == usage and rt.store.info(key) == after
    copy = rt.create("Portable reaffirmation", snapshot=deepcopy(rt.store.snapshot(key)))["id"]
    copied = {r["name"]: r for r in search(rt, copy, kind="declaration")["items"]}
    assert copied["quota.permits"]["evidence"] == rows["quota.permits"]["evidence"]


@pytest.mark.parametrize("change", ["cancel", "pause", "policy"])
def test_reaffirmation_fences_local_publication(rig, monkeypatch, change):
    rt, gw = rig
    key, uid = start(rt, gw)
    before = rt.store.info(key)
    compute = rt.learning._compute
    raced = []

    def interrupted(*args, **kwargs):
        result = compute(*args, **kwargs)
        if args[2] == "learning_admit" and not raced:
            raced.append(True)
            if change == "policy":
                rt.store.change(key, before["policy_epoch"])
            else:
                command(rt, key, uid, change)
        return result

    monkeypatch.setattr(rt.learning, "_compute", interrupted)
    for _ in range(12):
        rt.learning.tick()
        rt.conversations.tick()
    assert raced
    assert rt.store.info(key)["support_root"] == before["support_root"]
    assert task(rt, key, uid)["execution"]["steps"][0]["status"] != "accepted"
    if change == "pause":
        command(rt, key, uid, "resume")
        done = finish_explanation(rt, key, uid)
        assert done["status"] == "succeeded"
        with rt.store.db(key) as db:
            assert db.execute("SELECT count(*) FROM learning_receipts").fetchone()[0] == 1


def test_pins_reject_unknown_duplicate_and_overlap_with_changed_dependents():
    model = instance().model
    p = plan(["turn"])
    reuse(p)
    p = ReaffirmingPlan.model_validate(p).model_dump()
    assert pins(model, p, Budget())[0] == {"quota.permits": model.index["quota.permits"]}
    changed = deepcopy(p)
    changed["children"][0]["reuse_symbols"] = ["unknown.rule"]
    with pytest.raises(PreparationError, match="unknown symbol"):
        pins(model, changed, Budget())
    changed = deepcopy(p)
    changed["children"].append(deepcopy(changed["children"][0]))
    with pytest.raises(PreparationError, match="twice"):
        pins(model, changed, Budget())
    rev = plan(["turn"])
    correction(rev)
    changed = deepcopy(p)
    changed["kind"] = "mixed"
    changed["children"].extend(rev["children"])
    preserve_dependents(model, changed, Budget())
    with pytest.raises(PreparationError, match="another child"):
        pins(model, changed, Budget())


def test_changed_pin_cannot_construct_a_reaffirmation_candidate():
    checked = validate_snapshot(instance().export_snapshot())
    with pytest.raises(Exception, match="changed since preparation"):
        candidate(checked, {"quota.permits": "sha256:" + "0" * 64}, {"inputs": []}, "candidate", Budget())


@pytest.mark.parametrize(
    "case,rule",
    [
        ("empty", "empty_teaching_child"),
        ("duplicate", "duplicate_reuse_symbol"),
        ("interfaces", "reaffirmation_shape"),
        ("other_kind", "unexpected_reuse_symbols"),
    ],
)
def test_shape_failures_have_safe_explanations(case, rule):
    p = plan(["turn"])
    if case == "empty":
        p["children"][0]["interfaces"] = {}
    else:
        reuse(p)
        if case == "duplicate":
            p["children"][0]["reuse_symbols"] *= 2
        elif case == "interfaces":
            p["children"][0]["interfaces"] = {"private.secret": {"kind": "function"}}
        else:
            p["children"][0]["kind"] = "capability"
    with pytest.raises(ValidationError) as err:
        ReaffirmingPlan.model_validate(p)
    value = diagnostic("plan", "invalid_fields", err.value)
    assert value["issues"][0]["rule"] == rule
    assert "private.secret" not in json.dumps(value)
    assert value["issues"][0]["hint"]


def test_old_plan_still_rejects_empty_child_and_new_schema_is_published():
    p = plan(["turn"])
    p["children"][0]["interfaces"] = {}
    with pytest.raises(ValidationError) as err:
        TemporalPlan.model_validate(p)
    assert diagnostic("plan", "invalid_fields", err.value)["issues"][0]["rule"] == "empty_teaching_child"
    from pathlib import Path

    for temporal, suffix in ((True, ""), (False, "legacy-")):
        schema = response_schema(temporal_evidence=temporal, assessed=True, reaffirmation=True)
        path = Path(__file__).parents[1] / "contracts" / f"teaching-{suffix}reaffirmation-reply.schema.json"
        assert schema == json.loads(path.read_text())
        assert schema["properties"]["profile"]["enum"] == [f"awm-adm-teaching-reply/{8 if temporal else 9}"]


def test_mixed_reaffirmation_and_failed_new_rule_reports_partial_without_losing_reaffirmation(rig):
    from .interaction_support import definition, reply
    from .test_direct_teach import has_ready

    rt, gw = rig
    key = rt.create("Mixed knowledge", snapshot=pack(instance().export_snapshot()))["id"]
    before = rt.store.info(key)

    def mixed(p):
        new = deepcopy(p["children"][0])
        reuse(p)
        p["kind"] = "mixed"
        p["children"].append(new)

    key, uid = preparation(rt, gw, key, mutate=mixed)
    for _ in range(2):
        pump(rt, key, uid, lambda t: has_ready(rt))
        bad = definition()
        bad["result"]["definitions"]["math.double"]["body"] = {"op": "literal", "value": 9999}
        reply(rt, bad)
    done = finish_explanation(rt, key, uid)
    assert done["status"] == "partially_succeeded"
    summary = done["execution"]["summary"]
    assert len(summary["accepted"]) == len(summary["reaffirmed"]) == len(summary["unresolved"]) == 1
    assert rt.store.info(key)["theory_version"] == before["theory_version"]
    assert rt.store.info(key)["support_root"] != before["support_root"]
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants WHERE episode IS NOT NULL").fetchone()[0] == 2


def test_empty_work_item_stops_with_actionable_diagnostic_before_configuration(rig):
    rt, gw = rig
    key = rt.create("Invalid empty work")["id"]
    before = rt.store.info(key)

    def empty(p):
        p["children"][0]["interfaces"] = {}

    key, uid = preparation(rt, gw, key, mutate=empty)
    result = rt.interactions.get(key, uid)
    assert result["status"] == "failed"
    assert result["failure_diagnostics"]["issues"][0]["rule"] == "empty_teaching_child"
    assert rt.store.info(key) == before
    assert not task(rt, key, uid)["execution_authorized"]
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM episodes").fetchone()[0] == 0


def test_local_reaffirmation_cannot_bypass_independent_requirements():
    from awm_adm.engine import Instance
    from awm_adm.engine.acquisition import validate_contract
    from awm_adm.learning.compute import compute, transport
    from awm_adm.teaching.intent import capture
    from awm_adm.teaching.reaffirmation import headers

    base = instance()
    checked = validate_snapshot(base.export_snapshot())
    selected = dict(base.model.index)
    intent = capture(
        {
            "id": "t",
            "conversation_id": "c",
            "created_at_ms": 1,
            "inputs": [{"id": "i", "text": "Retain the rule"}],
        },
        {"kind": "reaffirmation", "objective": "Retain rule", "input_ids": ["i"]},
    )
    package, _ = candidate(checked, selected, intent, "receipt", Budget())
    # The current owner requires a result inconsistent with the unchanged rule.
    policy = {
        "profile": "adm-conformance/0.1",
        "contracts": [
            {
                "contract_id": "independent",
                "origin": "Independent owner fixture",
                "required_symbols": ["quota.permits"],
                "checks": [
                    {
                        "id": "blocked",
                        "kind": "value",
                        "params": {},
                        "expression": {
                            "op": "call",
                            "function": "quota.permits",
                            "args": {"n": {"op": "literal", "value": 3}},
                        },
                        "expected": {"op": "literal", "value": True},
                    }
                ],
            }
        ],
    }
    # Install requirements on a policy-free empty instance, then supply a candidate
    # computed from the other base. Admission must refuse the policy violation.
    current = Instance(policy=policy)
    contract = validate_contract(
        {
            "profile": "adm-acquisition/1",
            "required_symbols": list(selected),
            "allowed_helpers": [],
            "interfaces": headers(base.model, selected),
            "allowed_retractions": [],
            "max_declarations": 32,
            "max_bytes": 65536,
        }
    )
    value = compute(
        {
            "operation": "learning_admit",
            "snapshot": pack(base.export_snapshot()),
            "current_snapshot": pack(current.export_snapshot()),
            "context": current.info(),
            "body": {"task": {"acquisition_contract": contract}, "construction": False},
            "package": transport(package),
            "receipt_sequence": 1,
            "reaffirmation": selected,
        },
        Budget(),
    )
    assert value["status"] == "rejected"
    assert value["decision"]["report"]["error"]["code"] == "conformance_failed"
