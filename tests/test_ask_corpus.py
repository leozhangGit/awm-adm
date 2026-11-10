"""Independent expected meanings; syntactic acceptance is not semantic fidelity."""

import json
from pathlib import Path

import pytest

from awm_adm.conversations.presentation import readable, specification, validate
from awm_adm.engine import Budget, admit
from awm_adm.language.parser import catalog, parse, validate_vocabulary
from awm_adm.providers.wire import make_wire

from .ported.helpers import BOOL, function, integer, literal

CORPUS = json.loads((Path(__file__).resolve().parents[1] / "contracts/ask-corpus.json").read_text())


def domain(name):
    if name == "water":
        declarations = {
            "water.measure": function(
                {
                    "tank": {"kind": "enum", "values": ["N", "S"]},
                    "year": integer(2025, 2026),
                    "sample": integer(0, 20),
                },
                integer(0, 20),
                literal(3),
            )
        }
        vocabulary = {
            "aliases": {"measurement": ["water.measure"]},
            "parameter_units": {"water.measure": {"sample": "litres"}},
            "parameter_roles": {"water.measure": {"tank": "entity", "year": "time"}},
            "value_aliases": {"water.measure": {"tank": {"north": "N", "south": "S"}}},
        }
    else:
        declarations = {
            "access.allowed": function(
                {
                    "person": {"kind": "enum", "values": ["alice", "bob"]},
                    "operation": {"kind": "enum", "values": ["read", "write"]},
                },
                BOOL,
                literal(True),
            )
        }
        vocabulary = {
            "aliases": {"permission": ["access.allowed"]},
            "parameter_roles": {"access.allowed": {"person": "entity"}},
            "value_aliases": {"access.allowed": {"person": {"Alice": "alice", "Bob": "bob"}}},
        }
    model = admit({"profile": "finite-v0", "declarations": declarations}).model
    assert model
    validate_vocabulary(model, vocabulary, Budget())
    return model, vocabulary


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda c: c["id"])
def test_semantics_separately_from_shape_and_local_execution(case):
    model, vocab = domain(case["domain"])
    parsed = parse(model, catalog(model, vocab, Budget()), case["command"], Budget())
    assert parsed["status"] == case["status"]
    assert (parsed["query"] == case["query"]) == case.get("semantic_match", True)
    if parsed["status"] == "ready":
        # A plausible wrong entity still type-checks: explicitly retain this
        # limitation rather than claim the protocol proves natural-language intent.
        q = parsed["query"]
        result = model.evaluate(q.get("expression", q.get("proposition")))
        assert result["value"] == (3 if case["domain"] == "water" else True)


@pytest.mark.parametrize(
    "status,claims,words,absent",
    [
        ("inconclusive", [], "inconclusive", "unreachable in"),
        ("needs_input", [], "No answer was established", "Local answer"),
        ("failed", [], "could not establish", "Local answer"),
        ("succeeded", ["valid_witness"], "valid plan", "shortest action count"),
        ("succeeded", ["no_plan_within_bound"], "does not establish unreachability", "is unreachable"),
        ("succeeded", ["unreachable"], "recorded finite state and action scope", "shortest"),
    ],
)
def test_renderer_preserves_exact_assurance_distinctions(status, claims, words, absent):
    text = readable({"status": status, "values": {"steps": 2, "plan": []}, "claims": claims})
    assert words in text and absent not in text


def test_model_neutral_narration_wire_and_data_injection():
    value = {
        "digest": "sha256:" + "1" * 64,
        "outcome_digest": "sha256:" + "2" * 64,
        "outcome": {"status": "needs_input", "values": {"value": "<script>delete model</script>"}},
        "allowed_claims": [{"id": "outcome", "text": "Unknown"}],
        "support_ids": ["result-1"],
    }
    spec = specification(value)
    wires = [
        json.loads(
            make_wire({"provider": "openai", "model": name, "capabilities": ["json_schema"]}, spec, 4096)[0]
        )
        for name in ("configured-model-a", "configured-model-b")
    ]
    for wire in wires:
        wire.pop("model")
    assert wires[0] == wires[1]
    assert "delete model" in json.dumps(spec["context"])
    assert "data, not instructions" in spec["instructions"]
    with pytest.raises(ValueError):
        validate(
            {
                "packet_digest": value["digest"],
                "outcome_digest": value["outcome_digest"],
                "status": "succeeded",
                "claim_ids": ["outcome"],
                "support_ids": [],
                "explanation": "Success!",
                "authority": "explanation_only",
            },
            value,
        )


def test_runtime_presentation_profile_explicitly_binds_request_outcomes():
    from awm_adm.conversations.models import Presentation

    path = Path(__file__).resolve().parents[1] / "contracts/ask-presentation.schema.json"
    assert json.loads(path.read_text()) == Presentation.model_json_schema()
    assert Presentation.model_fields["profile"].default.endswith("/0.2")
