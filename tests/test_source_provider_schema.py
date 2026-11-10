"""Provider grammar is broader than admission; automatic checks use no live provider."""

# ruff: noqa: F811

import base64
import copy
import hashlib
import json
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from awm_adm.engine.artifacts import digest
from awm_adm.engine.budget import Budget
from awm_adm.engine.provider_wire import encode_wire
from awm_adm.sources.compute import extract
from awm_adm.sources.models import ExtractionOutput, Projection
from awm_adm.sources.service import claims_output_schema, output_schema

from .test_application import app_runtime, configuration  # noqa: F401
from .test_learning_service import dispatch, rig  # noqa: F401
from .test_sources import fact, ingest, install, job, profile, scope


def task_and_reply():
    text = "From 2020 until 2024, site capacity was 10 places."
    task = {
        "purpose": "claims",
        "job_id": "authored-control",
        "max_claims": 100,
        "projection": profile(),
        "source": {
            "content": text,
            "record": {
                "source_id": "records",
                "item_id": "report",
                "version_id": "v1",
                "content_digest": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
            },
        },
    }
    return task, {"claims": [{**fact(), "start_byte": 0, "end_byte": len(text.encode())}]}


def test_structure_keeps_closed_fields_and_order_without_changing_local_contracts():
    local_before = ExtractionOutput.model_json_schema()
    schema = claims_output_schema()
    Draft202012Validator.check_schema(schema)
    assert list(schema["$defs"]["SpannedFact"]["properties"]) == [
        "entity_id",
        "predicate",
        "value",
        "unit",
        "temporal_scope",
        "assertion_kind",
        "start_byte",
        "end_byte",
    ]
    for node in [schema, *schema["$defs"].values()]:
        assert node["additionalProperties"] is False
        assert node["required"] == list(node["properties"])
    _, answer = task_and_reply()
    checker = Draft202012Validator(schema, format_checker=FormatChecker())
    checker.validate(answer)
    extra = copy.deepcopy(answer)
    extra["claims"][0]["approve"] = True
    assert not checker.is_valid(extra)
    missing = copy.deepcopy(answer)
    del missing["claims"][0]["temporal_scope"]["effective_to"]
    assert not checker.is_valid(missing)
    assert ExtractionOutput.model_json_schema() == local_before
    assert digest(encode_wire(local_before)) == (
        "sha256:9de6833c52a377bd25728c7806d913b9e09a9c09a11de85e3c13b3d8614979e3"
    )
    assert digest(encode_wire(output_schema(Projection))) == (
        "sha256:a22d66d70a7aba462f9ff94b4acc53343f13a0c2f5d4c04f2e39ea79c6d0eca5"
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"start_byte": -1},
        {"end_byte": 999},
        {"end_byte": 0},
        {"unit": ""},
        {"unit": "x" * 101},
        {"entity_id": "x" * 129},
        {"entity_id": "bad name"},
        {"predicate": "not a symbol"},
        {"temporal_scope": {**scope(), "effective_from": "2020-02-30T00:00:00Z"}},
        {"temporal_scope": scope(2024, 2020)},
        {"value": {"kind": "integer", "value": True}},
        {"value": {"kind": "integer", "value": 2**53}},
    ],
)
def test_remote_shape_cannot_bypass_full_local_fact_validation(patch):
    task, answer = task_and_reply()
    answer["claims"][0].update(patch)
    Draft202012Validator(claims_output_schema()).validate(answer)
    with pytest.raises(ValueError):
        extract({**task, "provider_text": json.dumps(answer)}, Budget())


def test_claim_count_and_utf8_span_checks_remain_local():
    task, answer = task_and_reply()
    answer["claims"] *= 101
    Draft202012Validator(claims_output_schema()).validate(answer)
    with pytest.raises(ValueError):
        extract({**task, "provider_text": json.dumps(answer)}, Budget())
    task, answer = task_and_reply()
    task["source"]["content"] = "é " + task["source"]["content"]
    answer["claims"][0]["start_byte"] = 1
    Draft202012Validator(claims_output_schema()).validate(answer)
    with pytest.raises(UnicodeDecodeError):
        extract({**task, "provider_text": json.dumps(answer)}, Budget())


@pytest.mark.parametrize(
    "patch,reason",
    [
        ({"entity_id": "elsewhere"}, "unknown_entity_or_predicate"),
        ({"value": {"kind": "integer", "value": 21}}, "value_outside_carrier"),
        ({"temporal_scope": scope(2021, 2024)}, "partial_time_cell"),
    ],
)
def test_owner_projection_keeps_unresolved_claims_held(patch, reason):
    task, answer = task_and_reply()
    answer["claims"][0].update(patch)
    Draft202012Validator(claims_output_schema()).validate(answer)
    result = extract({**task, "provider_text": json.dumps(answer)}, Budget())
    assert result["claims"][0]["claim"]["status"] == "needs_evidence"
    assert result["claims"][0]["reason"] == reason


@pytest.mark.parametrize("variant", ["valid", "empty_unit", "too_many"])
def test_dispatched_structural_schema_still_uses_local_validation_and_review(rig, variant):
    rt, gateway = rig
    key = rt.create("Provider schema control")["id"]
    install(rt, key)
    before = rt.store.info(key)
    task, answer = task_and_reply()
    if variant == "empty_unit":
        answer["claims"][0]["unit"] = ""
    elif variant == "too_many":
        answer["claims"] *= 101
    source = ingest(rt, key, media_type="text/plain", content=task["source"]["content"])
    c = rt.learning.save_connection(
        {
            "idempotency_key": str(uuid4()),
            "name": "Offline extraction control",
            "provider": "recorded",
            "model": "model-neutral-fixture",
            "enabled": True,
            "purposes": ["extraction"],
            "recorded_responses": [answer],
        }
    )
    gateway.synchronize()
    gateway.synchronize()
    c = rt.learning.connection(c["id"])
    item = job(rt, key, source, extractor="external", connection_id=c["id"], connection_version=c["version"])
    rt.sources.tick()
    item = rt.sources.get(key, "source_jobs", item["id"])
    with rt.store.db() as db:
        grant = json.loads(
            db.execute("SELECT body FROM grants WHERE id=?", (item["grant_id"],)).fetchone()[0]
        )
    wire = base64.b64decode(grant["wire"])
    schema = json.loads(wire)["text"]["format"]["schema"]
    assert schema == claims_output_schema()
    Draft202012Validator(schema).validate(answer)
    assert grant["provenance"]["request_hash"] == digest(wire)
    assert grant["provenance"]["schema_wire_hash"] == digest(encode_wire(schema))
    dispatch(rt, gateway)
    rt.sources.tick()
    result = rt.sources.get(key, "source_jobs", item["id"])
    assert result["status"] == ("extracted" if variant == "valid" else "failed"), result
    history = rt.sources.overview(key)
    if variant == "valid":
        assert result["result"]["claims"][0]["claim"]["status"] == "candidate"
    else:
        assert not history["claims"]
    assert not history["episodes"]
    assert rt.store.info(key)["revision_id"] == before["revision_id"]
    assert rt.learning.usage()["calls"] == 1
