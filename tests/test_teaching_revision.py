"""General revision behavior through recorded preparation, acquisition and admission."""

from copy import deepcopy

import pytest

from awm_adm.engine import Budget, Instance, validate_snapshot
from awm_adm.engine.admission import dependent_closure
from awm_adm.engine.errors import InvalidIR
from awm_adm.language.models import Vocabulary
from awm_adm.runtime.compute import compute
from awm_adm.runtime.protocol import RuntimeFault, dumps, pack, unpack
from awm_adm.teaching.dependencies import preserve_dependents
from awm_adm.teaching.models import Plan

from .interaction_support import reply
from .ported.helpers import BOOL, call, function, integer, literal, operator, variable
from .ported.provider_fixtures import wire_expression
from .test_application import app_runtime as app_runtime
from .test_direct_teach import finish_explanation, has_ready, preparation, pump, task
from .test_learning_service import rig as rig


def instance(prefix="quota", invariant=False):
    declarations = {
        prefix + ".ceiling": function({}, integer(0, 5), literal(2)),
        prefix + ".permits": function(
            {"n": integer(0, 5)},
            BOOL,
            operator("le", variable("n"), call(prefix + ".ceiling")),
        ),
        prefix + ".empty_ok": function({}, BOOL, call(prefix + ".permits", n=literal(0))),
    }
    if invariant:
        declarations[prefix + ".bounded"] = {
            "kind": "assertion",
            "params": {},
            "body": operator("le", call(prefix + ".ceiling"), literal(2)),
        }
    return Instance({"profile": "finite-v0", "declarations": declarations})


def correction(p, prefix="quota"):
    original = p["children"][0]
    p.update(kind="correction", vocabulary={})
    original.update(
        kind="correction",
        objective="Raise the ceiling to three while keeping dependent definitions",
        interfaces={prefix + ".ceiling": {"kind": "function", "params": {}, "returns": integer(0, 5)}},
    )


def update(prefix="quota", tamper=False, invariant=False, retain=True):
    definitions = {prefix + ".ceiling": {"body": wire_expression(literal(3))}}
    if retain:
        definitions.update({prefix + ".permits": None, prefix + ".empty_ok": None})
    if invariant:
        definitions[prefix + ".bounded"] = None
    if tamper:
        definitions[prefix + ".permits"] = {"body": wire_expression(literal(True))}
    return {
        "format": "adm-construction/1",
        "result": {
            "status": "draft",
            "definitions": definitions,
            "declarations": [],
            "discard": [],
            "retractions": [],
            "summary": "Authored revision",
        },
    }


def query(rt, key, symbol, **args):
    return rt.query(
        key,
        {
            "op": "evaluate",
            "module": symbol.rsplit(".", 1)[0],
            "expression": call(symbol, **{k: literal(v) for k, v in args.items()}),
        },
    )["result"]


def setup(rt, prefix="quota", invariant=False):
    inst = instance(prefix, invariant)
    key = rt.create("Revision fixture", snapshot=pack(inst.export_snapshot()))["id"]
    vocabulary = Vocabulary(
        aliases={"ceiling": [prefix + ".ceiling"], "permitted": [prefix + ".permits"]},
        parameter_units={prefix + ".permits": {"n": "items"}},
        parameter_roles={prefix + ".permits": {"n": "value"}},
    ).model_dump()
    rt.language.set_vocabulary(
        key,
        {
            "expected_revision": rt.store.info(key)["revision_id"],
            "expected_generation": 0,
            "vocabulary": vocabulary,
        },
    )
    return key, vocabulary


