"""Provider-visible bounds and safe length diagnostics; no live provider calls."""

import base64
import copy
import hashlib
import json

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from awm_adm.providers.wire import make_wire
from awm_adm.runtime.protocol import dumps, loads
from awm_adm.runtime.service import Runtime
from awm_adm.teaching.field_guidance import INSTRUCTIONS, OBJECTIVE
from awm_adm.teaching.models import Child
from awm_adm.teaching.prompt import ASSESSED_PROMPT_FORMATS, specification
from awm_adm.teaching.provider_format import response_schema

from .interaction_support import plan, respond
from .test_application import app_runtime as app_runtime
from .test_direct_ask import recorded
from .test_direct_teach import has_ready, preparation, pump, task
from .test_learning_service import rig as rig
from .test_plugin_workflow import connector
from .test_teaching_format import check, proposed


def grammar(value):
    if isinstance(value, dict):
        return {k: grammar(v) for k, v in value.items() if k != "description"}
    if isinstance(value, list):
        return [grammar(v) for v in value]
    return value


@pytest.mark.parametrize(
    "options,digest",
    [
        ({}, "69a70af7b89149ba2844df37e6c59cb91bf1ee96f0c43e732ca53a78040dcc8a"),
        ({"assessed": True}, "fc4852cec3d0c192e63d711bf567d58af19970f79c927ea128ec639d1f27b2f7"),
        (
            {"assessed": True, "temporal_evidence": True},
            "90e2460d1db896085c02ad34b7bec281abb49f756892086a0299e4c78ac8eb13",
        ),
    ],
)
def test_bound_annotations_preserve_the_existing_shallow_wire_grammar(options, digest):
    schema = response_schema(**options)
    # These hashes identify the grammar before field guidance, excluding annotations.
    assert hashlib.sha256(dumps(grammar(schema))).hexdigest() == digest
    Draft202012Validator.check_schema(schema)
    fields = schema["properties"]["plan"]["anyOf"][0]["properties"]
    child = fields["children"]["items"]["properties"]
    assert fields["summary"]["description"] == "Local limits: 1 to 2000 characters."
    assert fields["children"]["description"] == "Local limits: 1 to 4 items."
    assert fields["types"]["description"] == "Local limits: at most 128 items."
    assert OBJECTIVE in child["objective"]["description"]
    assert "1 to 2000 characters" in child["objective"]["description"]
    assert child["input_ids"]["description"] == "Local limits: 1 to 4 items."
    assert child["interfaces"]["description"] == "Local limits: at most 32 items."
    node = fields["types"]["items"]["properties"]
    assert node["values"]["description"] == "Local limits: at most 64 items."
    assert "value >= 0; value <= 32" in node["length"]["anyOf"][0]["description"]
    assert "32768 characters" in fields["requirements_json"]["anyOf"][0]["description"]
    if options.get("assessed"):
        gaps = schema["properties"]["missing_information"]
        assert "at most 8 items" in gaps["description"]
        assert "1 to 200 characters" in gaps["items"]["properties"]["subject"]["description"]
        assert "1 to 1000 characters" in gaps["items"]["properties"]["detail"]["description"]


@pytest.mark.parametrize("selected", [False, True])
def test_same_guidance_and_authored_property_order_reach_both_provider_wires(selected):
    data = {"objective": "The adopted rule", "inputs": [], "temporal_context": {"basis": "fixture"}}
    if selected:
        data["material_manifest"] = {"entries": []}
    spec = specification(data, {}, {}, None)
    assert INSTRUCTIONS in spec["instructions"]
    assert all(s not in spec["instructions"].lower() for s in ("a-team", "nvidia", "gpt-", "claude"))
    assert spec["prompt_version"] == f"adm-teaching-preparation/{22 if selected else 23}"
    for provider in ("openai", "anthropic"):
        bodies = []
        for model in ("configured-a", "configured-b"):
            raw, _ = make_wire(
                {"provider": provider, "model": model, "capabilities": ["json_schema"]}, spec, 8192
            )
            body = json.loads(raw)
            field = body["text"]["format"] if provider == "openai" else body["output_config"]["format"]
            assert json.dumps(field["schema"]) == json.dumps(spec["schema"])
            assert body["instructions" if provider == "openai" else "system"] == spec["instructions"]
            body.pop("model")
            bodies.append(body)
        assert bodies[0] == bodies[1]
    for version in (14, 16, 18, 20):
        assert ASSESSED_PROMPT_FORMATS[f"adm-teaching-preparation/{version}"] == "awm-adm-teaching-reply/6"
    for version in (15, 17, 19, 21):
        assert ASSESSED_PROMPT_FORMATS[f"adm-teaching-preparation/{version}"] == "awm-adm-teaching-reply/7"


