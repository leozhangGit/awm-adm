"""Native provider format, strict local checks and durable diagnostic regressions."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from awm_adm.engine import Budget, Instance
from awm_adm.runtime.protocol import dumps, pack
from awm_adm.runtime.supervisor import Supervisor
from awm_adm.teaching.compute import compute
from awm_adm.teaching.prompt import specification
from awm_adm.teaching.provider_format import PROFILE, response_schema

from .teaching_wire import native_reply
from .test_application import app_runtime as app_runtime
from .test_conversations import message
from .test_learning_service import rig as rig
from .test_teaching import funded, material, plan, respond

ROOT = Path(__file__).parents[1]


def proposed():
    return native_reply(
        {"status": "ready", "message": "Ready for review.", "plan_json": dumps(plan(["turn-one"])).decode()}
    )


def task(reply, *, legacy=False, input_ids=None):
    instance = Instance()
    return {
        "operation": "teaching_check",
        "snapshot": pack(instance.export_snapshot()),
        "context": instance.info(),
        "vocabulary": {},
        "input_ids": input_ids or ["turn-one"],
        "provider_text": reply if isinstance(reply, str) else dumps(reply).decode(),
        "reply_format": None if legacy else PROFILE,
        "limits": {"max_work": 1000000, "max_duration_ms": 5000},
    }


def check(reply, **kwargs):
    return compute(task(reply, **kwargs), Budget(1000000, 5))


def test_native_reply_is_shallow_closed_and_matches_published_contract():
    schema = response_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(proposed())
    assert schema == json.loads((ROOT / "contracts/teaching-reply.schema.json").read_text())
    assert len(dumps(schema)) < 10000

    def walk(value):
        if isinstance(value, dict):
            assert "$ref" not in value and "$defs" not in value
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert value["required"] == list(value["properties"])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(schema)
    result = check(proposed())
    assert result["plan"]["children"][0]["interfaces"] == plan(["turn-one"])["children"][0]["interfaces"]
    assert result["contracts"][0]["allowed_helpers"] == []
    assert result["reply"]["status"] == "ready"


def test_saved_live_malformed_json_is_rejected_with_position_across_process():
    raw = (ROOT / "tests/fixtures/teaching/malformed-legacy-reply.json").read_text()
    local_task = task(raw, legacy=True, input_ids=["f827c407-d919-46f7-aa45-18ac7b906394"])
    supervisor = Supervisor()
    try:
        result = supervisor.run(local_task)
    finally:
        supervisor.close()
    assert result["failure"]["stage"] == "plan_json"
    assert result["failure"]["position"] == {"line": 1, "column": 4871, "offset": 4870}
    assert "plan" not in result and "reply" not in result
    assert "camera-kit" not in dumps(result["failure"]).decode()
    # A new native contract must not silently fall back to the old envelope.
    assert check(raw)["failure"]["stage"] == "envelope"


def test_valid_legacy_contract_still_uses_the_same_local_checker():
    reply = {"status": "ready", "message": "Review.", "plan_json": dumps(plan(["turn-one"])).decode()}
    assert check(reply, legacy=True)["plan"] == check(proposed())["plan"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r["plan"]["types"].append(copy.deepcopy(r["plan"]["types"][0])),
        lambda r: r["plan"]["types"][0].update(kind="ref", symbol="missing.Type", minimum=None, maximum=None),
        lambda r: r["plan"]["types"][0].update(
            kind="vector", element_id="t0", length=1, minimum=None, maximum=None
        ),
        lambda r: r["plan"]["types"][0].update(maximum=1000000),
        lambda r: r["plan"]["types"][0].update(symbol="unused.Hidden"),
        lambda r: r["plan"]["children"][0]["interfaces"][0].update(body={"op": "literal", "value": True}),
        lambda r: r["plan"]["children"][0]["interfaces"].append(
            copy.deepcopy(r["plan"]["children"][0]["interfaces"][0])
        ),
        lambda r: r["plan"]["children"][0].update(input_ids=["foreign-turn"]),
        lambda r: r["plan"]["aliases"][0].update(targets=["math.double.n"]),
        lambda r: r["plan"]["aliases"].append(copy.deepcopy(r["plan"]["aliases"][0])),
        lambda r: r["plan"].update(requirements_json="{"),
        lambda r: r.update(status="needs_clarification"),
        lambda r: r["plan"].update(owner_authorized=True),
    ],
)
def test_invalid_native_proposals_do_not_reach_local_plan(mutation):
    value = proposed()
    mutation(value)
    result = check(value)
    assert "failure" in result and "plan" not in result
    assert len(dumps(result["failure"])) < 4096


def test_all_type_and_header_forms_preserve_local_meaning():
    values = {
        "sample.Choice": {"kind": "type", "type": {"kind": "enum", "values": ["a", "b"]}},
        "sample.Record": {
            "kind": "type",
            "type": {
                "kind": "record",
                "fields": {
                    "flag": {"kind": "bool"},
                    "items": {"kind": "vector", "element": {"ref": "sample.Choice"}, "length": 2},
                },
            },
        },
        "sample.Sum": {
            "kind": "type",
            "type": {
                "kind": "sum",
                "variants": {"yes": {"kind": "bool"}, "no": {"kind": "record", "fields": {}}},
            },
        },
        "sample.step": {
            "kind": "transition",
            "state": {"ref": "sample.Record"},
            "parameters": {"kind": "record", "fields": {}},
        },
        "sample.goal": {"kind": "goal", "state": {"ref": "sample.Record"}},
        "sample.property": {"kind": "assertion", "params": {"x": {"ref": "sample.Sum"}}},
    }
    p = plan(["turn-one"])
    p["children"][0]["interfaces"].update(values)
    result = check(native_reply({"status": "ready", "message": "Review.", "plan_json": dumps(p).decode()}))
    assert result["plan"]["children"][0]["interfaces"] == p["children"][0]["interfaces"]


def test_source_permissions_unknown_cells_and_existing_rules_are_not_authority():
    p = plan(["turn-one"])
    p["kind"] = "mixed"
    p["children"].append(
        {
            "kind": "facts",
            "objective": "Bounded supplied history",
            "input_ids": ["turn-one"],
            "material": material(),
        }
    )
    good = native_reply({"status": "ready", "message": "Review.", "plan_json": dumps(p).decode()})
    assert "plan" in check(good)
    permission = copy.deepcopy(good)
    permission["plan"]["children"][1]["material"]["sources"][0]["allow_external"] = True
    assert "failure" in check(permission)
    unknown = copy.deepcopy(good)
    unknown["plan"]["children"][1]["material"]["projection"]["cells"].append(
        {"kind": "unknown", "granularity": "year", "effective_from": None, "effective_to": None}
    )
    assert "failure" in check(unknown)
    assert not list(Draft202012Validator(response_schema()).iter_errors(good))
    assert list(Draft202012Validator(response_schema()).iter_errors(unknown))


def test_error_diagnostics_do_not_echo_untrusted_values_or_map_keys():
    value = proposed()
    value["plan"]["SECRET-DO-NOT-ECHO"] = "password-like content"
    value["plan"]["children"][0]["interfaces"][0]["kind"] = "malicious <script>"
    diagnostic = check(value)["failure"]
    encoded = dumps(diagnostic).decode()
    assert all(text not in encoded for text in ("SECRET", "password-like", "<script>"))
    assert diagnostic["issues"]


def test_preparation_guidance_is_model_and_domain_neutral():
    spec = specification({"objective": "owner request", "inputs": []}, {}, {}, {})
    assert spec["prompt_version"] == "adm-teaching-preparation/4"
    assert "local_plan_schema" not in spec["context"]
    assert "plan_json" not in dumps(spec["schema"]).decode()
    assert all(
        s not in spec["instructions"].lower() for s in ("equipment", "camera-kit", "luna", "gpt-", "claude")
    )


def test_failure_reason_is_durable_and_preserves_paid_usage_without_retry(rig):
    rt, gw = rig
    key, cid = funded(rt, gw)
    before = rt.store.info(key)
    rt.conversations.message(key, cid, message(rt, key, cid, "Teach a bounded numeric capability."))
    rt.conversations.tick()
    value = proposed()
    value["plan"]["types"][0]["element_id"] = "malicious-unused-reference"
    respond(rt, value)
    details = rt.conversations.details(key, cid)
    failed = details["tasks"][0]
    assert failed["status"] == "failed" and failed["failure_diagnostics"]["stage"] == "types"
    assert details["work"][0]["failure_diagnostics"] == failed["failure_diagnostics"]
    assert "finite types" in details["turns"][-1]["text"]
    assert (
        rt.conversations.teaching.listing(key)["items"][0]["failure_diagnostics"]
        == failed["failure_diagnostics"]
    )
    assert rt.learning.usage()["calls"] == 1
    assert rt.store.info(key) == before
    assert not [p for p in details["proposals"] if p["kind"] == "task"]
    assert not rt.conversations.tick()
    assert rt.learning.claim() is None
