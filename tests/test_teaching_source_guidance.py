"""Saved source failure and authored controls. No provider calls or candidate admission."""

import copy
import hashlib
import json

import pytest
from jsonschema import Draft202012Validator

from awm_adm.providers.wire import make_wire
from awm_adm.runtime.protocol import dumps
from awm_adm.runtime.supervisor import Supervisor
from awm_adm.teaching import service
from awm_adm.teaching.prompt import specification
from awm_adm.teaching.provider_format import response_schema
from awm_adm.teaching.source_guidance import BOUNDS, KIND, NAMESPACE, SYMBOL, VALUES

from .teaching_wire import native_reply
from .test_application import app_runtime as app_runtime
from .test_conversations import message
from .test_learning_service import rig as rig
from .test_teaching import funded, plan
from .test_teaching_format import ROOT, check, task

SAVED_REPLY = ROOT / "tests/fixtures/teaching/invalid-native-source-reply.json"
INPUT_ID = "80f49b80-6817-4c15-a813-32e162310227"
PREDICATE_PATH = ["plan", "children", 1, "material", "projection", "predicates", 0]


def saved():
    return json.loads(SAVED_REPLY.read_text())


def predicate(reply):
    return reply["plan"]["children"][1]["material"]["projection"]["predicates"][0]


def authored_control():
    # An authored diagnostic control, not a provider repair or learned candidate.
    reply = saved()
    predicate(reply).update(symbol="equipment.capacity", values=[])
    return reply


def test_exact_saved_source_failure_is_still_rejected_across_process():
    raw = SAVED_REPLY.read_bytes()
    assert (
        hashlib.sha256(raw).hexdigest() == "22266fe23b03626bbbfa2bcaa5663f7e670669a6ccddc373888bdcc795d7a43f"
    )
    # The deliberately shallow provider grammar permits this; local refinements reject it.
    Draft202012Validator(response_schema()).validate(json.loads(raw))
    supervisor = Supervisor()
    try:
        result = supervisor.run(task(raw.decode(), input_ids=[INPUT_ID]))
    finally:
        supervisor.close()
    assert "plan" not in result and "reply" not in result
    failure = result["failure"]
    assert failure["stage"] == "sources"
    assert failure["issues"] == [{"code": "string_pattern_mismatch", "path": [*PREDICATE_PATH, "symbol"]}]
    assert "capacity" not in dumps(failure).decode()


@pytest.mark.parametrize("fix_symbol,fix_values", [(True, False), (False, True), (True, True)])
def test_source_controls_require_both_independent_fields(fix_symbol, fix_values):
    reply = saved()
    if fix_symbol:
        predicate(reply)["symbol"] = "equipment.capacity"
    if fix_values:
        predicate(reply)["values"] = []
    before = copy.deepcopy(reply)
    result = check(reply, input_ids=[INPUT_ID])
    assert reply == before  # No silent prefixing, coercion or carrier cleanup.
    if fix_symbol and fix_values:
        material = result["plan"]["children"][1]["material"]
        assert material == before["plan"]["children"][1]["material"]
        assert material["projection"]["cells"][-1]["effective_to"] == "2027-01-01T00:00:00Z"
        assert len(material["projection"]["cells"]) == 2
        assert result["plan"]["requirements"] is None
    else:
        assert "plan" not in result
        assert result["failure"]["stage"] == "sources"
        assert result["failure"]["issues"] == [
            {"code": "value_error", "path": PREDICATE_PATH}
            if fix_symbol
            else {"code": "string_pattern_mismatch", "path": [*PREDICATE_PATH, "symbol"]}
        ]


@pytest.mark.parametrize(
    "fields,valid",
    [
        ({"kind": "boolean", "values": []}, True),
        ({"kind": "boolean", "values": ["false", "true"]}, False),
        ({"kind": "integer", "values": []}, True),
        ({"kind": "integer", "values": ["0", "1", "2"]}, False),
        ({"kind": "enum", "values": ["low", "high"]}, True),
        ({"kind": "enum", "values": []}, False),
        ({"kind": "enum", "values": ["low", "low"]}, False),
        ({"kind": "enum", "values": [""]}, False),
        ({"kind": "int"}, False),
        ({"kind": "bool"}, False),
        ({"minimum": 3, "maximum": 2}, False),
        ({"minimum": 0, "maximum": 1000001}, False),
        ({"symbol": "other.measure"}, True),
        ({"symbol": "domain._measure2"}, True),
        ({"symbol": "measure"}, False),
        ({"symbol": "domain.2measure"}, False),
        ({"symbol": "domain.measure-name"}, False),
    ],
)
def test_source_guidance_agrees_with_unchanged_local_carrier_checks(fields, valid):
    reply = authored_control()
    predicate(reply).update(fields)
    result = check(reply, input_ids=[INPUT_ID])
    assert ("plan" in result) is valid
    if not valid:
        assert result["failure"]["stage"] == "sources"


