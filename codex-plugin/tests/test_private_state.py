"""Invalid private files fail without silently creating another project identity."""

import json
import tempfile
import unittest
from pathlib import Path

from awm_adm_plugin.client import Problem
from awm_adm_plugin.journal import Journal


class PrivateStateTests(unittest.TestCase):
    def test_corrupt_or_linked_state_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            journal = Journal(root / "state")
            with journal.project(project) as (_, save):
                save()
            saved = next((root / "state").glob("*.json"))
            original = saved.read_bytes()
            for raw in [b"{", b"[]", json.dumps({"profile": "wrong"}).encode()]:
                saved.write_bytes(raw)
                with self.assertRaises(Problem) as error, journal.project(project):
                    pass
                self.assertEqual(error.exception.code, "invalid_state")
                self.assertEqual(saved.read_bytes(), raw)
            saved.unlink()
            other = root / "other.json"
            other.write_bytes(original)
            saved.symlink_to(other)
            with self.assertRaises(Problem) as error, journal.project(project):
                pass
            self.assertEqual(error.exception.code, "unsafe_state")
            self.assertEqual(other.read_bytes(), original)
