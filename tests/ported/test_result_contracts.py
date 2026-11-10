import unittest

from awm_adm.engine import Budget, admit
from awm_adm.engine.artifacts import digest
from awm_adm.engine.certificates import build_certificate, transition_table, verify_certificate
from awm_adm.engine.data import encode
from awm_adm.engine.planning import find_plan

from .helpers import UNIT, integer, literal, operator, variable


def action(source, target):
    return {
        "kind": "transition",
        "state": integer(0, 3),
        "parameters": UNIT,
        "legal": operator("eq", variable("state"), literal(source)),
        "next": literal(target),
    }


def chain(*, blocked=False):
    declarations = {
        "r.State": {"kind": "type", "type": integer(0, 3)},
        "r.a": action(0, 1),
        "r.b": action(1, 2),
        "r.done": {
            "kind": "goal",
            "state": integer(0, 3),
            "body": operator("eq", variable("state"), literal(3)),
        },
    }
    if not blocked:
        declarations["r.c"] = action(2, 3)
    return {"profile": "finite-v0", "declarations": declarations}


def plan_query(**extra):
    return {"op": "find_plan", "module": "r", "initial_state": 0, "goal": "r.done", **extra}


class ResultContractTests(unittest.TestCase):
    def test_selector_intent_survives_equal_resolution_and_shortcut(self):
        source = chain()
        old = admit(source).model
        all_result = find_plan(old, "r", 0, "r.done")
        fixed = find_plan(old, "r", 0, "r.done", transitions=["r.c", "r.a", "r.b"])
        self.assertEqual(all_result["scope"], fixed["scope"])
        self.assertNotEqual(all_result["binding"]["digest"], fixed["binding"]["digest"])
        self.assertEqual(all_result["binding"]["query"]["selection"], {"kind": "module_all"})
        source["declarations"]["r.shortcut"] = action(0, 3)
        new = admit(source).model
        self.assertEqual(find_plan(new, "r", 0, "r.done")["steps"], 1)
        self.assertEqual(
            find_plan(new, "r", 0, "r.done", transitions=fixed["scope"]["transitions"])["steps"], 3
        )
        self.assertEqual(
            old.symbol_dependencies(fixed["scope"]["transitions"]),
            new.symbol_dependencies(fixed["scope"]["transitions"]),
        )
        state = 0
        for step in all_result["plan"]:
            state = new.step(step["transition"], state, step["parameters"])["value"]
        self.assertEqual(state, 3)  # Valid old witness, obsolete module-wide minimum.
        self.assertEqual(
            [c["claim"] for c in all_result["assurance"]["claims"]], ["plan_valid", "shortest_action_count"]
        )

    def test_depth_exhaustion_and_resource_exhaustion_are_distinct(self):
        model = admit(chain()).model
        bounded = find_plan(model, "r", 0, "r.done", max_depth=1)
        self.assertEqual(bounded["assurance"]["claims"][0]["claim"], "no_plan_within_depth")
        self.assertEqual(bounded["binding"]["query"]["max_depth"], 1)
        limited = find_plan(model, "r", 0, "r.done", budget=Budget(1))
        self.assertEqual(limited["assurance"]["claims"], [])
        self.assertEqual(limited["outcome"], "inconclusive")
        unreachable = find_plan(admit(chain(blocked=True)).model, "r", 0, "r.done")
        self.assertEqual(unreachable["assurance"]["claims"][0]["claim"], "unreachable")

    def test_certificate_format_and_closed_scope_remain_unchanged(self):
        model = admit(chain(blocked=True)).model
        table = transition_table(model, "r", "r.done")
        self.assertNotIn("selection", table["scope"])
        cert = build_certificate(model, "r", 0, "r.done")
        raw = encode(cert)
        result = verify_certificate(model, cert)
        self.assertEqual(raw, encode(cert))
        self.assertEqual(cert["table_digest"], digest(encode(table)))
        self.assertNotIn("binding", cert)
        self.assertEqual(result["scope"]["selection"]["kind"], "explicit")
        self.assertEqual(
            result["assurance"]["claims"],
            [
                {"claim": "unreachable", "status": "established", "method": "exhaustive_finite"},
                {
                    "claim": "executable_correspondence",
                    "status": "established",
                    "method": "exhaustive_finite",
                },
            ],
        )
        changed = chain(blocked=True)
        changed["declarations"]["r.shortcut"] = action(0, 3)
        self.assertEqual(verify_certificate(admit(changed).model, cert)["status"], "rejected")
