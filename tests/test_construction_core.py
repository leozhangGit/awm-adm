import copy
import json
from pathlib import Path

import pytest

from awm_adm.engine import Budget, Instance, Model, build_candidate
from awm_adm.engine.acquisition import AcquisitionError, check_proposal, validate_contract
from awm_adm.engine.artifacts import digest
from awm_adm.engine.construction import DraftIncomplete, complete, merge, seed, view
from awm_adm.engine.construction_format import FORMAT, decode_update, response_schema
from awm_adm.engine.data import encode
from awm_adm.engine.errors import InvalidIR, ResourceLimit
from awm_adm.engine.provider_format import _decode
from awm_adm.engine.provider_format import response_schema as complete_schema
from awm_adm.engine.provider_prompt import CONSTRUCTION_INSTRUCTIONS, INSTRUCTIONS, LEARNING_ROLE
from awm_adm.engine.provider_wire import encode_wire as ordered_encode

from .ported.helpers import call, function, integer, literal
from .ported.provider_fixtures import wire_expression
from .test_instance import capacity_policy, evidence, value_query


def contract():
    return validate_contract(
        {
            **validate_contract(),
            "required_symbols": ["site.capacity"],
            "allowed_helpers": ["site.base"],
            "allowed_retractions": [],
            "interfaces": {"site.capacity": {"kind": "function", "params": {}, "returns": integer(0, 100)}},
        }
    )


def update(expression):
    return {
        "draft": {
            "definitions": {"site.capacity": {"body": expression}},
            "declarations": {},
            "discard": [],
            "retractions": [],
        },
        "evidence": [evidence()],
    }


def wire(expression):
    return {
        "format": FORMAT,
        "result": {
            "status": "draft",
            "definitions": {"site.capacity": {"body": wire_expression(expression)}},
            "declarations": [],
            "discard": [],
            "retractions": [],
            "summary": "Authored test",
        },
    }


def test_private_draft_never_serves_and_complete_candidate_still_checks_owner_policy():
    instance = Instance(policy=capacity_policy())
    c = contract()
    draft = seed(c)
    with pytest.raises(DraftIncomplete):
        complete(draft, c, instance.model, Budget())
    assert view(draft, c)["trust"] == "unaccepted_private_draft"
    assert instance.query(value_query())["status"] == "needs_input"
    bad = merge(draft, update(literal(12)), c, Budget())
    complete(bad, c, instance.model, Budget())
    package = build_candidate(
        instance.model,
        bad["declarations"],
        candidate_id="bad",
        evidence=list(bad["evidence"].values()),
        evidence_by_symbol=bad["support"],
    )
    instance.receive(package, review_required=False)
    assert instance.decide_next()["status"] == "rejected"
    good = merge(bad, update(literal(10)), c, Budget())
    complete(good, c, instance.model, Budget())
    instance.receive(
        build_candidate(
            instance.model,
            good["declarations"],
            candidate_id="good",
            evidence=list(good["evidence"].values()),
            evidence_by_symbol=good["support"],
        ),
        review_required=False,
    )
    assert instance.decide_next()["status"] == "accepted"
    assert instance.query(value_query())["value"] == 10
    assert bad["declarations"]["site.capacity"]["body"]["value"] == 12


def test_missing_helper_and_receiver_interface_cannot_be_filled_or_replaced_silently():
    c = contract()
    draft = merge(seed(c), update(call("site.base")), c, Budget())
    with pytest.raises(DraftIncomplete):
        complete(draft, c, Model.empty(), Budget())
    bad = update(literal(10))
    bad["draft"]["declarations"]["site.capacity"] = function({}, integer(0, 100), literal(10))
    with pytest.raises(AcquisitionError):
        merge(draft, bad, c, Budget())
    helper = {
        "draft": {
            "definitions": {},
            "declarations": {"site.base": function({}, integer(0, 100), literal(10))},
            "discard": [],
            "retractions": [],
        },
        "evidence": [evidence("helper")],
    }
    finished = merge(draft, helper, c, Budget())
    complete(finished, c, Model.empty(), Budget())
    assert "site.base" not in draft["declarations"]
    with pytest.raises(ResourceLimit):
        merge(draft, helper, c, Budget(max_work=1))


def test_scope_unused_helpers_retractions_and_bad_update_are_rejected_atomically():
    c = contract()
    draft = seed(c)
    saved = copy.deepcopy(draft)
    bad = update(literal(10))
    bad["draft"]["retractions"] = ["site.capacity"]
    with pytest.raises(AcquisitionError):
        merge(draft, bad, c, Budget())
    assert draft == saved
    extra = {
        "site.capacity": function({}, integer(0, 100), literal(10)),
        "site.base": function({}, integer(0, 100), literal(4)),
    }
    with pytest.raises(AcquisitionError):
        check_proposal(extra, [], c, Budget())


def test_schema_local_references_and_needs_evidence_branch_are_closed():
    c = contract()
    schema = response_schema(c)
    proposal = wire(literal(10))
    assert decode_update(proposal, Budget(), c)["draft"]["definitions"]["site.capacity"]["body"] == literal(
        10
    )
    schema["$defs"]["literal"]["properties"]["value"] = {"type": "boolean"}
    with pytest.raises(InvalidIR):
        _decode(proposal, schema, Budget(), "")
    schema = response_schema(c)
    del schema["$defs"]["literal"]
    with pytest.raises(InvalidIR):
        _decode(proposal, schema, Budget(), "")
    missing = {"format": FORMAT, "result": {"status": "needs_evidence", "summary": "Unknown source"}}
    assert decode_update(missing, Budget(), c)["status"] == "needs_evidence"
    missing["result"]["definitions"] = {}
    with pytest.raises(InvalidIR):
        decode_update(missing, Budget(), c)


def test_shared_guidance_and_both_schema_encodings_match_v1():
    golden = json.loads((Path(__file__).parent / "fixtures/v1/reference/acquisition-golden.json").read_text())
    assert digest(INSTRUCTIONS.encode()) == golden["instructions"]
    assert digest(CONSTRUCTION_INSTRUCTIONS.encode()) == golden["construction_instructions"]
    assert INSTRUCTIONS.startswith(LEARNING_ROLE) and CONSTRUCTION_INSTRUCTIONS.startswith(LEARNING_ROLE)
    assert digest(encode(complete_schema())) == golden["complete_schema"]
    assert digest(ordered_encode(complete_schema())) == golden["complete_schema_wire"]
    schema = response_schema(validate_contract())
    assert digest(encode(schema)) == golden["construction_schema"]
    assert digest(ordered_encode(schema)) == golden["construction_schema_wire"]
    # There is no model-selection argument in either grammar or shared prompt.
    assert list(complete_schema()["properties"]) == [
        "format",
        "status",
        "declarations",
        "retractions",
        "summary",
    ]
