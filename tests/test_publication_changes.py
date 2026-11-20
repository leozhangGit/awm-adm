"""Checked before/after reporting independently of provider narrative."""

from copy import deepcopy

import pytest

from awm_adm.engine import Budget, Instance, build_candidate, validate_snapshot
from awm_adm.learning.changes import BYTE_LIMIT, description, publication_effects, summarize
from awm_adm.runtime.protocol import dumps
from awm_adm.sources.compute import evidence

from .interaction_support import TEXT, reply
from .ported.helpers import function, integer, literal
from .test_application import app_runtime as app_runtime
from .test_direct_teach import finish_explanation, has_ready, pump
from .test_intake import material_task
from .test_learning_service import rig as rig
from .test_sources import fact, ingest, install, project


def publish(old, new, retractions=()):
    inst = Instance({"profile": "finite-v0", "declarations": old}, mode="forward")
    before = validate_snapshot(inst.export_snapshot())
    candidate = build_candidate(
        inst.model,
        new,
        candidate_id="change",
        retractions=list(retractions),
        evidence=[evidence({"fixture": "publication comparison"})],
    )
    inst.receive(candidate, review_required=False)
    assert inst.decide_next()["status"] == "accepted"
    return publication_effects(before, inst, Budget())


def test_added_removed_and_changed_signature_are_distinct():
    small = function({}, integer(0, 5), literal(2))
    wide = function({}, integer(0, 10), literal(2))
    effects = publish(
        {"limits.old": small, "limits.value": small},
        {"limits.new": small, "limits.value": wide},
        ["limits.old"],
    )
    rows = {v["symbol"]: v for v in effects["change_report"]["entries"]}
    assert rows["limits.old"]["kind"] == "removed"
    assert rows["limits.old"]["after"] is None
    assert rows["limits.new"]["kind"] == "added"
    assert rows["limits.new"]["before"] is None
    assert rows["limits.value"]["kind"] == "definition_changed"
    assert rows["limits.value"]["before"]["text"] != rows["limits.value"]["after"]["text"]


def test_bounded_and_legacy_reports_never_claim_complete_changes():
    old = {f"many.v{i}": function({}, integer(0, 5), literal(1)) for i in range(40)}
    new = {k: function({}, integer(0, 5), literal(2)) for k in old}
    effects = publish(old, new)
    report = effects["change_report"]
    assert report["total"] == 40 and not report["complete"]
    assert len(dumps(report["entries"])) < BYTE_LIMIT + 64
    receipts = [
        {"receipt_id": "one", "accepted_revision": "revision", "status": "accepted", "effects": effects}
    ]
    summary = summarize(receipts)
    assert not summary["complete"]
    assert "incomplete" in summary["text"]
    assert all(e["revision_id"] == "revision" for e in summary["entries"])
    legacy = summarize([{"status": "accepted", "receipt_id": "old", "effects": None}])
    assert legacy["entries"] == [] and not legacy["complete"]
    rejected = summarize([{"status": "rejected", "effects": effects}])
    assert rejected["entries"] == [] and rejected["text"] == ""


def test_unsupported_expression_is_explicitly_abbreviated():
    body = function(
        {}, integer(0, 5), {"op": "if", "condition": literal(True), "then": literal(1), "else": literal(2)}
    )
    assert description(body)["abbreviated"]
    assert description(body)["definition"] == body
    assert description(body)["definition_complete"]
    large = function({}, {"kind": "enum", "values": ["v" + str(i) for i in range(400)]}, literal("v0"))
    assert description(large)["definition"] is None
    assert not description(large)["definition_complete"]
    assert description(large)["abbreviated"]


@pytest.mark.parametrize("new_value, expected", [(10, "evidence_changed"), (12, "definition_changed")])
def test_source_changes_bind_values_intervals_and_support(app_runtime, new_value, expected):
    rt = app_runtime
    key = rt.create("Evidence changes", mode="forward")["id"]
    install(rt, key)
    first = project(rt, key, ingest(rt, key, [fact(10)]))
    second = project(rt, key, ingest(rt, key, [fact(new_value)]))
    assert first["status"] == second["status"] == "accepted"
    report = second["effects"]["change_report"]
    assert report["complete"] and len(report["entries"]) == 1
    entry = report["entries"][0]
    assert entry["kind"] == expected
    assert entry["before_fact"]["value"]["value"] == 10
    assert entry["after_fact"]["value"]["value"] == new_value
    assert entry["before_fact"]["cell"] == entry["after_fact"]["cell"]
    assert entry["before_fact"]["source"] != entry["after_fact"]["source"]
    assert second["decision_revision"] == first["accepted_revision"]
    assert second["accepted_revision"] == rt.store.info(key)["revision_id"]
    with rt.store.db(key) as db:
        from awm_adm.runtime.protocol import loads

        saved = loads(
            db.execute("SELECT data FROM learning_receipts WHERE id=?", (second["id"],)).fetchone()[0]
        )
    assert saved["effects"] == second["effects"]
    assert saved["accepted_revision"] == second["accepted_revision"]


def test_source_teaching_exposes_publications_and_checked_summary(rig):
    rt, gw = rig
    key, _, uid, _ = material_task(rt, gw)
    pump(rt, key, uid, lambda _: has_ready(rt))
    reply(rt, {"claims": [{**fact(), "start_byte": 0, "end_byte": len(TEXT.encode())}]})
    final = finish_explanation(rt, key, uid)
    assert final["status"] == "succeeded"
    view = rt.interactions.get(key, uid)
    admissions = view["teaching"]["admissions"]
    assert len(admissions) == 1 and admissions[0]["classification"] == "accepted"
    changes = view["teaching"]["summary"]["changes"]
    assert changes["complete"] and len(changes["entries"]) == 1
    assert changes["entries"][0]["after_fact"]["value"]["value"] == 10
    saved = deepcopy(changes)
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    assert rt.interactions.get(key, uid)["teaching"]["summary"]["changes"] == saved


def test_source_admission_reports_all_checked_work(app_runtime, monkeypatch):
    from awm_adm.sources.compute import compute

    rt = app_runtime
    key = rt.create("Work accounting")["id"]
    install(rt, key)
    original = rt.learning.supervisor.run
    observed = []

    def checked(task, **kwargs):
        if task["operation"] != "source_admit":
            return original(task, **kwargs)
        budget = Budget(task["limits"]["max_work"], task["limits"]["max_duration_ms"] / 1000)
        result = compute(task, budget)
        observed.append((result["work"], budget.used))
        return result

    monkeypatch.setattr(rt.learning.supervisor, "run", checked)
    result = project(rt, key, ingest(rt, key))
    assert result["status"] == "accepted"
    assert result["effects"]["change_report"]["complete"]
    assert len(observed) == 1
    reported, consumed = observed[0]
    assert reported == consumed and consumed > 0
