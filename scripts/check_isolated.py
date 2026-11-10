"""Export, install non-editably, and test the product using offline dependency caches."""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from export_release import export as export_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default="python3", help="Installed Python 3.13 executable")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    uv = root / ".venv/bin/uv"
    python = Path(shutil.which(args.python) or args.python).resolve()
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        env.pop(name, None)
    env["UV_NO_MANAGED_PYTHON"] = "1"
    records = []

    def run(command, cwd):
        completed = subprocess.run(
            [str(x) for x in command],
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        records.append(
            {
                "command": [str(x) for x in command],
                "exit_code": completed.returncode,
                "output": completed.stdout,
            }
        )
        if completed.returncode:
            raise RuntimeError("Isolated command failed")

    with tempfile.TemporaryDirectory(prefix="awm-adm-isolated-") as temporary:
        # macOS exposes its temporary directory through /var -> /private/var.
        # Resolve that trusted base before the exporter rejects source/destination links.
        export = Path(temporary).resolve() / "awm-adm"
        # Exercise the same explicit public-file boundary used by release packaging.
        export_source(root, export)
        try:
            run(
                [
                    uv,
                    "sync",
                    "--locked",
                    "--offline",
                    "--no-editable",
                    "--no-python-downloads",
                    "--cache-dir",
                    root / ".cache/uv",
                    "--python",
                    python,
                ],
                export,
            )
            isolated_python = export / ".venv/bin/python"
            run(
                [
                    isolated_python,
                    "-I",
                    "-c",
                    "import awm_adm, pathlib, sys; p=pathlib.Path(awm_adm.__file__).resolve(); assert p.is_relative_to(pathlib.Path(sys.prefix).resolve()); print(p)",
                ],
                export,
            )
            run([isolated_python, "-I", "-m", "pytest", "-q"], export)
            run([isolated_python, "scripts/check_boundaries.py"], export)
            run([isolated_python, "scripts/check_public_release.py"], export)
            run([isolated_python, "-I", "-m", "awm_adm", "check-config", "config/default.toml"], export)
            run(
                [
                    isolated_python,
                    "-I",
                    "-m",
                    "awm_adm",
                    "schemas",
                    "--output",
                    "contracts/schemas",
                    "--check",
                ],
                export,
            )
            run([isolated_python, "-I", "-m", "hatchling", "build", "-t", "wheel"], export)
            run(
                ["npm", "ci", "--offline", "--ignore-scripts", "--cache", root / ".cache/npm"],
                export / "console",
            )
            run(["npm", "run", "build"], export / "console")
            run(["npm", "run", "format:check"], export / "console")
            run(["npm", "test"], export / "console")
        except RuntimeError:
            print(json.dumps({"status": "failed", "commands": records}, indent=2))
            return 1
        print(
            json.dumps(
                {
                    "status": "passed",
                    "export_temporary": True,
                    "parent_project_installed": False,
                    "dependency_network_enabled": False,
                    "commands": records,
                },
                indent=2,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
