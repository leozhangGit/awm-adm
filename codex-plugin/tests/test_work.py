"""Submission/recovery semantics independent of any provider or domain."""

import copy
import unittest
from uuid import uuid4

import test_binding as binding
from awm_adm_plugin.client import Problem
from awm_adm_plugin.connector import Connector


class WorkService(binding.Service):
    def __init__(self):
        super().__init__()
        self.messages = {}
        self.enabled = True
        self.lose_submit = False
        self.refuse = False
        self.post_count = 0

    def system(self):
        return {**super().system(), "connection_ready": self.enabled}

    def submit(self, model, channel, body, revision):
        self.post_count += 1
        key = (model, body["idempotency_key"])
        if key not in self.messages:
            if self.refuse or revision != self.models[model]["revision_id"]:
                raise Problem("stale_context", "changed")
            self.messages[key] = {
                "id": str(uuid4()),
                "idempotency_key": body["idempotency_key"],
                "channel": channel,
                "status": "running",
                "reply": None,
                "outcome": None,
                "body": body,
            }
        value = self.messages[key]
        if value["body"] != body:
            raise Problem("conflict", "different input")
        if self.lose_submit:
            self.lose_submit = False
            raise Problem("service_unavailable", "lost response")
        return copy.deepcopy(value)

    def interaction(self, model, key, *, cancel=False):
        for (m, _), v in self.messages.items():
            if m == model and v["id"] == key:
                if cancel:
                    v["status"] = "cancelled"
                return copy.deepcopy(v)
        raise Problem("not_found", "missing")

    def request_record(self, *args):
        raise Problem("not_found", "not in fixture")

    def knowledge(self, model, query, after, revision):
        return {"revision_id": revision, "items": [], "next_cursor": None, "total": 0}


