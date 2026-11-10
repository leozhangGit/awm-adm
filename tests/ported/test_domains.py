import unittest
from unittest.mock import patch

from awm_adm.engine import admit
from awm_adm.engine.errors import EvaluationError, IllegalAction

from .helpers import fixture


class DomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tanks = admit(fixture("tanks")).model
        cls.access = admit(fixture("access")).model
        assert cls.tanks is not None and cls.access is not None

    def test_every_tank_transition_against_reference_behavior(self):
        # Reference behavior is independent Python over the fixture's physical rules.
        for left in range(6):
            for right in range(4):
                state = {"left": left, "right": right}
                lr, rl = min(left, 3 - right), min(right, 5 - left)
                outcomes = {
                    "fill_left": (left < 5, (5, right)),
                    "fill_right": (right < 3, (left, 3)),
                    "empty_left": (left > 0, (0, right)),
                    "empty_right": (right > 0, (left, 0)),
                    "pour_left_right": (lr > 0, (left - lr, right + lr)),
                    "pour_right_left": (rl > 0, (left + rl, right - rl)),
                }
                for action, (legal, expected) in outcomes.items():
                    with self.subTest(state=state, action=action):
                        if not legal:
                            with self.assertRaises(IllegalAction):
                                self.tanks.step("tanks." + action, state, {})
                        else:
                            result = self.tanks.step("tanks." + action, state, {})
                            self.assertEqual(result["value"], dict(zip(("left", "right"), expected)))
                            self.assertEqual(result["cost"], 1)
                            self.assertEqual(result["theory_version"], self.tanks.version)

    def test_replay_six_step_tank_witness(self):
        state = {"left": 0, "right": 0}
        self.assertFalse(self.tanks.goal("tanks.four_litres", state)["value"])
        actions = [
            "fill_left",
            "pour_left_right",
            "empty_right",
            "pour_left_right",
            "fill_left",
            "pour_left_right",
        ]
        expected = [(5, 0), (2, 3), (2, 0), (0, 2), (5, 2), (4, 3)]
        for action, pair in zip(actions, expected):
            state = self.tanks.step("tanks." + action, state, {})["value"]
            self.assertEqual(state, dict(zip(("left", "right"), pair)))
        self.assertTrue(self.tanks.goal("tanks.four_litres", state)["value"])

    def test_access_truth_table_and_actions(self):
        closed = {"tag": "closed", "value": {}}
        states = [closed] + [{"tag": "open", "value": who} for who in ("alice", "bob")]
        for state in states:
            for actor in ("alice", "bob"):
                with self.subTest(state=state, actor=actor):
                    result = self.access.call("access.authorized", {"permission": state, "actor": actor})
                    self.assertEqual(result["value"], state == {"tag": "open", "value": actor})
                    if state == closed:
                        grant = self.access.step("access.grant", state, actor)
                        self.assertEqual(grant["value"], {"tag": "open", "value": actor})
                    else:
                        with self.assertRaises(IllegalAction):
                            self.access.step("access.grant", state, actor)
            if state == closed:
                with self.assertRaises(IllegalAction):
                    self.access.step("access.revoke", state, {})
            else:
                self.assertEqual(self.access.step("access.revoke", state, {})["value"], closed)

    def test_invalid_operational_inputs(self):
        for state in (
            {"left": True, "right": 0},
            {"left": 6, "right": 0},
            {"left": 1},
            {"left": 1, "right": 0, "extra": 1},
        ):
            with self.subTest(state=state), self.assertRaises(EvaluationError):
                self.tanks.step("tanks.fill_left", state, {})
        with self.assertRaises(EvaluationError):
            self.access.step("access.grant", {"tag": "closed", "value": {}}, "unknown-person")

    def test_admission_and_execution_with_network_disabled(self):
        with patch("socket.socket", side_effect=AssertionError("Network access is forbidden")):
            model = admit(fixture("access")).model
            self.assertIsNotNone(model)
            self.assertTrue(model.goal("access.bob_access", {"tag": "open", "value": "bob"})["value"])

    def test_all_four_presentations_are_checked(self):
        reports = {**self.tanks.report["presentations"], **self.access.report["presentations"]}
        self.assertEqual(
            {r["construction"] for r in reports.values()}, {"product", "coproduct", "pullback", "equalizer"}
        )
        self.assertEqual({r["guarantee"] for r in reports.values()}, {"exhaustive_finite"})

    def test_dependency_closure_includes_capacity_and_state_types(self):
        closure = self.tanks.dependencies("tanks.pour_right_left", transitive=True)
        self.assertTrue(
            {"tanks.State", "tanks.Left", "tanks.Right", "tanks.capacity", "tanks.space_left"}
            <= closure.keys()
        )
        self.assertEqual(closure["tanks.capacity"], self.tanks.index["tanks.capacity"])


if __name__ == "__main__":
    unittest.main()
