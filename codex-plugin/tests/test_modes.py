"""Mode intent survives acknowledgement loss and is never inferred from teaching."""

import unittest
from uuid import uuid4

import test_binding as binding
from awm_adm_plugin.client import Problem
from awm_adm_plugin.connector import Connector


class ModeService(binding.Service):
    def __init__(self):
        super().__init__()
        self.patches = 0
        self.lose = False
        self.concurrent = False

    def mode(self, key, mode, epoch):
        self.patches += 1
        if self.concurrent:
            self.models[key]["policy_epoch"] += 1
        if self.models[key]["policy_epoch"] != epoch:
            raise Problem("stale_context", "changed")
        self.models[key].update(mode=mode, policy_epoch=epoch + 1, revision_id=str(uuid4()))
        if self.lose:
            self.lose = False
            raise Problem("service_unavailable", "lost acknowledgement")
        return self.models[key]


class ModeTests(unittest.TestCase):
    def setUp(self):
        binding.BindingTests.setUp(self)
        self.service = ModeService()
        self.c = Connector(self.service, self.journal)
        self.root = str(self.project)
        self.c.project(self.root)

    def test_explicit_forward_persists_and_explicit_backward_is_separate(self):
        with self.assertRaises(Problem):
            self.c.set_mode(self.root, mode="forward", operation="no-consent")
        self.assertEqual(self.service.patches, 0)
        self.assertEqual(
            self.c.set_mode(self.root, mode="forward", operation="forward", user_requested=True)["model"][
                "mode"
            ],
            "forward",
        )
        self.assertEqual(self.c.project(self.root)["model"]["mode"], "forward")
        self.c.set_mode(self.root, mode="forward", operation="forward", user_requested=True)
        self.assertEqual(self.service.patches, 1)
        self.c.set_mode(self.root, mode="backward", operation="backward", user_requested=True)
        self.assertEqual(self.c.status(self.root)["model"]["mode"], "backward")

    def test_lost_reply_reconciles_current_state_without_second_mutation(self):
        self.service.lose = True
        with self.assertRaises(Problem):
            self.c.set_mode(self.root, mode="forward", operation="switch", user_requested=True)
        outcome = self.c.set_mode(self.root, mode="forward", operation="switch", user_requested=True)
        self.assertEqual(outcome["state"], "reconciled")
        self.assertEqual(self.service.patches, 1)
        with self.assertRaises(Problem):
            self.c.set_mode(self.root, mode="backward", operation="switch", user_requested=True)

    def test_concurrent_change_never_rebases_a_refused_decision(self):
        self.service.concurrent = True
        with self.assertRaises(Problem):
            self.c.set_mode(self.root, mode="forward", operation="switch", user_requested=True)
        self.service.concurrent = False
        with self.assertRaises(Problem):
            self.c.set_mode(self.root, mode="forward", operation="switch", user_requested=True)
        self.assertEqual(self.service.patches, 1)
        self.assertEqual(self.c.status(self.root)["model"]["mode"], "backward")
