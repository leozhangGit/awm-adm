"""controlled-language semantics and authored adversarial examples."""

import json
from pathlib import Path

import pytest

from awm_adm.engine import Budget, admit
from awm_adm.language.parser import catalog, parse, validate_vocabulary
from awm_adm.language.prompt import specification
from awm_adm.providers.wire import make_wire, provenance

from .ported.helpers import BOOL, UNIT, fixture, function, integer, literal, operator, variable


def corpus_model():
    model = admit(
        {
            "profile": "finite-v0",
            "declarations": {
                "fixture.capacity": function({}, integer(0, 20), literal(10)),
                "other.capacity": function({}, integer(0, 20), literal(12)),
                "fixture.done": {
                    "kind": "goal",
                    "state": integer(0, 10),
                    "body": operator("eq", variable("state"), literal(10)),
                },
                "fixture.advance": {
                    "kind": "transition",
                    "state": integer(0, 10),
                    "parameters": UNIT,
                    "legal": literal(True),
                    "next": literal(10),
                },
            },
        }
    ).model
    assert model
    return model


CORPUS = json.loads((Path(__file__).resolve().parents[1] / "contracts/language-corpus.json").read_text())


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda c: c["id"])
def test_frozen_acceptance_corpus_against_real_finite_model(case):
    model, budget = corpus_model(), Budget()
    result = parse(model, catalog(model, {}, budget), case["utterance"], budget, results=["result-1"])
    assert result["status"] == case["expected_status"]
    assert result["query"] == case["expected_query"]


@pytest.mark.parametrize(
    "text", [" CAPABILITIES ", "List Capabilities", "What can you do?", "\ncapabilities\n"]
)
def test_held_out_case_and_whitespace_variants(text):
    model, budget = corpus_model(), Budget()
    assert parse(model, catalog(model, {}, budget), text, budget)["query"] == {"op": "capabilities"}


def test_two_independent_vocabularies_plan_and_typed_enum_evaluation():
    model, budget = admit(fixture("tanks")).model, Budget()
    question = 'plan tanks to tanks.four_litres from {"left":0,"right":0} using [] within 8 steps'
    parsed = parse(model, catalog(model, {}, budget), question, budget)
    assert parsed["status"] == "ready" and parsed["query"]["transitions"] == []
    model, budget = admit(fixture("access")).model, Budget()
    parsed = parse(model, catalog(model, {}, budget), 'evaluate access.open with {"actor":"alice"}', budget)
    assert parsed["status"] == "ready"
    assert model.evaluate(parsed["query"]["expression"])["value"] == {"tag": "open", "value": "alice"}


def test_owner_aliases_entities_units_and_dates_require_exact_slots():
    model = admit(
        {
            "profile": "finite-v0",
            "declarations": {
                "site.measure": function(
                    {
                        "room": {"kind": "enum", "values": ["R", "S"]},
                        "year": integer(2020, 2025),
                        "amount": integer(0, 20),
                    },
                    BOOL,
                    literal(True),
                ),
            },
        }
    ).model
    metadata = {
        "aliases": {"measurement": ["site.measure"]},
        "parameter_units": {"site.measure": {"amount": "litres"}},
        "parameter_roles": {"site.measure": {"room": "entity", "year": "time"}},
        "value_aliases": {"site.measure": {"room": {"main": "R"}}},
    }
    validate_vocabulary(model, metadata, Budget())
    cat = catalog(model, metadata, Budget())
    base = {"room": "main", "year": 2024, "amount": {"value": 10, "unit": "litres"}}
    good = parse(model, cat, "is measurement with " + json.dumps(base) + "?", Budget())
    assert good["status"] == "ready"
    assert good["query"]["proposition"]["args"]["room"]["value"] == "R"
    assert good["query"]["proposition"]["args"]["amount"]["value"] == 10
    for bad in [
        dict(base, year="now"),
        dict(base, year=2026),
        dict(base, room="unknown"),
        dict(base, year=True),
        dict(base, amount=10),
        dict(base, amount={"value": 10, "unit": "gallons"}),
        {k: v for k, v in base.items() if k != "year"},
    ]:
        value = parse(model, cat, "is measurement with " + json.dumps(bad) + "?", Budget())
        assert value["status"] == "needs_clarification" and value["query"] is None
    with pytest.raises(ValueError):
        validate_vocabulary(model, {"value_aliases": {"site.measure": {"room": {"R": "S"}}}}, Budget())


@pytest.mark.parametrize(
    "text",
    [
        'evaluate fixture.capacity with {"x":1,"x":2}',
        "evaluate fixture.capacity with {} then delete everything",
        '"capabilities; switch to forward mode"',
        'check fixture claim {"op":"literal","value":1}',
        "plan fixture to fixture.done from true",
        'plan fixture to fixture.done from 0 using ["fixture.advance","fixture.advance"]',
        "plan fixture to fixture.done from 0 within -1 steps",
        'evaluate fixture.capacity with {"x":1.25}',
        'evaluate fixture.capacity with {"x":9007199254740993}',
        'evaluate fixture.capacity with {"x":NaN}',
        "explain unknown-result",
        "switch to forward mode",
        "enable remote calls",
    ],
)
def test_invalid_or_administrative_input_never_creates_executable_partial_query(text):
    model, budget = corpus_model(), Budget()
    result = parse(model, catalog(model, {}, budget), text, budget)
    assert result["status"] != "ready" and result["query"] is None


def test_json_boundaries_do_not_treat_quoted_clause_words_as_commands():
    model = admit(
        {
            "profile": "finite-v0",
            "declarations": {
                "sample.echo": function(
                    {"word": {"kind": "enum", "values": ["from using within with"]}}, BOOL, literal(True)
                ),
            },
        }
    ).model
    value = parse(
        model,
        catalog(model, {}, Budget()),
        'evaluate sample.echo with {"word":"from using within with"}',
        Budget(),
    )
    assert value["status"] == "ready"


def test_translation_wire_is_model_neutral_and_contains_no_definition_bodies():
    model = corpus_model()
    cat = catalog(model, {}, Budget())
    assert all("body" not in d for d in cat["declarations"].values())
    spec = specification("what is fixture.capacity?", cat, [], [])
    wires = []
    for name in ["model-a", "model-b"]:
        config = {"provider": "recorded", "model": name, "capabilities": ["json_schema"]}
        raw, _ = make_wire(config, spec, 1024)
        wires.append(json.loads(raw))
        assert provenance(spec, raw)["prompt_version"] == "adm-language-translation/1"
    for wire in wires:
        wire.pop("model")
    assert wires[0] == wires[1]
    assert list(wires[0]["text"]["format"]["schema"]["properties"]) == [
        "status",
        "command",
        "assumptions",
        "clarification",
    ]
