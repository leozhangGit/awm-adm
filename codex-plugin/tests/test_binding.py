"""Durable binding/creation faults and local-only endpoint validation."""

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from awm_adm_plugin.client import Client, Problem
from awm_adm_plugin.connector import Connector
from awm_adm_plugin.journal import Journal


class Service:
    origin = "http://127.0.0.1:9527"

    def __init__(self):
        self.installation = str(uuid4())
        self.models = {}
        self.operations = {}
        self.creates = {}
        self.calls = 0
        self.lose = False

    def system(self):
        self.calls += 1
        return {"profile": "awm-adm-local/1", "installation_id": self.installation, "connection_ready": False}

    def create(self, name, identity):
        self.calls += 1
        if identity not in self.creates:
            key, operation = str(uuid4()), str(uuid4())
            self.models[key] = {
                "id": key,
                "name": name,
                "mode": "backward",
                "status": "ready",
                "revision_id": str(uuid4()),
                "policy_epoch": 0,
            }
            self.operations[operation] = {"status": "succeeded", "result": {"adm_id": key}}
            self.creates[identity] = {"operation_id": operation, "status": "received"}
        if self.lose:
            self.lose = False
            raise Problem("service_unavailable", "lost acknowledgement")
        return self.creates[identity]

    def operation(self, key):
        return self.operations[key]

    def model(self, key):
        if key not in self.models:
            raise Problem("gone", "deleted")
        return self.models[key]


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.service = Service()
        self.journal = Journal(self.root / "private")
        self.c = Connector(self.service, self.journal)

    def test_no_project_or_ambiguous_roots_never_contact_service(self):
        self.assertEqual(self.c.project(None)["state"], "no_project")
        self.assertEqual(self.c.status(None, [str(self.project), str(self.root)])["state"], "choose_project")
        self.assertEqual(self.service.calls, 0)
        self.assertFalse((self.root / "private").exists())

    def test_concurrent_creation_and_new_client_reuse(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.c.project(str(self.project)), range(8)))
        self.assertEqual(len(self.service.creates), 1)
        self.assertEqual(len({x["model"]["id"] for x in results}), 1)
        key = results[0]["model"]["id"]
        self.service.models[key]["mode"] = "forward"
        self.assertEqual(
            Connector(self.service, self.journal).project(str(self.project))["model"]["mode"], "forward"
        )
        self.assertEqual((self.root / "private").stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in (self.root / "private").iterdir()))

    def test_lost_creation_reply_uses_original_identity(self):
        self.service.lose = True
        with self.assertRaises(Problem):
            self.c.project(str(self.project))
        recovered = self.c.project(str(self.project))
        self.assertEqual(recovered["state"], "ready")
        self.assertEqual(len(self.service.creates), 1)

    def test_same_names_different_roots_and_changed_installation(self):
        other = self.root / "other" / "project"
        other.mkdir(parents=True)
        first = self.c.project(str(self.project))
        second = self.c.project(str(other))
        self.assertNotEqual(first["model"]["id"], second["model"]["id"])
        self.service.installation = str(uuid4())
        with self.assertRaises(Problem) as e:
            self.c.project(str(self.project))
        self.assertEqual(e.exception.code, "installation_changed")
        self.assertEqual(len(self.service.creates), 2)

    def test_deleted_model_is_not_replaced_automatically(self):
        first = self.c.project(str(self.project))
        del self.service.models[first["model"]["id"]]
        with self.assertRaises(Problem):
            self.c.project(str(self.project))
        self.assertEqual(len(self.service.creates), 1)

    def test_host_and_path_restrictions(self):
        for value in [
            "https://127.0.0.1:9527",
            "http://example.com:9527",
            "http://127.0.0.1:9527/api/v1",
            "http://user@localhost:9527",
            "http://localhost:9527/?x=1",
            "http://127.0.0.2:9527",
            "http://localhost:80",
        ]:
            with self.subTest(value=value), self.assertRaises(Problem):
                Client(value)
        self.assertEqual(Client("http://localhost:9527/").origin, "http://localhost:9527")