def test_source_descriptions_reach_ordered_wire_without_model_specific_guidance():
    spec = specification({"objective": "owner request", "inputs": []}, {}, {}, {})
    projection = spec["schema"]["properties"]["plan"]["anyOf"][0]["properties"]["children"]["items"][
        "properties"
    ]["material"]["anyOf"][0]["properties"]["projection"]["properties"]
    fields = projection["predicates"]["items"]["properties"]
    for node, description in (
        (projection["namespace"], NAMESPACE),
        (fields["symbol"], SYMBOL),
        (fields["kind"], KIND),
        (fields["values"], VALUES),
        (fields["minimum"], BOUNDS),
        (fields["maximum"], BOUNDS),
    ):
        assert node["description"] == description
        assert description in spec["instructions"]
    wires = []
    for model in ("configured-model-a", "configured-model-b"):
        raw, _ = make_wire(
            {"provider": "openai", "model": model, "capabilities": ["json_schema"]}, spec, 8192
        )
        wire = json.loads(raw)
        assert wire.pop("model") == model
        assert wire["instructions"] == spec["instructions"]
        assert json.dumps(wire["text"]["format"]["schema"]) == json.dumps(spec["schema"])
        wires.append(wire)
    assert wires[0] == wires[1]
    assert all(s not in dumps(spec).decode().lower() for s in ("equipment", "camera-kit", "gpt-", "claude"))


def settle(rt, reply):
    job = rt.learning.claim()
    assert job is not None
    rt.learning.authorize(job["grant_id"], job["lease"])
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {
            "status": "succeeded",
            "text": dumps(reply).decode(),
            "usage": {"input_tokens": 3195, "output_tokens": 956},
        },
    )
    assert rt.conversations.tick()


def test_source_failure_is_durable_settles_known_usage_and_never_retries(rig):
    rt, gw = rig
    key, cid = funded(rt, gw)
    before = rt.conversations.context(key)
    rt.conversations.message(key, cid, message(rt, key, cid, "Prepare a capability and supplied history."))
    assert rt.conversations.tick()
    settle(rt, saved())
    details = rt.conversations.details(key, cid)
    failed = details["tasks"][0]
    assert failed["status"] == "failed" and failed["failure_diagnostics"]["stage"] == "sources"
    assert details["work"][0]["failure_diagnostics"] == failed["failure_diagnostics"]
    assert "source coverage" in details["turns"][-1]["text"]
    assert "capacity" not in details["turns"][-1]["text"]
    usage = rt.learning.usage()
    assert usage["calls"] == 1
    assert usage["input_tokens"] == 3195 and usage["output_tokens"] == 956
    assert rt.conversations.context(key) == before
    assert not [p for p in details["proposals"] if p["kind"] == "task"]
    assert not rt.conversations.tick() and rt.learning.claim() is None
    assert rt.learning.usage() == usage


@pytest.mark.parametrize(
    "version,legacy,valid",
    [
        ("1", True, True),
        ("2", True, True),
        ("3", False, True),
        ("4", False, True),
        ("3", True, False),
        ("4", True, False),
        ("unknown", False, False),
    ],
)
def test_retained_prompt_provenance_selects_decoder_without_content_fallback(
    rig, monkeypatch, version, legacy, valid
):
    # Exercise dispatch provenance and decoder routing, not a recreation of historical prompts.
    def dispatched_spec(*args):
        spec = specification(*args)
        spec["prompt_version"] = f"adm-teaching-preparation/{version}"
        return spec

    monkeypatch.setattr(service, "specification", dispatched_spec)
    rt, gw = rig
    key, cid = funded(rt, gw)
    before = rt.store.info(key)
    turn = rt.conversations.message(key, cid, message(rt, key, cid, "Teach a bounded doubling capability."))
    assert rt.conversations.tick()
    reply = {"status": "ready", "message": "Review.", "plan_json": dumps(plan([turn["id"]])).decode()}
    settle(rt, reply if legacy else native_reply(reply))
    details = rt.conversations.details(key, cid)
    assert details["work"][0]["provenance"]["prompt_version"] == f"adm-teaching-preparation/{version}"
    assert details["tasks"][0]["status"] == ("awaiting_review" if valid else "failed")
    assert rt.store.info(key) == before
    assert not rt.conversations.tick() and rt.learning.claim() is None
