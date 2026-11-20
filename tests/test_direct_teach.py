"""Ordinary Teach performs checked admission without per-task financial setup."""

from awm_adm.runtime.protocol import loads

from .interaction_support import definition, plan, reply, respond
from .test_application import app_runtime as app_runtime
from .test_direct_ask import recorded, work
from .test_learning_service import rig as rig


def preparation(
    rt,
    gateway,
    key=None,
    mutate=None,
    text="Teach doubling whole numbers 0 through 5, with outputs 0 through 10.",
    **extra,
):
    key = key or rt.create("Direct teaching")["id"]
    if not rt.learning.connection_manager.control()["connection_id"]:
        recorded(rt, gateway, {})
    item = rt.interactions.submit(key, "teach", {"text": text, **extra})
    assert rt.conversations.teaching.tick()
    value = plan([work(rt, key, item["id"])["turn_id"]])
    if mutate:
        mutate(value)
    respond(
        rt,
        {
            "status": "ready",
            "message": "The doubling scope is clear.",
            "plan_json": __import__("json").dumps(value),
        },
    )
    return key, item["id"]


def task(rt, key, uid):
    return rt.conversations.teaching.get(key, uid)


def pump(rt, key, uid, predicate, count=40):
    for _ in range(count):
        current = task(rt, key, uid)
        if predicate(current):
            return current
        rt.conversations.tick()
        rt.learning.tick()
        rt.sources.tick()
        rt.sources.feeds.tick()
    raise AssertionError(task(rt, key, uid))


def has_ready(rt):
    with rt.store.db() as db:
        return db.execute("SELECT count(*) FROM grants WHERE status='ready'").fetchone()[0] == 1


def test_clear_rule_automatically_learns_and_serves_without_requirements_or_review(rig):
    rt, gw = rig

    def punctuated(p):
        p["children"][0]["objective"] = "Double a bounded number."

    key, uid = preparation(rt, gw, mutate=punctuated)
    t = task(rt, key, uid)
    assert t["status"] == "queued", t
    assert t["execution"]["publication"] == "checked_auto"
    assert t["intent_authority"] == "local_teach_submission"
    pump(rt, key, uid, lambda _: has_ready(rt))
    reply(rt, definition())
    t = pump(rt, key, uid, lambda t: t["execution"]["phase"] == "narration")
    run = t["execution"]
    assert run["steps"][0]["status"] == "accepted", t
    reply(
        rt,
        {
            "packet_digest": run["packet_digest"],
            "accepted_ids": run["summary"]["accepted_ids"],
            "unresolved_ids": [],
            "explanation": "The doubling rule is ready.",
            "authority": "explanation_only",
        },
    )
    t = pump(rt, key, uid, lambda t: t["status"] == "succeeded")
    view = rt.interactions.get(key, uid)
    assert view["status"] == "succeeded"
    assert view["outcome_label"] == "Learned and saved · 1 objective"
    assert view["explanation"] == "The doubling rule is ready."
    assert "Double a bounded number." in view["outcome_text"]
    assert ".." not in view["outcome_text"]
    assert view["teaching"]["summary"]["accepted"] == ["Double a bounded number."]
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM allowances").fetchone()[0] == 0
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM chat_decisions").fetchone()[0] == 0
        receipts = [loads(r[0]) for r in db.execute("SELECT data FROM learning_receipts")]
    assert len(receipts) == 1
    answer = rt.query(
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
    assert answer["result"]["value"] == 6


def test_ambiguity_waits_without_expiring_and_retains_selected_inputs(rig, monkeypatch):
    rt, gw = rig
    key = rt.create("Clarification")["id"]
    recorded(rt, gw, {})
    first = rt.interactions.submit(key, "teach", {"text": "Teach doubling numbers"})
    rt.conversations.teaching.tick()
    respond(
        rt,
        {
            "status": "needs_clarification",
            "message": "What whole-number range should this cover?",
            "plan_json": None,
        },
    )
    assert rt.interactions.get(key, first["id"])["reply"] == "What whole-number range should this cover?"
    before = rt.conversations.now()
    monkeypatch.setattr(rt.conversations, "now", lambda: before + 86400000)
    second = rt.interactions.submit(
        key, "teach", {"text": "Zero through five, with outputs zero through ten.", "reply_to": first["id"]}
    )
    t = task(rt, key, second["id"])
    assert len(t["inputs"]) == 2
    assert t["question"] == "What whole-number range should this cover?"
    assert t["execution_authorized"] is False
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM episodes").fetchone()[0] == 0


def test_cancel_dispatched_learning_keeps_unknown_and_fences_publication(rig):
    from .interaction_support import command

    rt, gw = rig
    key, uid = preparation(rt, gw)
    pump(rt, key, uid, lambda _: has_ready(rt))
    job = rt.learning.claim()
    rt.learning.authorize(job["grant_id"], job["lease"])
    command(rt, key, uid, "cancel")
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {
            "status": "succeeded",
            "text": __import__("json").dumps(definition()),
            "usage": {"input_tokens": 10, "output_tokens": 20},
        },
    )
    pump(rt, key, uid, lambda t: t["execution"].get("delivered"))
    assert task(rt, key, uid)["status"] == "cancelled"
    assert "math.double" not in rt.query(key, {"op": "capabilities"})["result"]["value"]["declarations"]


