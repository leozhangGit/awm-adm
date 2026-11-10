import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from awm_adm.engine import Budget, admit
from awm_adm.engine.certificates import build_certificate, transition_table, verify_certificate
from awm_adm.engine.errors import Interrupted, InvalidIR, Rejected, ResourceLimit
from awm_adm.engine.lean_backend import LeanBackend, render_source

from .helpers import fixture


def access_certificate(model):
    return build_certificate(
        model, "access", {"tag": "closed", "value": {}}, "access.bob_access", transitions=["access.revoke"]
    )


class CertificateTests(unittest.TestCase):
    def setUp(self):
        self.model = admit(fixture("access")).model
        self.certificate = access_certificate(self.model)

    def test_table_matches_independent_access_rules_including_all_parameters(self):
        table = transition_table(self.model, "access", "access.bob_access")
        self.assertEqual(
            table["states"],
            [
                {"tag": "closed", "value": {}},
                {"tag": "open", "value": "alice"},
                {"tag": "open", "value": "bob"},
            ],
        )
        self.assertEqual(table["goals"], [2])
        self.assertEqual(
            table["edges"],
            [
                {"source": 0, "target": 1, "action": {"transition": "access.grant", "parameters": "alice"}},
                {"source": 0, "target": 2, "action": {"transition": "access.grant", "parameters": "bob"}},
                {"source": 1, "target": 0, "action": {"transition": "access.revoke", "parameters": {}}},
                {"source": 2, "target": 0, "action": {"transition": "access.revoke", "parameters": {}}},
            ],
        )

    def test_invariant_proves_unbounded_exclusion_in_explicit_scope(self):
        with patch("socket.socket", side_effect=AssertionError("Verification must be local")):
            result = verify_certificate(self.model, self.certificate)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["guarantee"], "exhaustive_finite")
        self.assertEqual(result["scope"]["path_length"], "any_nonnegative_integer")
        self.assertEqual(result["scope"]["transitions"], ["access.revoke"])
        self.assertEqual(result["correspondence"]["states"], 3)

    def test_enabling_grant_makes_goal_reachable(self):
        with self.assertRaises(Rejected):
            build_certificate(self.model, "access", {"tag": "closed", "value": {}}, "access.bob_access")

    def test_rejects_zero_step_goal_even_without_actions(self):
        with self.assertRaises(Rejected):
            build_certificate(
                self.model, "access", {"tag": "open", "value": "bob"}, "access.bob_access", transitions=[]
            )

    def test_rejects_each_invalid_premise(self):
        for invariant in (
            [],
            [{"tag": "open", "value": "alice"}],
            [{"tag": "closed", "value": {}}, {"tag": "open", "value": "bob"}],
            [{"tag": "closed", "value": {}}, {"tag": "closed", "value": {}}],
            [{"tag": "closed", "value": {}}, {"tag": "open", "value": "eve"}],
        ):
            with self.subTest(invariant=invariant):
                certificate = {**self.certificate, "invariant_states": invariant}
                result = verify_certificate(self.model, certificate)
                self.assertEqual(result["status"], "rejected")
                self.assertIsNone(result["guarantee"])
        certificate = build_certificate(
            self.model,
            "access",
            {"tag": "open", "value": "alice"},
            "access.bob_access",
            transitions=["access.revoke"],
            invariant_states=[{"tag": "open", "value": "alice"}],
        )
        self.assertIn("preserved", verify_certificate(self.model, certificate)["error"]["message"])

    def test_rejects_stale_theory_dependency_table_and_scope(self):
        changes = {
            "theory_version": "sha256:" + "0" * 64,
            "dependencies": {},
            "table_digest": "sha256:" + "0" * 64,
            "transitions": ["access.grant", "access.revoke"],
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                result = verify_certificate(self.model, {**self.certificate, field: value})
                self.assertEqual(result["status"], "rejected")
        modified = fixture("access")
        modified["declarations"]["access.revoke"]["legal"] = {"op": "literal", "value": False}
        changed = admit(modified).model
        self.assertEqual(verify_certificate(changed, self.certificate)["status"], "rejected")

    def test_no_caller_source_report_or_table_is_accepted(self):
        for field in ("lean_source", "axioms", "checker", "table", "guarantee"):
            self.assertEqual(
                verify_certificate(self.model, {**self.certificate, field: "forged"})["status"], "rejected"
            )

    def test_inconclusive_and_unavailable_never_become_proofs(self):
        self.assertEqual(
            verify_certificate(self.model, self.certificate, budget=Budget(max_work=1))["status"],
            "inconclusive",
        )
        self.assertEqual(
            verify_certificate(self.model, self.certificate, backend="lean")["status"], "unavailable"
        )
        with patch("awm_adm.engine.certificates.MAX_STATES", 1):
            self.assertEqual(verify_certificate(self.model, self.certificate)["status"], "inconclusive")
        with patch("awm_adm.engine.certificates.MAX_EDGES", 1):
            self.assertEqual(verify_certificate(self.model, self.certificate)["status"], "inconclusive")
        with patch("awm_adm.engine.certificates.MAX_BYTES", 16):
            self.assertEqual(verify_certificate(self.model, self.certificate)["status"], "inconclusive")

    def test_tanks_invariant_and_table_against_independent_fill_empty_rules(self):
        model = admit(fixture("tanks")).model
        transitions = ["tanks.empty_left", "tanks.empty_right", "tanks.fill_left", "tanks.fill_right"]
        table = transition_table(model, "tanks", "tanks.four_litres", transitions)
        self.assertEqual(len(table["states"]), 24)
        for edge in table["edges"]:
            s = table["states"][edge["source"]]
            name = edge["action"]["transition"].split(".")[1]
            field = "left" if name.endswith("left") else "right"
            value = (5 if field == "left" else 3) if name.startswith("fill") else 0
            self.assertEqual(table["states"][edge["target"]], {**s, field: value})
        certificate = build_certificate(
            model, "tanks", {"left": 0, "right": 0}, "tanks.four_litres", transitions=transitions
        )
        self.assertEqual(
            certificate["invariant_states"],
            [
                {"left": 0, "right": 0},
                {"left": 0, "right": 3},
                {"left": 5, "right": 0},
                {"left": 5, "right": 3},
            ],
        )
        self.assertEqual(verify_certificate(model, certificate)["status"], "verified")
        with self.assertRaises(Rejected):
            build_certificate(model, "tanks", {"left": 0, "right": 0}, "tanks.four_litres")


class LeanBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.model = admit(fixture("access")).model
        self.certificate = access_certificate(self.model)
        self.backend = LeanBackend("/configured/lean")

    def check_with_output(self, code, output):
        with patch.object(
            self.backend, "_run", side_effect=[(0, "Lean (version 4.19.0, test)"), (code, output)]
        ):
            return verify_certificate(self.model, self.certificate, backend="lean", lean=self.backend)

    def test_accepts_only_clean_expected_axiom_audit(self):
        for output in (
            "'ADM.Instance.certified' depends on axioms: [sorryAx]\n",
            "'ADM.Instance.certified' depends on axioms: [Lean.ofReduceBool]\n",
            "'Other.certified' does not depend on any axioms\n",
            "warning: declaration uses sorry\n'ADM.Instance.certified' depends on axioms: []\n",
            "",
        ):
            with self.subTest(output=output):
                self.assertEqual(self.check_with_output(0, output)["status"], "rejected")
        self.assertEqual(self.check_with_output(1, "proof failed")["status"], "rejected")
        self.assertEqual(self.check_with_output(1, "maximum heartbeats exceeded")["status"], "inconclusive")

    def test_missing_and_wrong_version_are_unavailable(self):
        result = verify_certificate(self.model, self.certificate, backend="lean", lean=self.backend)
        self.assertEqual(result["status"], "unavailable")
        with patch.object(self.backend, "_run", return_value=(0, "Lean (version 4.20.0, test)")):
            self.assertEqual(
                verify_certificate(self.model, self.certificate, backend="lean", lean=self.backend)["status"],
                "unavailable",
            )

    def test_cancellation_is_propagated(self):
        with patch.object(self.backend, "_run", side_effect=Interrupted("Cancelled")):
            with self.assertRaises(Interrupted):
                verify_certificate(self.model, self.certificate, backend="lean", lean=self.backend)

    def test_rendering_never_interpolates_domain_strings(self):
        table = transition_table(self.model, "access", "access.bob_access", ["access.revoke"])
        table["states"][0] = "import Evil; run_tac malicious"
        source = render_source(table, 0, [0])
        self.assertNotIn(b"malicious", source)
        with self.assertRaises(InvalidIR):
            render_source(table, "0; malicious", [0])

    def test_subprocess_deadline_and_output_limit_kill_and_reap(self):
        import sys

        backend = LeanBackend(sys.executable)
        real_popen = subprocess.Popen
        children = []

        def launch(*args, **kwargs):
            self.assertNotIn("LEAN_PATH", kwargs["env"])
            process = real_popen(*args, **kwargs)
            children.append(process)
            return process

        with (
            tempfile.TemporaryDirectory() as folder,
            patch("awm_adm.engine.lean_backend.subprocess.Popen", side_effect=launch),
            patch.dict(os.environ, {"LEAN_PATH": "untrusted"}),
        ):
            with self.assertRaises(ResourceLimit):
                backend._run(["-c", "import time; time.sleep(30)"], folder, Budget(max_seconds=0.1))
            with self.assertRaises(ResourceLimit):
                backend._run(["-c", "print('x'*70000)"], folder, Budget(max_seconds=2))
        self.assertTrue(children)
        self.assertTrue(all(p.returncode is not None for p in children))


@unittest.skipUnless(
    os.environ.get("AWM_ADM_LEAN"), "Set AWM_ADM_LEAN to the pinned local compiler for real kernel tests"
)
class RealLeanTests(unittest.TestCase):
    def test_two_domains_with_real_lean(self):
        model = admit(fixture("access")).model
        certificate = access_certificate(model)
        backend = LeanBackend.from_env()
        result = verify_certificate(
            model, certificate, backend="lean", lean=backend, budget=Budget(max_seconds=30)
        )
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual(result["guarantee"], "lean_kernel")
        self.assertEqual(result["checker"]["axioms"], ["propext", "Quot.sound"])
        tanks = admit(fixture("tanks")).model
        certificate = build_certificate(
            tanks,
            "tanks",
            {"left": 0, "right": 0},
            "tanks.four_litres",
            transitions=["tanks.empty_left", "tanks.empty_right", "tanks.fill_left", "tanks.fill_right"],
        )
        result = verify_certificate(
            tanks, certificate, backend="lean", lean=backend, budget=Budget(max_seconds=30)
        )
        self.assertEqual(result["status"], "verified", result)

    def test_kernel_itself_rejects_false_invariant_premises(self):
        model = admit(fixture("access")).model
        table = transition_table(model, "access", "access.bob_access")
        with self.assertRaises(Rejected):
            # Direct backend test: bypass Python's premise checker to ensure
            # Lean independently rejects the grant edge escaping this set.
            LeanBackend.from_env().check(table, 0, [0], budget=Budget(max_seconds=30))
