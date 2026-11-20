"""Prepare this local marketplace or an installed plugin runtime; no service/provider calls."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["marketplace", "runtime"])
    parser.add_argument("--installed", type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    if args.action == "marketplace":
        target = source.parent / ".agents/plugins/marketplace.json"
        catalog = (source / "marketplace.template.json").read_bytes()
        if target.is_symlink() or (target.exists() and target.read_bytes() != catalog):
            parser.error("A different marketplace already exists; preserve it and resolve the collision.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(catalog)
        print(target)
        return
    if not args.installed:
        parser.error("Use --installed with the path returned by the native plugin installer.")
    root = args.installed.resolve(strict=True)
    manifest = json.loads((root / "plugin.json").read_text())
    if manifest.get("name") != "awm-adm" or not (root / "uv.lock").is_file():
        parser.error("The selected directory is not the AWM-ADM plugin package.")
    runtime = root / ".venv"
    if runtime.is_symlink():
        parser.error("Refusing a linked runtime directory.")
    python = runtime / "bin/python"
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(name, None)
    # An active project shell must not redirect this installation into its own venv.
    env["UV_PROJECT_ENVIRONMENT"] = str(runtime)
    if python.exists():
        result = subprocess.run(
            [str(python), "-I", "-c", "import sys; print(sys.prefix)"],
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode or Path(result.stdout.strip()).resolve() != runtime:
            shutil.rmtree(runtime)  # Only this package's copied, unusable virtual environment.
    subprocess.run(
        ["uv", "sync", "--project", str(root), "--locked", "--no-editable", "--python", "3.13"],
        cwd=root,
        check=True,
        env=env,
    )
    subprocess.run(
        [str(python), "-I", "-c", "import awm_adm_plugin.server; print('AWM-ADM runtime ready')"],
        cwd=root,
        check=True,
        env=env,
    )


if __name__ == "__main__":
    sys.exit(main())