def test_supplied_markdown_is_extracted_and_admitted_with_automatic_provenance(rig, monkeypatch):
    import base64
    import json

    from .interaction_support import TEXT, uploaded
    from .test_sources import fact, lookup, profile

    rt, gw = rig
    monkeypatch.setenv("TZ", "America/New_York")
    key = rt.create("Historical material")["id"]
    recorded(rt, gw, {})
    meta = uploaded(rt, key)
    item = rt.interactions.submit(
        key,
        "teach",
        {
            "text": "Learn the attached site's dated capacities, in whole places from zero to twenty, for 2020–2024 and 2024–2026.",
            "attachments": [meta["id"]],
        },
    )
    rt.conversations.teaching.tick()
    value = {
        "kind": "facts",
        "summary": "Historical site capacity",
        "children": [
            {
                "kind": "facts",
                "objective": "Retain historical capacity",
                "input_ids": [work(rt, key, item["id"])["turn_id"]],
                "material": {
                    "projection": profile(),
                    "sources": [
                        {
                            "source_id": "records",
                            "attribution": "Supplied history",
                            "evidence_group": "owner",
                            "allow_external": False,
                        }
                    ],
                },
            }
        ],
    }
    respond(rt, {"status": "ready", "message": "Learn these dated facts.", "plan_json": json.dumps(value)})
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    pump(rt, key, item["id"], lambda _: has_ready(rt))
    with rt.store.db() as db:
        grant = loads(
            db.execute(
                "SELECT body FROM grants WHERE json_extract(body,'$.purpose')='extraction'"
            ).fetchone()[0]
        )
    wire = json.loads(base64.b64decode(grant["wire"]))
    assert "America/New_York" in json.dumps(wire["input"])
    assert "Asia/Tokyo" not in json.dumps(wire["input"])
    reply(rt, {"claims": [{**fact(), "start_byte": 0, "end_byte": len(TEXT.encode())}]})
    current = pump(rt, key, item["id"], lambda t: t["execution"]["phase"] == "narration")
    assert current["execution"]["steps"][0]["status"] == "accepted", current
    with rt.store.db(key) as db:
        episodes = [loads(r[0]) for r in db.execute("SELECT data FROM source_episodes")]
        assert db.execute("SELECT count(*) FROM chat_decisions").fetchone()[0] == 0
    assert episodes[0]["review_authority"] == "automatic_teach"
    assert rt.sources.versions(key)[0]["content"] == TEXT
    assert lookup(rt, key, 2021)["result"]["value"]["value"] == 10


