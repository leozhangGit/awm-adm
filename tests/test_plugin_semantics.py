"""Independent finite examples of what a project connector may actually claim.

These are authored mappings, not a measurement of live language interpretation.
No new core semantics or production domain rules are introduced.
"""

from awm_adm.engine import Instance

from .ported.helpers import BOOL, call, function, integer, literal, operator, variable
from .test_instance import capacity_policy, constant, publish, value_query


def test_equivalent_rewrite_is_preservation_conflict_not_logical_contradiction():
    instance = Instance()
    original = constant(2)
    equivalent = function({}, integer(0, 100), operator("add", literal(1), literal(1)))
    assert publish(instance, {"site.capacity": original}, "original")["status"] == "accepted"
    before = instance.context()
    rejected = publish(instance, {"site.capacity": equivalent}, "paraphrased-same-value")
    assert rejected["status"] == "rejected"
    error = rejected["decision"]["report"]["error"]
    assert error["context"] == {"conflicts": ["site.capacity"], "mode": "backward"}
    assert instance.context() == before
    assert instance.query(value_query())["value"] == 2


def test_independently_named_statements_are_not_automatically_related():
    instance = Instance()
    assert publish(instance, {"site.capacity": constant(2)}, "initial")["status"] == "accepted"
    # A provider might paraphrase the same real concept using a different symbol.
    # The kernel sees two independent definitions, not a declared equality.
    assert publish(instance, {"site.other_capacity": constant(3)}, "alias")["status"] == "accepted"
    assert instance.query(value_query("site.capacity"))["value"] == 2
    assert instance.query(value_query("site.other_capacity"))["value"] == 3


def test_checked_requirement_violation_is_distinct_and_survives_forward_mode():
    instance = Instance()
    publish(instance, {"site.capacity": constant(2)}, "initial")
    instance.set_conformance(capacity_policy(2))
    instance.set_mode("forward")
    before = instance.context()
    rejected = publish(instance, {"site.capacity": constant(3)}, "bad")
    assert rejected["status"] == "rejected"
    assert rejected["decision"]["report"]["error"]["code"] == "conformance_failed"
    assert instance.context() == before


def relation(pairs):
    # An explicitly closed finite relation. Absence is false only within this fixture.
    terms = [
        operator("and", operator("eq", variable("x"), literal(x)), operator("eq", variable("y"), literal(y)))
        for x, y in pairs
    ]
    return function({"x": integer(0, 2), "y": integer(0, 2)}, BOOL, operator("or", *terms))


def strict_order_requirement():
    x, y, z = variable("x"), variable("y"), variable("z")
    return {
        "profile": "adm-conformance/0.1",
        "contracts": [
            {
                "contract_id": "strict-order",
                "origin": "Independent authored finite-order requirement",
                "required_symbols": ["order.greater"],
                "checks": [
                    {
                        "id": "irreflexive",
                        "kind": "value",
                        "params": {"x": integer(0, 2)},
                        "expression": call("order.greater", x=x, y=x),
                        "expected": literal(False),
                    },
                    {
                        "id": "transitive",
                        "kind": "value",
                        "params": {n: integer(0, 2) for n in ("x", "y", "z")},
                        "expression": operator(
                            "or",
                            operator(
                                "not",
                                operator(
                                    "and", call("order.greater", x=x, y=y), call("order.greater", x=y, y=z)
                                ),
                            ),
                            call("order.greater", x=x, y=z),
                        ),
                        "expected": literal(True),
                    },
                ],
            }
        ],
    }


def test_targeted_order_replacement_retires_old_derivation_and_does_not_replay():
    # 0=A, 1=B, 2=C. Authored transitive closure of A>B and B>C.
    instance = Instance()
    definitions = {
        "order.greater": relation([(0, 1), (1, 2), (0, 2)]),
        "order.a_greater_c": function({}, BOOL, call("order.greater", x=literal(0), y=literal(2))),
    }
    assert publish(instance, definitions, "chain")["status"] == "accepted"
    instance.set_conformance(strict_order_requirement())
    assert instance.query(value_query("order.a_greater_c"))["value"] is True
    replacement = {"order.greater": relation([(0, 1), (2, 1)])}
    before = instance.context()
    assert publish(instance, replacement, "backward-reversal")["status"] == "rejected"
    assert instance.context() == before
    instance.set_mode("forward")
    assert instance.query(value_query("order.a_greater_c"))["value"] is True
    accepted = publish(instance, replacement, "fresh-forward-reversal")
    assert accepted["status"] == "accepted"
    assert accepted["decision"]["report"]["removed"] == ["order.a_greater_c"]
    assert "order.a_greater_c" not in instance.model.index
    assert instance.model.call("order.greater", {"x": 0, "y": 2})["value"] is False
    assert instance.candidate("backward-reversal")["status"] == "rejected"
    cyclic = {"order.greater": relation([(0, 1), (1, 0)])}
    refused = publish(instance, cyclic, "cyclic-forward-proposal")
    assert refused["status"] == "rejected"
    assert refused["decision"]["report"]["error"]["code"] == "conformance_failed"
    instance.set_mode("backward")
    assert instance.model.call("order.greater", {"x": 2, "y": 1})["value"] is True