@pytest.mark.parametrize("length", [0, 1999, 2000, 2001, 2403])
def test_objective_boundary_counts_characters_and_never_truncates(length):
    value = proposed()
    value["plan"]["children"][0]["objective"] = "é" * length
    before = copy.deepcopy(value)
    result = check(value)
    assert value == before
    if 1 <= length <= 2000:
        assert result["plan"]["children"][0]["objective"] == value["plan"]["children"][0]["objective"]
    else:
        failure = result["failure"]
        assert "plan" not in result and "reply" not in result
        assert failure["issues"] == [
            {
                "path": ["plan", "children", 0, "objective"],
                "code": "string_too_long" if length > 2000 else "string_too_short",
                "actual_length": length,
                "max_length" if length > 2000 else "min_length": 2000 if length else 1,
                "unit": "characters",
            }
        ]
        assert f"{length} characters" in failure["message"]
        assert "é" not in dumps(failure).decode()
    # The local Plan model retains exactly the same boundary as provider decoding.
    local = {**plan(["turn-one"])["children"][0], "objective": "é" * length}
    if 1 <= length <= 2000:
        assert Child.model_validate(local).objective == local["objective"]
    else:
        with pytest.raises(ValidationError):
            Child.model_validate(local)


@pytest.mark.parametrize(
    "field,value,actual,bound,unit",
    [
        ("input_ids", ["PRIVATE-REFERENCE"] * 5, 5, 4, "items"),
        ("interfaces", [], 0, None, None),
        ("summary", "PRIVATE-TEXT" * 201, 2412, 2000, "characters"),
    ],
)
def test_other_fields_use_general_diagnostics_without_exposing_content(field, value, actual, bound, unit):
    proposal = proposed()
    target = proposal["plan"] if field == "summary" else proposal["plan"]["children"][0]
    target[field] = value
    failure = check(proposal)["failure"]
    encoded = dumps(failure).decode()
    assert "PRIVATE" not in encoded
    assert len(encoded) < 4096
    if bound is not None:
        assert failure["issues"][0]["actual_length"] == actual
        assert failure["issues"][0]["max_length"] == bound
        assert failure["issues"][0]["unit"] == unit
    else:
        assert all("actual_length" not in i for i in failure["issues"])


def test_concise_objective_keeps_full_original_requirements_in_acquisition(rig):
    rt, gw = rig
    text = "Adopt the bounded doubling rule. " + "Retain this explicit requirement and its exception. " * 100
    key, uid = preparation(rt, gw, text=text)
    pump(rt, key, uid, lambda _: has_ready(rt))
    step = task(rt, key, uid)["execution"]["steps"][0]
    episode = rt.learning.episode(key, step["episode_id"])
    assert episode["body"]["task"]["description"] == "Double a bounded number"
    original = episode["body"]["task"]["owner_inputs"]
    assert len(original) == 1 and original[0]["text"] == text
    with rt.store.db() as db:
        grant = loads(db.execute("SELECT body FROM grants WHERE id=?", (episode["grant_id"],)).fetchone()[0])
    wire = loads(base64.b64decode(grant["wire"]))
    context = loads(wire["input"][0]["content"].encode())
    assert context["task"]["owner_inputs"] == original


def test_length_failure_reaches_api_and_plugin_and_survives_restart_without_retry(rig, tmp_path):
    rt, gw = rig
    key = rt.create("Bounded preparation")["id"]
    recorded(rt, gw, {})
    before = rt.store.info(key)
    c, root = connector(rt, tmp_path / "project", tmp_path / "private")
    c.project(root, model_id=key)
    item = c.teach(root, text="Save the adopted bounded rule.", operation="length")
    uid = item["interaction_id"]
    assert rt.conversations.teaching.tick()
    value = proposed()
    value["plan"]["children"][0]["objective"] = "PRIVATE-GENERATED-TEXT" * 120
    respond(rt, value)
    final = c.work(root, work_id="length")
    assert final["state"] == "failed" and final["failure_code"] == "invalid_preparation"
    failure = final["failure_diagnostics"]
    assert failure["issues"][0]["actual_length"] == 2640
    assert failure["issues"][0]["max_length"] == 2000
    view = rt.interactions.get(key, uid)
    assert view["failure_diagnostics"] == failure
    assert "2640 characters" in view["reply"] and "2000" in view["reply"]
    assert "PRIVATE" not in dumps(failure).decode()
    assert rt.store.info(key) == before
    assert rt.learning.usage()["calls"] == 1
    for _ in range(2):
        assert c.work(root, work_id="length")["failure_diagnostics"] == failure
        assert not rt.conversations.tick()
        assert rt.learning.claim() is None
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM episodes").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM chat_questions").fetchone()[0] == 0
    config = rt.config
    rt.close()
    restored = Runtime(config, start_scheduler=False)
    try:
        assert restored.interactions.get(key, uid)["failure_diagnostics"] == failure
        assert restored.learning.claim() is None
        assert restored.learning.usage()["calls"] == 1
        assert restored.store.info(key) == before
    finally:
        restored.close()