def test_installed_independent_requirements_still_reject_a_wrong_complete_candidate(rig):
    from awm_adm.engine import Instance
    from awm_adm.runtime.protocol import pack

    from .ported.provider_fixtures import wire_expression
    from .test_instance import capacity_policy

    rt, gw = rig
    policy = capacity_policy(10)
    contract = policy["contracts"][0]
    contract["required_symbols"] = ["math.double"]
    contract["checks"][0]["expression"] = {
        "op": "call",
        "function": "math.double",
        "args": {"n": {"op": "literal", "value": 5}},
    }
    key = rt.create("Independent requirements", snapshot=pack(Instance(policy=policy).export_snapshot()))[
        "id"
    ]
    key, uid = preparation(rt, gw, key)
    pump(rt, key, uid, lambda _: has_ready(rt))
    wrong = definition()
    wrong["result"]["definitions"]["math.double"]["body"] = wire_expression({"op": "literal", "value": 0})
    reply(rt, wrong)
    # Local rejection can request one bounded diagnostic revision; it never publishes the bad draft.
    pump(rt, key, uid, lambda _: has_ready(rt))
    assert not rt.query(key, {"op": "capabilities"})["result"]["value"]["declarations"]
    reply(rt, wrong)
    current = pump(
        rt, key, uid, lambda t: t["execution"]["phase"] in {"narration", "deliver"} or t["status"] == "failed"
    )
    assert current["execution"]["steps"][0]["status"] == "unresolved"
    assert not rt.query(key, {"op": "capabilities"})["result"]["value"]["declarations"]


def finish_explanation(rt, key, uid):
    current = pump(rt, key, uid, lambda t: t["execution"]["phase"] == "narration")
    run = current["execution"]
    reply(
        rt,
        {
            "packet_digest": run["packet_digest"],
            "accepted_ids": run["summary"]["accepted_ids"],
            "unresolved_ids": run["summary"]["unresolved_ids"],
            "explanation": "The checked teaching outcome is recorded.",
            "authority": "explanation_only",
        },
    )
    return pump(rt, key, uid, lambda t: t["execution"].get("delivered"))


def test_backward_rejects_replacement_then_forward_accepts_fresh_request(rig):
    from .ported.provider_fixtures import wire_expression

    rt, gw = rig
    key, first = preparation(rt, gw)
    pump(rt, key, first, lambda _: has_ready(rt))
    reply(rt, definition())
    finish_explanation(rt, key, first)

    def correction(p):
        p["kind"] = "correction"
        p["children"][0]["kind"] = "correction"
        p["children"][0]["objective"] = (
            "Replace the doubling rule with a constant zero for the same finite inputs"
        )

    changed = definition()
    changed["result"]["definitions"]["math.double"]["body"] = wire_expression({"op": "literal", "value": 0})
    original = rt.store.info(key)["revision_id"]
    key, second = preparation(
        rt,
        gw,
        key,
        mutate=correction,
        text="Change the previous rule to return zero for every allowed input.",
    )
    pump(rt, key, second, lambda _: has_ready(rt))
    reply(rt, changed)
    rejected = finish_explanation(rt, key, second)
    assert rejected["execution"]["steps"][0]["status"] == "unresolved"
    assert rt.interactions.get(key, second)["outcome_label"] is None
    assert rt.store.info(key)["revision_id"] == original
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    assert rt.conversations.teaching.get(key, second)["status"] == "failed"
    key, third = preparation(
        rt,
        gw,
        key,
        mutate=correction,
        text="Replace the previous doubling rule with zero for every allowed input.",
    )
    pump(rt, key, third, lambda _: has_ready(rt))
    reply(rt, changed)
    accepted = finish_explanation(rt, key, third)
    assert accepted["status"] == "succeeded"
    assert (
        rt.query(
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
        )["result"]["value"]
        == 0
    )
    assert task(rt, key, second)["execution"]["steps"][0]["status"] == "unresolved"


