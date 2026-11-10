import copy
import json
import unittest

from awm_adm.engine import Budget, Model, admit
from awm_adm.engine.artifacts import MemoryStore, digest
from awm_adm.engine.errors import KnowledgeGap, ResourceLimit, TypeMismatch

from .helpers import BOOL, UNIT, call, fixture, function, integer, literal, operator, theory, variable


class KernelTests(unittest.TestCase):
    def accepted(self, source):
        result = admit(source)
        self.assertEqual(result.status, "accepted", result.report)
        self.assertIsNotNone(result.model)
        return result.model

    def inactive(self, source, code=None, status="rejected", budget=None):
        result = admit(source, budget=budget)
        self.assertEqual(result.status, status, result.report)
        self.assertIsNone(result.model)
        if code:
            self.assertEqual(result.report["error"]["code"], code)
        return result

    def test_empty_model_and_missing_knowledge(self):
        model = Model.empty()
        self.assertEqual(model.index, {})
        self.assertEqual(model.evaluate(operator("add", literal(2), literal(3)))["value"], 5)
        with self.assertRaises(KnowledgeGap):
            model.evaluate(call("missing.capacity"))

    def test_total_bounded_function_and_counterexample(self):
        t = integer(0, 2)
        x = variable("x")
        good = {
            "op": "if",
            "condition": operator("lt", x, literal(2)),
            "then": operator("add", x, literal(1)),
            "else": x,
        }
        model = self.accepted(theory(**{"test.increment": function({"x": t}, t, good)}))
        self.assertEqual([model.call("test.increment", {"x": n})["value"] for n in range(3)], [1, 2, 2])
        self.inactive(
            theory(**{"test.increment": function({"x": t}, t, operator("add", x, literal(1)))}),
            "evaluation_error",
        )

    def test_boolean_is_not_integer(self):
        self.inactive(theory(**{"test.number": function({}, integer(0, 1), literal(True))}), "type_error")
        self.inactive(
            theory(**{"test.number": function({}, integer(0, 1), literal(True, integer(0, 1)))}), "type_error"
        )

    def test_false_assertion_is_not_a_premise(self):
        self.inactive(
            theory(**{"test.false": {"kind": "assertion", "params": {}, "body": literal(False)}}),
            "admission_rejected",
        )
        x = variable("x")
        result = self.inactive(
            theory(
                **{
                    "test.claim": {
                        "kind": "assertion",
                        "params": {"x": integer(0, 3)},
                        "body": operator("lt", x, literal(3)),
                    }
                }
            ),
            "admission_rejected",
        )
        self.assertEqual(result.report["error"]["context"]["inputs"], {"x": 3})

    def test_opaque_theorems_and_unknown_constants_are_unsupported(self):
        self.inactive(
            theory(**{"test.theorem": {"kind": "theorem", "proof": "trust me"}}), "unsupported_feature"
        )
        self.inactive(
            theory(**{"test.unknown": function({}, BOOL, {"op": "unknown"})}), "unsupported_feature"
        )

    def test_unbound_variable_and_missing_dependency(self):
        self.inactive(theory(**{"test.bad": function({}, BOOL, variable("unknown"))}), "type_error")
        self.inactive(theory(**{"test.bad": function({}, BOOL, call("test.absent"))}), "knowledge_gap")

    def test_recursive_functions_and_types_are_rejected(self):
        self.inactive(
            theory(
                **{"test.a": function({}, BOOL, call("test.b")), "test.b": function({}, BOOL, call("test.a"))}
            ),
            "invalid_ir",
        )
        self.inactive(theory(**{"test.Type": {"kind": "type", "type": {"ref": "test.Type"}}}), "invalid_ir")

    def test_unreachable_branch_is_still_type_checked(self):
        expr = {"op": "if", "condition": literal(True), "then": literal(1), "else": literal(False)}
        self.inactive(theory(**{"test.bad": function({}, integer(0, 1), expr)}), "type_error")

    def test_no_host_code_operator(self):
        self.inactive(
            theory(**{"test.bad": function({}, BOOL, {"op": "python", "source": "return True"})}),
            "unsupported_feature",
        )

    def test_strict_document_shape_and_json(self):
        for source in (
            '{"profile":"finite-v0","profile":"finite-v0","declarations":{}}',
            '{"profile":"finite-v0","declarations":{},"number":NaN}',
            '{"profile":"finite-v0","declarations":{},"number":1.0}',
        ):
            with self.subTest(source=source):
                self.inactive(source, "invalid_ir")
        self.inactive({"profile": "finite-v0", "declarations": {}, "ignore_me": True}, "invalid_ir")
        self.inactive({"profile": "unknown", "declarations": {}}, "unsupported_feature")

    def test_malformed_structured_fields_produce_serializable_errors(self):
        sources = [
            {"profile": {"unsupported": True}, "declarations": {}},
            theory(**{"test.Type": {"kind": "type", "type": {"kind": {"bad": []}}}}),
            theory(**{"test.bad": function({}, BOOL, {"op": "var", "name": {"not": "a name"}})}),
        ]
        for source in sources:
            with self.subTest(source=source):
                result = self.inactive(source)
                self.assertEqual(json.loads(json.dumps(result.report)), result.report)

    def test_budget_exhaustion_does_not_accept_a_partial_check(self):
        source = theory(
            **{"test.big": function({"x": integer(0, 10**12)}, integer(0, 10**12), variable("x"))}
        )
        self.inactive(source, "resource_exhausted", "inconclusive", Budget(max_work=200))
        model = self.accepted(theory())
        with self.assertRaises(ResourceLimit):
            model.evaluate(operator("add", literal(1), literal(2)), budget=Budget(max_work=1))

    def test_empty_state_rejected_but_empty_carrier_allowed(self):
        empty = {"kind": "refined", "base": BOOL, "where": literal(False)}
        self.accepted(theory(**{"test.Empty": {"kind": "type", "type": empty}}))
        self.inactive(
            theory(**{"test.goal": {"kind": "goal", "state": empty, "body": literal(True)}}),
            "admission_rejected",
        )

    def test_unused_refinement_still_has_to_be_total(self):
        vector = {"kind": "vector", "element": BOOL, "length": 0}
        bad = {
            "kind": "refined",
            "base": vector,
            "where": {"op": "index", "vector": variable("value"), "index": literal(0)},
        }
        self.inactive(theory(**{"test.EmptyVector": {"kind": "type", "type": bad}}), "evaluation_error")

    def test_transition_preservation_is_checked(self):
        source = theory(
            **{
                "test.increment": {
                    "kind": "transition",
                    "state": integer(0, 2),
                    "parameters": UNIT,
                    "legal": literal(True),
                    "next": operator("add", variable("state"), literal(1)),
                }
            }
        )
        self.inactive(source, "evaluation_error")

    def test_refinement_preservation_is_checked(self):
        even = {
            "kind": "refined",
            "base": integer(0, 2),
            "where": operator("ne", variable("value"), literal(1)),
        }
        source = theory(
            **{
                "test.bad": {
                    "kind": "transition",
                    "state": even,
                    "parameters": UNIT,
                    "legal": literal(True),
                    "next": literal(1),
                }
            }
        )
        self.inactive(source, "evaluation_error")

    def test_vector_value_equality_and_quantifiers(self):
        vector = {"kind": "vector", "element": BOOL, "length": 2}
        expr = operator("eq", variable("v"), literal([True, False], vector))
        model = self.accepted(theory(**{"test.vector": function({"v": vector}, BOOL, expr)}))
        self.assertTrue(model.call("test.vector", {"v": [True, False]})["value"])
        self.assertFalse(model.call("test.vector", {"v": [False, True]})["value"])
        empty = {"kind": "enum", "values": []}
        for op, expected in (("forall", True), ("exists", False)):
            result = model.evaluate({"op": op, "var": "x", "type": empty, "body": literal(False)})
            self.assertIs(result["value"], expected)
        result = model.evaluate(
            {
                "op": "forall",
                "var": "x",
                "type": integer(0, 5),
                "body": operator("le", variable("x"), literal(5)),
            }
        )
        self.assertTrue(result["value"])

    def test_sum_match_must_be_exhaustive(self):
        source = fixture("access")
        del source["declarations"]["access.authorized"]["body"]["cases"]["closed"]
        self.inactive(source, "type_error")

    def test_bad_algebraic_presentations_are_rejected(self):
        corruptions = [
            ("tanks", "tanks.project_left", literal(0)),
            (
                "tanks",
                "tanks.include_goal",
                {"op": "update", "record": variable("state"), "fields": {"left": literal(0)}},
            ),
            (
                "access",
                "access.open",
                {
                    "op": "tag",
                    "type": {"ref": "access.Permission"},
                    "tag": "closed",
                    "value": literal({}, UNIT),
                },
            ),
        ]
        for domain, symbol, body in corruptions:
            with self.subTest(symbol=symbol):
                source = fixture(domain)
                source["declarations"][symbol]["body"] = body
                self.inactive(source, "admission_rejected")

    def test_missing_product_fibers_are_rejected(self):
        identity = function({"x": BOOL}, BOOL, variable("x"))
        source = theory(
            **{
                "test.identity": identity,
                "test.product": {
                    "kind": "presentation",
                    "construction": "product",
                    "carrier": BOOL,
                    "left": BOOL,
                    "right": BOOL,
                    "project_left": "test.identity",
                    "project_right": "test.identity",
                },
            }
        )
        result = self.inactive(source, "admission_rejected")
        self.assertEqual(result.report["error"]["context"]["missing"], 2)

    def test_coproduct_rejects_overlapping_images(self):
        source = theory(
            **{
                "test.left": function({"x": BOOL}, BOOL, variable("x")),
                "test.right": function({"x": UNIT}, BOOL, literal(False)),
                "test.sum": {
                    "kind": "presentation",
                    "construction": "coproduct",
                    "carrier": BOOL,
                    "left": BOOL,
                    "right": UNIT,
                    "inject_left": "test.left",
                    "inject_right": "test.right",
                },
            }
        )
        result = self.inactive(source, "admission_rejected")
        self.assertIn("uniqueness", result.report["error"]["message"])

    def test_pullback_and_equalizer_require_every_compatible_element(self):
        access = fixture("access")
        carrier = access["declarations"]["access.Authorization"]["type"]
        actor = {"op": "get", "record": variable("value"), "field": "actor"}
        carrier["where"] = operator(
            "and", carrier["where"], operator("eq", actor, literal("alice", {"ref": "access.Actor"}))
        )
        result = self.inactive(access, "admission_rejected")
        self.assertEqual(result.report["error"]["context"]["construction"], "pullback")
        self.assertEqual(result.report["error"]["context"]["missing"], 1)
        tanks = fixture("tanks")
        carrier = tanks["declarations"]["tanks.GoalState"]["type"]
        right = {"op": "get", "record": variable("value"), "field": "right"}
        carrier["where"] = operator("and", carrier["where"], operator("gt", right, literal(0)))
        result = self.inactive(tanks, "admission_rejected")
        self.assertEqual(result.report["error"]["context"]["construction"], "equalizer")
        self.assertEqual(result.report["error"]["context"]["missing"], 1)

    def test_string_domain_values_are_not_reparsed_as_json(self):
        state = {"kind": "enum", "values": ["true", "1", "null"]}
        model = self.accepted(
            theory(
                **{
                    "test.keep": {
                        "kind": "transition",
                        "state": state,
                        "parameters": UNIT,
                        "legal": literal(True),
                        "next": variable("state"),
                    }
                }
            )
        )
        for value in ("true", "1", "null"):
            self.assertEqual(model.step("test.keep", value, {})["value"], value)

    def test_inputs_and_returned_metadata_cannot_mutate_a_model(self):
        source = fixture("tanks")
        model = self.accepted(source)
        version = model.version
        source["declarations"]["tanks.capacity"]["body"]["value"] = 1
        model.document()["declarations"].clear()
        model.index.clear()
        model.report["presentations"].clear()
        self.assertEqual(model.call("tanks.capacity", {})["value"], 5)
        self.assertEqual(model.version, version)

    def test_dependency_hashes_change_with_their_premises(self):
        source = theory(
            **{
                "test.premise": function({}, BOOL, literal(False)),
                "test.consequence": function({}, BOOL, call("test.premise")),
            }
        )
        old = self.accepted(source)
        changed = copy.deepcopy(source)
        changed["declarations"]["test.premise"]["body"] = literal(True)
        new = self.accepted(changed)
        self.assertNotEqual(old.version, new.version)
        self.assertNotEqual(old.index["test.consequence"], new.index["test.consequence"])
        self.assertEqual(new.dependencies("test.consequence"), {"test.premise": new.index["test.premise"]})
        self.assertFalse(old.call("test.consequence", {})["value"])
        self.assertTrue(new.call("test.consequence", {})["value"])

    def test_stored_identity_is_independent_of_json_input_formatting(self):
        source = fixture("access")
        self.assertEqual(
            self.accepted(source).version, self.accepted(json.dumps(source, sort_keys=True)).version
        )

    def test_artifacts_hash_exact_stored_bytes(self):
        store = MemoryStore()
        key = store.put(b'{"value":10}\n')
        self.assertEqual(key, digest(store.get(key)))
        self.assertNotEqual(key, store.put(b'{ "value": 10 }\n'))
        with self.assertRaises(KnowledgeGap):
            store.get("sha256:" + "0" * 64)

    def test_wrong_call_arguments_are_errors(self):
        model = self.accepted(theory(**{"test.identity": function({"x": BOOL}, BOOL, variable("x"))}))
        with self.assertRaises(TypeMismatch):
            model.call("test.identity", {"y": True})


if __name__ == "__main__":
    unittest.main()