@pytest.mark.parametrize("prefix", ["quota", "inventory"])
def test_forward_preserves_transitive_dependents_and_backward_still_refuses(rig, prefix):
    rt, gw = rig
    key, vocabulary = setup(rt, prefix)
    before = rt.store.info(key)
    key, uid = preparation(rt, gw, key, mutate=lambda p: correction(p, prefix))
    pump(rt, key, uid, lambda _: has_ready(rt))
    reply(rt, update(prefix))
    rejected = finish_explanation(rt, key, uid)
    assert rejected["status"] == "failed"
    assert rt.store.info(key)["revision_id"] == before["revision_id"]
    rt.store.change(key, before["policy_epoch"], mode="forward")
    key, uid = preparation(rt, gw, key, mutate=lambda p: correction(p, prefix))
    child = task(rt, key, uid)["specification"]["children"][0]
    assert set(child["preserve_declarations"]) == {prefix + ".permits", prefix + ".empty_ok"}
    assert set(child["acquisition_contract"]["required_symbols"]) == {
        prefix + ".ceiling",
        prefix + ".permits",
        prefix + ".empty_ok",
    }
    pump(rt, key, uid, lambda _: has_ready(rt))
    reply(rt, update(prefix))  # Provider supplies only the requested change.
    done = finish_explanation(rt, key, uid)
    assert done["status"] == "succeeded"
    summary = done["execution"]["summary"]
    assert summary["unresolved"] == []
    assert summary["checked_changes"][0]["effects"]["removed"] == []
    assert set(summary["checked_changes"][0]["effects"]["replaced"]) == {
        prefix + ".ceiling",
        prefix + ".permits",
        prefix + ".empty_ok",
    }
    changes = summary["changes"]
    assert changes["complete"]
    entries = {e["symbol"]: e for e in changes["entries"]}
    assert entries[prefix + ".ceiling"]["kind"] == "definition_changed"
    assert "returns 2" in entries[prefix + ".ceiling"]["before"]["text"]
    assert "returns 3" in entries[prefix + ".ceiling"]["after"]["text"]
    for suffix in (".permits", ".empty_ok"):
        entry = entries[prefix + suffix]
        assert entry["kind"] == "preserved_dependent"
        assert entry["before"]["definition_digest"] == entry["after"]["definition_digest"]
        assert entry["before_declaration"] != entry["after_declaration"]
        assert entry["revision_id"] == rt.store.info(key)["revision_id"]
    view = rt.interactions.get(key, uid)
    assert "unchanged" in view["outcome_label"]
    assert "Forward mode remains active" in view["outcome_label"]
    assert view["teaching"]["admissions"][0]["effects"]["change_report"]["complete"]
    checked = validate_snapshot(unpack(rt.store.revision(key)["snapshot"]))["model"]
    original = instance(prefix).model
    for symbol in child["preserve_declarations"]:
        assert checked.document()["declarations"][symbol] == original.document()["declarations"][symbol]
        assert (
            checked.index[symbol] != original.index[symbol]
        )  # New bindings/evidence, not stale proof reuse.
    assert query(rt, key, prefix + ".ceiling")["value"] == 3
    assert query(rt, key, prefix + ".permits", n=3)["value"] is True
    assert query(rt, key, prefix + ".permits", n=4)["value"] is False
    assert query(rt, key, prefix + ".empty_ok")["value"] is True
    assert rt.language.catalog(key)["vocabulary"] == vocabulary
    assert rt.store.info(key)["mode"] == "forward"
    assert (
        rt.store.revision(key, before["revision_id"])["context"]["theory_version"] == before["theory_version"]
    )


@pytest.mark.parametrize("kind", ["provider_rewrite", "invalid_preserved_assertion"])
def test_preservation_never_accepts_provider_rewrite_or_invalid_dependent(rig, kind):
    rt, gw = rig
    key, _ = setup(rt, invariant=kind == "invalid_preserved_assertion")
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    before = rt.store.info(key)
    key, uid = preparation(rt, gw, key, mutate=correction)
    for _ in range(2):
        pump(rt, key, uid, lambda _: has_ready(rt))
        reply(rt, update(tamper=kind == "provider_rewrite", invariant=kind == "invalid_preserved_assertion"))
    final = finish_explanation(rt, key, uid)
    assert final["status"] == "failed"
    assert final["execution"]["summary"]["accepted"] == []
    assert rt.store.info(key)["revision_id"] == before["revision_id"]
    assert query(rt, key, "quota.ceiling")["value"] == 2
    ep = rt.learning.episode(key, final["execution"]["steps"][0]["episode_id"])
    assert all(r["status"] != "accepted" for r in ep["receipts"])
    diagnostic = dumps(ep).decode()
    assert (
        "Unrequested dependent definitions must remain unchanged"
        if kind == "provider_rewrite"
        else "Assertion has a counterexample"
    ) in diagnostic


@pytest.mark.parametrize("invalid_new_metadata", [False, True])
def test_changed_parameter_reconciles_inherited_metadata_but_validates_new_proposals(
    rig, invalid_new_metadata
):
    rt, gw = rig
    inst = Instance(
        {
            "profile": "finite-v0",
            "declarations": {"sensor.reading": function({"n": integer(0, 5)}, BOOL, literal(True))},
        }
    )
    key = rt.create("Parameter revision", snapshot=pack(inst.export_snapshot()))["id"]
    original = Vocabulary(parameter_units={"sensor.reading": {"n": "units"}}).model_dump()
    rt.language.set_vocabulary(
        key,
        {
            "expected_revision": rt.store.info(key)["revision_id"],
            "expected_generation": 0,
            "vocabulary": original,
        },
    )

    def revise(p):
        p.update(kind="correction", vocabulary=original if invalid_new_metadata else {})
        p["children"][0].update(
            kind="correction",
            objective="Replace the function interface with an explicitly named count parameter",
            interfaces={
                "sensor.reading": {"kind": "function", "params": {"count": integer(0, 5)}, "returns": BOOL}
            },
        )

    before = rt.store.info(key)["revision_id"]
    key, uid = preparation(rt, gw, key, mutate=revise)
    prepared = task(rt, key, uid)
    if invalid_new_metadata:
        assert prepared["status"] == "failed"
        assert "vocabulary" in dumps(prepared).decode()
    else:
        assert prepared["status"] == "queued", prepared
        assert prepared["specification"]["plan"]["vocabulary"]["parameter_units"] == {}
    assert rt.store.info(key)["revision_id"] == before
    assert rt.language.catalog(key)["vocabulary"] == original