def test_restart_never_repeats_an_uncertain_acquisition(rig):
    from awm_adm.runtime.service import Runtime

    rt, gw = rig
    key, uid = preparation(rt, gw)
    pump(rt, key, uid, lambda _: has_ready(rt))
    job = rt.learning.claim()
    rt.learning.authorize(job["grant_id"], job["lease"])
    with rt.store.db() as db:
        count = db.execute("SELECT count(*) FROM grants").fetchone()[0]
    rt.close()
    restored = Runtime(rt.config, start_scheduler=False)
    try:
        for _ in range(12):
            restored.conversations.tick()
            restored.learning.tick()
        with restored.store.db() as db:
            assert db.execute("SELECT count(*) FROM grants").fetchone()[0] == count
            row = db.execute(
                "SELECT unresolved,outcome FROM grants WHERE id=?", (job["grant_id"],)
            ).fetchone()
            assert row["unresolved"] == 1
        assert not restored.query(key, {"op": "capabilities"})["result"]["value"]["declarations"]
    finally:
        restored.close()


def test_source_subset_keeps_the_immutable_carrier_and_different_scope_is_reported():
    import copy

    import pytest

    from awm_adm.intake.coverage import extend
    from awm_adm.runtime.protocol import RuntimeFault

    from .test_sources import profile

    original = profile()
    subset = copy.deepcopy(original)
    subset["cells"] = [original["cells"][0]]
    assert extend(original, subset) == original
    changed = copy.deepcopy(subset)
    changed["predicates"][0]["unit"] = "dollars"
    with pytest.raises(RuntimeFault, match="unit or value range"):
        extend(original, changed)
    added = copy.deepcopy(subset)
    added["entities"] = ["new-site"]
    assert extend(original, added)["entities"] == ["site", "new-site"]


def test_later_teaching_extends_dates_through_checked_coverage_preserving_history(rig):
    import json

    from .interaction_support import uploaded
    from .test_sources import fact, lookup, profile

    rt, gw = rig
    key = rt.create("Growing history")["id"]
    recorded(rt, gw, {})
    for year, end, value in [(2020, 2024, 10), (2026, 2028, 12)]:
        text = f"The site has capacity {value} places from {year} until {end}."
        meta = uploaded(rt, key, name=f"history-{year}.md", content=text)
        item = rt.interactions.submit(
            key,
            "teach",
            {
                "text": f"Learn this site's capacity for {year}–{end}, in whole places zero through twenty.",
                "attachments": [meta["id"]],
            },
        )
        rt.conversations.teaching.tick()
        projection = profile()
        projection["cells"] = [
            {
                **projection["cells"][0],
                "effective_from": f"{year}-01-01T00:00:00Z",
                "effective_to": f"{end}-01-01T00:00:00Z",
            }
        ]
        p = {
            "kind": "facts",
            "summary": "Site capacity history",
            "children": [
                {
                    "kind": "facts",
                    "objective": f"Learn the {year} capacity",
                    "input_ids": [work(rt, key, item["id"])["turn_id"]],
                    "material": {
                        "projection": projection,
                        "sources": [
                            {
                                "source_id": "records",
                                "attribution": "Supplied history",
                                "evidence_group": "owner",
                                "allow_external": False,
                            }
                        ],
                    },
                }
            ],
        }
        respond(rt, {"status": "ready", "message": "Dated fact", "plan_json": json.dumps(p)})
        pump(rt, key, item["id"], lambda _: has_ready(rt))
        claim = fact()
        claim["value"]["value"] = value
        claim["temporal_scope"].update(
            effective_from=f"{year}-01-01T00:00:00Z", effective_to=f"{end}-01-01T00:00:00Z"
        )
        reply(rt, {"claims": [{**claim, "start_byte": 0, "end_byte": len(text.encode())}]})
        assert finish_explanation(rt, key, item["id"])["status"] == "succeeded"
    assert lookup(rt, key, 2021)["result"]["value"]["value"] == 10
    assert lookup(rt, key, 2027)["result"]["value"]["value"] == 12
    assert lookup(rt, key, 2025)["status"] == "needs_input"
