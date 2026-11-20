"""Installing the plugin cannot overwrite an unrelated active project environment."""

import json
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def test_runtime_install_ignores_another_projects_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / "plugin"
            root.mkdir()
            (root / "plugin.json").write_text(json.dumps({"name": "awm-adm"}))
            (root / "uv.lock").touch()
            other = Path(directory) / "other-env"
            other.mkdir()
            marker = other / "keep"
            marker.write_text("existing environment")
            with (
                patch.dict(os.environ, {"UV_PROJECT_ENVIRONMENT": str(other), "VIRTUAL_ENV": str(other)}),
                patch("sys.argv", ["setup.py", "runtime", "--installed", str(root)]),
                patch("subprocess.run") as run,
            ):
                runpy.run_path(str(ROOT / "setup.py"))["main"]()
            self.assertEqual(run.call_count, 2)
            install = run.call_args_list[0]
            self.assertEqual(install.args[0][2:4], ["--project", str(root)])
            for call in run.call_args_list:
                self.assertEqual(call.kwargs["env"]["UV_PROJECT_ENVIRONMENT"], str(root / ".venv"))
                self.assertNotIn("VIRTUAL_ENV", call.kwargs["env"])
            self.assertEqual(marker.read_text(), "existing environment")