def test_overlapping_corrections_must_be_atomic_and_explicit_dependents_can_change():
    inst = instance()
    p = Plan.model_validate(
        {
            "kind": "correction",
            "summary": "Change",
            "children": [
                {
                    "kind": "correction",
                    "objective": "Root",
                    "input_ids": ["a"],
                    "interfaces": {
                        "quota.ceiling": {"kind": "function", "params": {}, "returns": integer(0, 5)}
                    },
                },
                {
                    "kind": "correction",
                    "objective": "Dependent",
                    "input_ids": ["a"],
                    "interfaces": {
                        "quota.permits": {"kind": "function", "params": {"n": integer(0, 5)}, "returns": BOOL}
                    },
                },
            ],
        }
    ).model_dump()
    with pytest.raises(InvalidIR, match="same atomic"):
        preserve_dependents(inst.model, deepcopy(p), Budget())
    p["children"][0]["interfaces"].update(p["children"].pop()["interfaces"])
    retained = preserve_dependents(inst.model, p, Budget())
    assert set(retained[0]) == {"quota.empty_ok"}
    assert set(p["children"][0]["interfaces"]) == dependent_closure(inst.model, {"quota.ceiling"}, Budget())


def test_post_publication_failure_is_partial_and_records_the_unfinished_stage(rig, monkeypatch):
    rt, gw = rig
    key, _ = setup(rt)
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    key, uid = preparation(rt, gw, key, mutate=correction)
    original = rt.language._compute

    def fail(*args, **kw):
        if args[3] == "language_reconcile_vocabulary":
            raise RuntimeFault("resource_exhausted", "Authored local failure")
        return original(*args, **kw)

    monkeypatch.setattr(rt.language, "_compute", fail)
    pump(rt, key, uid, lambda _: has_ready(rt))
    reply(rt, update())
    done = pump(rt, key, uid, lambda t: t["execution"].get("delivered"))
    summary = done["execution"]["summary"]
    assert summary["accepted"]
    assert summary["unresolved"] == [
        {"objective": "Complete teaching follow-up", "reason": "resource_exhausted"}
    ]
    assert done["status"] != "succeeded"
    assert not rt.interactions.get(key, uid).get("outcome_label")
    assert query(rt, key, "quota.ceiling")["value"] == 3
    assert query(rt, key, "quota.permits", n=3)["value"] is True


def test_removed_dependency_reports_saved_symbols_without_claiming_the_whole_objective(rig):
    rt, gw = rig
    key, _ = setup(rt)
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    key, uid = preparation(rt, gw, key, mutate=correction)
    t = task(rt, key, uid)
    # A historical/in-flight plan predating dependency preservation. The actual
    # ordinary admission path must report its partial outcome honestly too.
    child = t["specification"]["children"][0]
    child["preserve_declarations"] = {}
    child["interfaces"] = {"quota.ceiling": child["interfaces"]["quota.ceiling"]}
    child["acquisition_contract"]["required_symbols"] = ["quota.ceiling"]
    child["acquisition_contract"]["interfaces"] = child["interfaces"]
    with rt.store.db(key) as db:
        rt.conversations.teaching.save(db, t)
    pump(rt, key, uid, lambda _: has_ready(rt))
    reply(rt, update(retain=False))
    done = finish_explanation(rt, key, uid)
    summary = done["execution"]["summary"]
    assert done["status"] == "partially_succeeded"
    assert summary["accepted"] == ["Saved declarations: quota.ceiling"]
    assert summary["unresolved"][0]["reason"] == "dependent_capabilities_removed"
    assert set(summary["checked_changes"][0]["effects"]["removed"]) == {"quota.permits", "quota.empty_ok"}
    # Previously installed metadata is retained as history but cannot block repair.
    raw = rt.language.vocabulary(key)
    assert "quota.permits" in raw["vocabulary"]["parameter_roles"]
    assert rt.language.catalog(key)["vocabulary"]["parameter_roles"] == {}
    assert rt.language.vocabulary(key) == raw
    current = rt.store.revision(key)
    for operation in ("teaching_catalog", "language_ask_catalog"):
        result = compute(
            {
                "operation": operation,
                "snapshot": current["snapshot"],
                "context": current["context"],
                "vocabulary": raw["vocabulary"],
                "limits": {"max_work": 1000000, "max_duration_ms": 5000},
            }
        )
        assert "quota.permits" not in result["catalog"]["declarations"]
    # A fresh Teach reaches provider preparation without resetting any vocabulary.
    repair = rt.interactions.submit(key, "teach", {"text": "Restore the dependent predicate."})
    rt.conversations.teaching.tick()
    assert task(rt, key, repair["id"])["status"] == "preparing"
    assert has_ready(rt)
