import unittest

from awm_adm.engine import Budget, admit
from awm_adm.engine.errors import EvaluationError, InvalidIR, KnowledgeGap, TypeMismatch
from awm_adm.engine.planning import find_plan

from .helpers import BOOL, UNIT, fixture, integer, literal, operator, theory, variable


def counter_model():
    # Even states form a closed cycle; the odd target is valid but unreachable.
    carrier = integer(0, 3)
    return admit(
        theory(
            **{
                "counter.advance": {
                    "kind": "transition",
                    "state": carrier,
                    "parameters": UNIT,
                    "legal": literal(True),
                    "next": {
                        "op": "if",
                        "condition": operator("eq", variable("state"), literal(0)),
                        "then": literal(2),
                        "else": literal(0),
                    },
                },
                "counter.target": {
                    "kind": "goal",
                    "state": carrier,
                    "body": operator("eq", variable("state"), literal(1)),
                },
            }
        )
    ).model


class PlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tanks = admit(fixture("tanks")).model
        cls.access = admit(fixture("access")).model

    def tanks_plan(self, **options):
        return find_plan(self.tanks, "tanks", {"left": 0, "right": 0}, "tanks.four_litres", **options)

    def test_shortest_tank_plan_and_independent_replay(self):
        result = self.tanks_plan()
        self.assertEqual(result["outcome"], "found")
        self.assertEqual(result["steps"], 6)
        self.assertTrue(result["witness_replayed"])
        state = result["initial_state"]
        for action in result["plan"]:
            state = self.tanks.step(action["transition"], state, action["parameters"])["value"]
        self.assertEqual(state, result["final_state"])
        self.assertTrue(self.tanks.goal("tanks.four_litres", state)["value"])
        self.assertIn("tanks.capacity", result["dependencies"])

    def test_depth_limit_does_not_claim_unreachable(self):
        result = self.tanks_plan(max_depth=5)
        self.assertEqual(result["outcome"], "no_plan_within_depth")
        self.assertFalse(result["complete_reachable_graph"])
        self.assertEqual(self.tanks_plan(max_depth=6)["steps"], 6)

    def test_zero_step_plan(self):
        result = find_plan(self.tanks, "tanks", {"left": 4, "right": 0}, "tanks.four_litres", max_depth=0)
        self.assertEqual(result["plan"], [])
        self.assertEqual(result["steps"], 0)

    def test_parameter_enumeration_in_different_domain(self):
        result = find_plan(self.access, "access", {"tag": "closed", "value": {}}, "access.bob_access")
        self.assertEqual(result["steps"], 1)
        self.assertEqual(result["plan"][0]["parameters"], "bob")

    def test_closed_cycle_is_exhausted_once(self):
        model = counter_model()
        self.assertIsNotNone(model)
        result = find_plan(model, "counter", 0, "counter.target")
        self.assertEqual(result["outcome"], "unreachable")
        self.assertTrue(result["complete_reachable_graph"])
        self.assertEqual(result["statistics"]["states_expanded"], 2)

    def test_explicit_action_scope(self):
        result = self.tanks_plan(transitions=[])
        self.assertEqual(result["outcome"], "unreachable")
        self.assertEqual(result["scope"]["transitions"], [])
        self.assertEqual(result["statistics"]["states_discovered"], 1)

    def test_resource_exhaustion_is_inconclusive(self):
        for options in (
            {"max_states": 1},
            {"max_search_bytes": 1},
            {"budget": Budget(max_work=1)},
            {"budget": Budget(max_seconds=1e-12)},
        ):
            with self.subTest(options=options):
                result = self.tanks_plan(**options)
                self.assertEqual(result["outcome"], "inconclusive")
                self.assertIsNone(result["guarantee"])
                self.assertNotIn("plan", result)

    def test_scope_and_input_errors(self):
        for options in (
            {"max_depth": -1},
            {"max_states": True},
            {"transitions": ["tanks.fill_left", "tanks.fill_left"]},
            {"transitions": ["access.grant"]},
        ):
            with self.subTest(options=options), self.assertRaises(InvalidIR):
                self.tanks_plan(**options)
        with self.assertRaises(KnowledgeGap):
            self.tanks_plan(transitions=["tanks.unknown"])
        with self.assertRaises(EvaluationError):
            find_plan(self.tanks, "tanks", {"left": 6, "right": 0}, "tanks.four_litres")

    def test_mixed_carriers_require_explicit_selection(self):
        document = fixture("tanks")
        document["declarations"]["tanks.switch"] = {
            "kind": "transition",
            "state": BOOL,
            "parameters": UNIT,
            "legal": literal(True),
            "next": operator("not", variable("state")),
        }
        model = admit(document).model
        self.assertIsNotNone(model)
        with self.assertRaises(TypeMismatch):
            find_plan(model, "tanks", {"left": 0, "right": 0}, "tanks.four_litres")
        result = find_plan(model, "tanks", {"left": 0, "right": 0}, "tanks.four_litres", transitions=[])
        self.assertEqual(result["outcome"], "unreachable")