class WorkTests(unittest.TestCase):
    def setUp(self):
        binding.BindingTests.setUp(self)
        self.service = WorkService()
        self.c = Connector(self.service, self.journal)
        self.path = str(self.project)
        self.c.project(self.path)

    # Binding scenarios are already tested by BindingTests, whose fixture is deliberately reused.
    def test_recovery_after_lost_reply_and_revision_change_is_one_service_message(self):
        self.service.lose_submit = True
        with self.assertRaises(Problem):
            self.c.teach(self.path, text="Keep the rule", operation="one")
        for m in self.service.models.values():
            m["revision_id"] = str(uuid4())
        resumed = self.c.work(self.path, work_id="one")
        self.assertEqual(resumed["state"], "running")
        self.assertEqual(len(self.service.messages), 1)
        self.c.teach(self.path, text="Keep the rule", operation="one")
        self.assertEqual(self.service.post_count, 2)
        with self.assertRaises(Problem):
            self.c.teach(self.path, text="Different", operation="one")
        self.assertEqual(len(self.service.messages), 1)

    def test_clarification_is_bound_to_the_same_project_and_channel(self):
        first = self.c.teach(self.path, text="Keep a capacity limit", operation="first")
        next(iter(self.service.messages.values())).update(status="needs_input", reply="Which capacity?")
        self.assertEqual(self.c.work(self.path, work_id="first")["summary"], "Which capacity?")
        self.c.teach(self.path, text="The batch capacity.", operation="reply", reply_to="first")
        self.assertEqual(list(self.service.messages.values())[1]["body"]["reply_to"], first["interaction_id"])
        with self.assertRaises(Problem):
            self.c.ask(self.path, text="What?", operation="wrong", reply_to="first")
        self.assertEqual(len(self.service.messages), 2)

    def test_disabled_connection_starts_no_work_and_known_stale_refusal_never_retries(self):
        self.service.enabled = False
        with self.assertRaises(Problem):
            self.c.ask(self.path, text="What?", operation="disabled")
        self.assertEqual(self.c.work(self.path)["total"], 0)
        self.service.enabled = True
        self.service.refuse = True
        with self.assertRaises(Problem):
            self.c.ask(self.path, text="What?", operation="stale")
        self.service.refuse = False
        self.assertEqual(self.c.work(self.path, work_id="stale")["state"], "not_submitted")
        self.assertEqual(self.service.post_count, 1)

    def test_source_child_diagnostics_survive_work_reads_without_resubmission(self):
        self.c.teach(self.path, text="Keep supplied observations", operation="source")
        failure = {
            "stage": "source_processing",
            "code": "source_processing_failed",
            "complete": True,
            "items": [
                {
                    "diagnostic": {
                        "code": "provider_timeout",
                        "job_id": "retained-job",
                        "provider_failure": {"unresolved": True, "calls": 1},
                    }
                }
            ],
        }
        next(iter(self.service.messages.values())).update(
            status="failed",
            failure_code="source_processing_failed",
            failure_diagnostics=failure,
            reply="Extraction timed out. Language setup was skipped.",
        )
        value = self.c.work(self.path, work_id="source")
        self.assertEqual(value["failure_diagnostics"], failure)
        self.assertEqual(value["failure_code"], "source_processing_failed")
        self.assertEqual(self.service.post_count, 1)

    def test_learning_capacity_diagnostics_survive_without_a_new_submission(self):
        self.c.teach(self.path, text="Save the adopted rule", operation="capacity")
        diagnostic = {
            "stage": "learning",
            "code": "learning_failed",
            "complete": True,
            "items": [
                {
                    "objective_id": "objective-one",
                    "episode_id": "episode-one",
                    "reason": "invalid_limits",
                    "diagnostic": {
                        "code": "input_capacity_exceeded",
                        "required_input_reservation": 128001,
                        "available_input_reservation": 128000,
                        "provider_call_dispatched": False,
                    },
                }
            ],
        }
        next(iter(self.service.messages.values())).update(
            status="failed",
            failure_code="invalid_limits",
            failure_diagnostics=diagnostic,
            reply="The request exceeds the configured input capacity. This call was not sent.",
        )
        for _ in range(2):
            value = self.c.work(self.path, work_id="capacity")
            self.assertEqual(value["failure_diagnostics"], diagnostic)
            self.assertEqual(value["failure_code"], "invalid_limits")
        self.assertEqual(self.service.post_count, 1)

    def test_checked_outcome_survives_explanation_failure_and_later_revision(self):
        self.c.ask(self.path, text="May it run?", operation="question")
        model = next(iter(self.service.models.values()))
        model.update(theory_version="sha256:one", support_root="sha256:support")
        message = next(iter(self.service.messages.values()))
        message.update(
            status="succeeded",
            outcome_text="Model answer: Yes",
            explanation=None,
            outcome={
                "status": "succeeded",
                "values": {"value": True},
                "binding": {"theory_root": "sha256:one", "support_root": "sha256:support", "policy_epoch": 0},
            },
        )
        value = self.c.work(self.path, work_id="question")
        self.assertTrue(value["checked_outcome"]["values"]["value"])
        self.assertIsNone(value["outcome_matches_current_model"])
        model["policy_epoch"] = 1
        self.assertFalse(self.c.work(self.path, work_id="question")["outcome_matches_current_model"])
        self.assertEqual(self.service.post_count, 1)

    def test_new_identity_allows_intentional_repeated_text_and_cancel_keeps_accepted_refs(self):
        self.c.teach(self.path, text="Keep the rule", operation="one")
        self.c.teach(self.path, text="Keep the rule", operation="two")
        message = next(iter(self.service.messages.values()))
        message["teaching"] = {
            "admissions": [
                {
                    "classification": "accepted",
                    "receipt_id": "receipt",
                    "accepted_revision": str(uuid4()),
                    "effects": {"added": ["rule"]},
                }
            ]
        }
        value = self.c.work(self.path, work_id="one", cancel=True)
        self.assertEqual(value["state"], "cancelled")
        self.assertEqual(len(value["admissions"]), 1)
        self.assertEqual(len(self.service.messages), 2)
        history = self.c.work(self.path)
        self.assertEqual(len(history["items"][0]["accepted_references"]), 1)


if __name__ == "__main__":
    unittest.main()
