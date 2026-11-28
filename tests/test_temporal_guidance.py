"""Provider-neutral temporal hints, safe diagnostics and unchanged rejection boundaries."""

import copy
import json

import pytest
from jsonschema import Draft202012Validator

from awm_adm.providers.wire import make_wire
from awm_adm.runtime.protocol import dumps
from awm_adm.runtime.supervisor import Supervisor
from awm_adm.sources.service import claims_output_schema
from awm_adm.teaching.prompt import specification
from awm_adm.teaching.provider_format import TEMPORAL_PROFILE, response_schema
from awm_adm.teaching.source_guidance import BOUNDS, NAMESPACE, SYMBOL, UNIT, VALUES
from awm_adm.temporal_evidence.guidance import ASK, EXACT_TIME, EXTRACTION, INSTRUCTIONS
from awm_adm.temporal_evidence.models import Catalog

from .interaction_support import respond
from .temporal_support import catalog
from .test_application import app_runtime as app_runtime
from .test_direct_ask import recorded, work
from .test_learning_service import rig as rig
from .test_teaching_format import task


def proposed(inputs=None, material="original"):
    return {
        "profile": TEMPORAL_PROFILE,
        "status": "ready",
        "message": "Proposed observations",
        "plan": {
            "kind": "facts",
            "summary": "Independent measurements",
            "types": [],
            "aliases": [],
            "parameters": [],
            "value_aliases": [],
            "requirements_json": None,
            "evidence_scope": catalog(),
            "children": [
                {
                    "kind": "facts",
                    "objective": "Learn supplied observations",
                    "input_ids": inputs or ["turn-one"],
                    "interfaces": [],
                    "material": {"material_ids": [material]},
                }
            ],
        },
    }


def invalid(value, case):
    scope = value["plan"]["evidence_scope"]
    if case in ("symbol", "both"):
        scope["predicates"][0]["symbol"] = "unqualified"
    if case in ("precision", "both"):
        scope["cells"][0]["precision"] = "hour"
    if case == "timezone":
        scope["cells"][0]["timezone_basis"] = "PRIVATE_UNTRUSTED_ZONE"
    if case == "window":
        scope["cells"][0]["kind"] = "occurrence"


@pytest.mark.parametrize("case", ["symbol", "precision", "both", "timezone", "window"])
def test_malformed_temporal_proposals_still_fail_across_process_without_coercion(case):
    value = proposed()
    invalid(value, case)
    original = copy.deepcopy(value)
    # Shallow provider grammar is intentionally not local semantic validation.
    Draft202012Validator(response_schema(temporal_evidence=True)).validate(value)
    request = {**task(value), "reply_format": TEMPORAL_PROFILE}
    supervisor = Supervisor()
    try:
        checked = supervisor.run(request)
    finally:
        supervisor.close()
    assert value == original
    assert "plan" not in checked and "reply" not in checked
    failure = checked["failure"]
    assert failure["stage"] == "sources"
    assert "temporal evidence catalog" in failure["message"]
    assert "No knowledge was accepted" in failure["message"]
    assert all(i["path"][:2] == ["plan", "evidence_scope"] for i in failure["issues"])
    assert all(
        i["rule"] in {"qualified_predicate_symbol", "temporal_scope_contract"} for i in failure["issues"]
    )
    assert "unqualified" not in dumps(failure).decode()
    assert "PRIVATE_UNTRUSTED_ZONE" not in dumps(failure).decode()


def test_scope_descriptions_distinguish_exact_coordinates_and_uncertainty_on_wire():
    schema = response_schema(temporal_evidence=True, assessed=True, reaffirmation=True)
    fields = schema["properties"]["plan"]["anyOf"][0]["properties"]["evidence_scope"]["anyOf"][0][
        "properties"
    ]
    predicate = fields["predicates"]["items"]["properties"]
    assert fields["namespace"]["description"].startswith(NAMESPACE)
    for name, hint in (
        ("symbol", SYMBOL),
        ("unit", UNIT),
        ("values", VALUES),
        ("minimum", BOUNDS),
        ("maximum", BOUNDS),
    ):
        assert predicate[name]["description"].startswith(hint)
    assert EXACT_TIME in fields["cells"]["items"]["properties"]["precision"]["description"]
    for instructions in (INSTRUCTIONS, EXTRACTION, ASK):
        assert EXACT_TIME in instructions
    extraction = claims_output_schema(temporal=True)
    for name in ("Scope", "Anchor"):
        assert EXACT_TIME in extraction["$defs"][name]["properties"]["precision"]["description"]
    spec = specification(
        {"objective": "Read supplied observations", "inputs": [], "material_manifest": {"entries": []}},
        {},
        {},
        {},
    )
    assert spec["prompt_version"] == "adm-teaching-preparation/22"
    wires = []
    for model in ("configured-a", "configured-b"):
        raw, _ = make_wire(
            {"provider": "openai", "model": model, "capabilities": ["json_schema"]}, spec, 8192
        )
        wire = json.loads(raw)
        assert wire.pop("model") == model
        assert json.dumps(wire["text"]["format"]["schema"]) == json.dumps(schema)
        wires.append(wire)
    assert wires[0] == wires[1]


def test_uncertain_window_retains_precision_and_exact_instant_requires_second():
    value = catalog()
    value["cells"][0].update(kind="occurrence", precision="hour", effective_to="2026-03-01T13:00:00Z")
    assert Catalog.model_validate(value).model_dump() == value
    value["cells"][0].update(kind="instant", effective_to=None)
    with pytest.raises(ValueError):
        Catalog.model_validate(value)
    value["cells"][0]["precision"] = "second"
    assert Catalog.model_validate(value).model_dump() == value


def test_temporal_failure_is_durable_does_not_accept_or_retry_and_hides_untrusted_keys(rig):
    rt, gw = rig
    key = rt.create("Temporal diagnostics")["id"]
    recorded(rt, gw, {})
    before = rt.conversations.context(key)
    item = rt.interactions.submit(key, "teach", {"text": "Learn the supplied measurements."})
    current = rt.conversations.teaching.get(key, item["id"])
    value = proposed([i["id"] for i in current["inputs"]], current["material_manifest"]["entries"][0]["id"])
    invalid(value, "both")
    value["plan"]["evidence_scope"]["PRIVATE_UNTRUSTED_KEY"] = "PRIVATE_UNTRUSTED_VALUE"
    assert rt.conversations.teaching.tick()
    respond(rt, value)
    cid = work(rt, key, item["id"])["conversation_id"]
    details = rt.conversations.details(key, cid)
    failed = details["tasks"][0]
    assert failed["status"] == "failed"
    diag = failed["failure_diagnostics"]
    assert diag == details["work"][0]["failure_diagnostics"]
    assert "temporal evidence catalog" in details["turns"][-1]["text"]
    assert "PRIVATE_UNTRUSTED" not in dumps(diag).decode()
    assert diag["issues"][-1]["path"][-1] == "<field>"
    assert rt.conversations.context(key) == before
    assert not rt.sources.versions(key)
    assert not [p for p in details["proposals"] if p["kind"] == "task"]
    usage = rt.learning.usage()
    assert usage["calls"] == 1
    assert not rt.conversations.tick()
    assert rt.learning.claim() is None
    assert rt.learning.usage() == usage
