"""Recorded replies exercise context/validation; they do not measure live LLM accuracy."""

import base64
import json

import pytest

from awm_adm.conversations.presentation import outcome_label, packet, readable
from awm_adm.engine import Instance
from awm_adm.language.prompt import specification
from awm_adm.providers.wire import make_wire
from awm_adm.runtime.protocol import pack

from .interaction_support import narration, proposal, reply
from .ported.helpers import BOOL, function, integer, literal, operator, variable
from .test_application import app_runtime as app_runtime
from .test_application import execute
from .test_direct_ask import recorded, work
from .test_learning_service import rig as rig


def cupboard(rt):
    model = Instance(
        {
            "profile": "finite-v0",
            "declarations": {
                "kits.allowed": function(
                    {"available": integer(0, 2), "borrowed": integer(0, 2)},
                    BOOL,
                    operator(
                        "and",
                        operator("ge", variable("available"), literal(1)),
                        operator("lt", variable("borrowed"), literal(2)),
                    ),
                )
            },
        }
    )
    return rt.create("Cupboard", snapshot=pack(model.export_snapshot()))["id"]


def start(rt, key, text, **kw):
    item = rt.interactions.submit(key, "ask", {"text": text, **kw})
    assert rt.conversations.ask.tick()
    w = work(rt, key, item["id"])
    with rt.store.db() as db:
        grant = json.loads(db.execute("SELECT body FROM grants WHERE id=?", (w["grant_id"],)).fetchone()[0])
    wire = json.loads(base64.b64decode(grant["wire"]))
    return item, wire


def finish(rt, key, item, available, borrowed):
    reply(
        rt,
        proposal("is kits.allowed with " + json.dumps({"available": available, "borrowed": borrowed}) + "?"),
    )
    assert rt.conversations.ask.tick()
    result = execute(rt, key)
    assert rt.conversations.ask.tick()
    narration(rt, work(rt, key, item["id"]), explanation="The model checked the supplied counts.")
    return result, rt.interactions.get(key, item["id"])


def test_grounded_followups_retain_and_override_scenario_inputs_and_keep_exact_results(rig):
    rt, gw = rig
    key = cupboard(rt)
    recorded(rt, gw, {})
    before = rt.store.info(key)
    first, _ = start(rt, key, "I have one kit on loan and one is available. Can I borrow another?")
    _, answer = finish(rt, key, first, 1, 1)
    assert answer["outcome"]["values"]["value"] is True
    second, wire = start(rt, key, "What if I already have two?", reply_to=first["id"])
    payload = json.dumps(wire["input"])
    assert first["text"] in payload
    assert "not an" in wire["instructions"] and "unsupported assumption" in wire["instructions"]
    result, answer = finish(rt, key, second, 1, 2)
    assert result["result"]["value"]["value"] is False
    assert answer["outcome_label"] == "Model answer: No"
    assert answer["outcome"]["binding"] == result["result"]["binding"]
    assert work(rt, key, second["id"])["packet"]["user_question"] == second["text"]
    assert work(rt, key, second["id"])["packet"]["selected_user_turns"][0]["text"] == first["text"]
    third, _ = start(
        rt, key, "Now suppose none are available and I have none on loan.", reply_to=second["id"]
    )
    result, _ = finish(rt, key, third, 0, 0)
    assert result["result"]["value"]["value"] is False
    assert rt.store.info(key) == before
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM requests").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM episodes").fetchone()[0] == 0


@pytest.mark.parametrize(
    "text,response",
    [
        (
            "What if I already have two?",
            proposal(status="needs_clarification", clarification="Two kits on loan, or two available?"),
        ),
        (
            "For the other kit?",
            proposal(status="needs_clarification", clarification="Which kit do you mean?"),
        ),
        (
            "Use the current inventory",
            proposal(
                'is kits.allowed with {"available":1,"borrowed":2}?', assumptions=["One kit is available now"]
            ),
        ),
        ("I have three on loan", proposal('is kits.allowed with {"available":1,"borrowed":3}?')),
    ],
)
def test_missing_ambiguous_unobserved_and_out_of_range_inputs_do_not_execute(rig, text, response):
    rt, gw = rig
    key = cupboard(rt)
    recorded(rt, gw, {})
    item, _ = start(rt, key, text)
    assert work(rt, key, item["id"])["selected_context"] == []
    reply(rt, response)
    rt.conversations.ask.tick()
    result = rt.interactions.get(key, item["id"])
    assert result["status"] == "needs_input"
    assert result["request_id"] is None
    assert "?" in result["reply"] or response["command"]  # parser can diagnose an invalid range
    assert not rt.store.page(key, "requests")["items"]


def test_provider_uncertainty_is_not_discarded_even_when_context_exists(rig):
    rt, gw = rig
    key = cupboard(rt)
    recorded(rt, gw, {})
    first, _ = start(rt, key, "One kit is available and I have one on loan.")
    finish(rt, key, first, 1, 1)
    second, _ = start(rt, key, "What if I already have two?", reply_to=first["id"])
    reply(
        rt,
        proposal(
            'is kits.allowed with {"available":1,"borrowed":2}?', assumptions=["The reference is ambiguous"]
        ),
    )
    rt.conversations.ask.tick()
    assert rt.interactions.get(key, second["id"])["status"] == "needs_input"
    assert len(rt.store.page(key, "requests")["items"]) == 1


def test_automatic_prompt_is_model_neutral_and_does_not_change_manual_preview_authority():
    spec = specification("What about that?", {}, [{"id": "turn", "text": "user input"}], [], automatic=True)
    wires = [
        json.loads(
            make_wire({"provider": "openai", "model": m, "capabilities": ["json_schema"]}, spec, 4096)[0]
        )
        for m in ("configured-one", "configured-two")
    ]
    for wire in wires:
        wire.pop("model")
    assert wires[0] == wires[1]
    assert list(spec["schema"]["properties"]) == ["status", "command", "assumptions", "clarification"]
    manual = specification("What about that?", {}, [], [])
    assert "Only an explicitly confirmed preview runs locally" in manual["instructions"]
    assert "latest explicit value" in spec["instructions"]
    assert "unrelated subject" in spec["instructions"]


@pytest.mark.parametrize("value,label", [(True, "Yes"), (False, "No"), (0, "0"), (2, "2"), ("open", "open")])
def test_short_note_keeps_authoritative_value_visible(value, label):
    body = {"status": "succeeded", "values": {"value": value, "verdict": "established"}, "claims": ["value"]}
    assert outcome_label(body) == "Model answer: " + label
    assert "Verdict" not in readable(body)


def test_short_note_never_hides_uncertainty_planning_or_historical_scope():
    body = {"status": "succeeded", "values": {"value": True}, "claims": ["value"]}
    for status in ("needs_input", "inconclusive", "failed"):
        assert outcome_label({**body, "status": status}) is None
    assert outcome_label({**body, "claims": ["value", "no_plan_within_bound"]}) is None
    assert (
        outcome_label({**body, "query": {"op": "lookup_fact"}}) == "Model answer: Yes · Historical evidence"
    )


def test_oversized_narration_context_falls_back_without_losing_the_result():
    request = {"request_id": "r", "status": "needs_input", "query": {}, "pinned_context": {}, "result": None}
    value, body = packet({}, request, question="x" * 33000)
    assert value is None and body["status"] == "needs_input"
