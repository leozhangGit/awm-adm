"""Caller intent survives checked publication without becoming external truth."""

from copy import deepcopy

import pytest

from awm_adm.engine.artifacts import digest
from awm_adm.engine.data import encode
from awm_adm.interaction.knowledge import search
from awm_adm.interaction.models import DirectMessage, DirectTeach
from awm_adm.teaching.intent import PROFILE, attach, capture

from .interaction_support import definition, reply
from .test_application import app_runtime as app_runtime
from .test_direct_teach import has_ready, preparation, pump
from .test_learning_service import rig as rig


def request():
    return {
        "id": "task",
        "conversation_id": "conversation",
        "created_at_ms": 1,
        "intent_authority": "local_teach_submission",
        "inputs": [
            {
                "id": "first",
                "text": "Adopt the bounded doubling rule.",
                "knowledge_intent": {"role": "adopted_rule", "basis": "Agreed design premise"},
            },
            {"id": "second", "text": "The range is zero through five."},
        ],
    }


def test_portable_record_separates_caller_intent_from_prepared_meaning():
    owner = request()
    child = {"objective": "Bounded function", "kind": "capability", "input_ids": ["first", "second"]}
    record = capture(owner, child)
    owner["inputs"][0]["text"] = "Changed later"
    assert record["inputs"][0]["text"] == "Adopt the bounded doubling rule."
    assert record["human_review"] == "not_established"
    declarations = {"a.new": {"kind": "function"}, "a.retained": {"kind": "function"}}
    provider = {"artifact_kind": "evidence", "content": "provider generated"}
    sources, support = attach(record, declarations, {"a.retained"}, [provider], None)
    assert len(sources) == 2
    assert len(support["a.retained"]) == 1
    content = sources[-1]["content"]
    assert content["definition_digest"] == digest(encode(declarations["a.new"]))
    assert content["input_digest"] == digest(encode(record["inputs"]))
    assert content["interpretation_assurance"] == "not_certified"
    assert len(support["a.new"]) == 2
    assert attach(None, declarations, {}, [provider], None) == ([provider], None)


def test_classification_is_optional_caller_metadata_not_an_ask_or_provider_permission():
    base = {"text": "Adopt the rule"}
    assert DirectTeach.model_validate(base).knowledge_intent is None
    value = {**base, "knowledge_intent": {"role": "adopted_rule", "basis": "Plan agreed by caller"}}
    assert DirectTeach.model_validate(value).knowledge_intent.role == "adopted_rule"
    with pytest.raises(ValueError):
        DirectMessage.model_validate(value)
    with pytest.raises(ValueError):
        DirectTeach.model_validate({**value, "knowledge_intent": {"role": "human_verified", "basis": "x"}})


@pytest.mark.parametrize("explicit", [False, True])
def test_checked_rule_retains_intent_and_provider_origin_across_snapshot(rig, explicit):
    rt, gw = rig
    extra = (
        {"knowledge_intent": {"role": "adopted_rule", "basis": "Caller adopted this finite rule"}}
        if explicit
        else {}
    )
    key, uid = preparation(rt, gw, **extra)
    pump(rt, key, uid, lambda _: has_ready(rt))
    reply(rt, definition())
    pump(rt, key, uid, lambda t: t["execution"]["steps"][0]["status"] == "accepted")
    rows = search(rt, key, kind="declaration")["items"]
    row = next(r for r in rows if r["name"] == "math.double")
    intents = [e["teaching_intent"] for e in row["evidence"] if "teaching_intent" in e]
    assert len(intents) == 1
    intent = intents[0]
    assert intent["profile"] == PROFILE and intent["task_id"] == uid
    assert intent["definition_digest"] == digest(encode(row["definition"]))
    assert intent["inputs"][0]["text"].startswith("Teach doubling")
    assert ("knowledge_intent" in intent["inputs"][0]) == explicit
    assert any(
        e["source"] == "awm-adm:acquisition" and e["kind"] == "provider_statement" for e in row["evidence"]
    )
    snapshot = rt.store.snapshot(key)
    copy = rt.create("Independent intent copy", snapshot=deepcopy(snapshot))["id"]
    copied = next(r for r in search(rt, copy, kind="declaration")["items"] if r["name"] == "math.double")
    assert copied["evidence"] == row["evidence"]
    assert copied["definition"] == row["definition"]
    with rt.store.db(copy) as db:
        assert db.execute("SELECT count(*) FROM teaching_tasks").fetchone()[0] == 0


def test_forward_keeps_prior_intent_for_preserved_dependents(rig):
    from awm_adm.engine import Instance, build_candidate
    from awm_adm.runtime.protocol import pack

    from .test_direct_teach import finish_explanation
    from .test_teaching_revision import correction, instance, update

    rt, gw = rig
    base = Instance()
    declarations = instance().model.document()["declarations"]
    record = capture(
        request(), {"objective": "Original policy", "kind": "capability", "input_ids": ["first"]}
    )
    evidence, support = attach(record, declarations, set(), [], None)
    package = build_candidate(
        base.model,
        declarations,
        candidate_id="original-adoption",
        evidence=evidence,
        evidence_by_symbol=support,
    )
    base.receive(package, review_required=False)
    assert base.decide_next()["status"] == "accepted"
    key = rt.create("Preserved provenance", snapshot=pack(base.export_snapshot()))["id"]
    before = {r["name"]: r for r in search(rt, key, kind="declaration")["items"]}
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    key, uid = preparation(rt, gw, key, mutate=correction)
    pump(rt, key, uid, lambda _: has_ready(rt))
    reply(rt, update())
    assert finish_explanation(rt, key, uid)["status"] == "succeeded"
    after = {r["name"]: r for r in search(rt, key, kind="declaration")["items"]}
    for symbol in ("quota.permits", "quota.empty_ok"):
        previous = [e for e in before[symbol]["evidence"] if "teaching_intent" in e]
        current = [e for e in after[symbol]["evidence"] if "teaching_intent" in e]
        assert current == previous
        assert current[0]["teaching_intent"]["task_id"] == "task"
    current = [e for e in after["quota.ceiling"]["evidence"] if "teaching_intent" in e]
    assert len(current) == 1 and current[0]["teaching_intent"]["task_id"] == uid
