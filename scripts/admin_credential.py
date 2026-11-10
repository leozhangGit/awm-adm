"""Issue a local setup/reset credential through the separate operator container."""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("purpose", choices=("bootstrap", "recovery"))
    parser.add_argument("--project", help="Compose project; inherited Compose configuration otherwise")
    args = parser.parse_args(argv)
    if args.project and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", args.project):
        parser.error("Use a valid Compose project name")
    if os.getuid() == 0:
        parser.error("Run as the local non-root installation owner")
    root = Path(__file__).resolve().parents[1]
    directory = root / ".local/admin-credentials"
    if (root / ".local").is_symlink() or directory.is_symlink():
        parser.error("Credential directory must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    name = args.purpose + "-" + uuid4().hex + ".token"
    command = ["docker", "compose"]
    if args.project:
        command += ["--project-name", args.project]
    command += [
        "run",
        "--rm",
        "--no-deps",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--volume",
        f"{directory}:/credentials",
        "operator",
        args.purpose,
        "--output",
        "/credentials/" + name,
    ]
    result = subprocess.run(command, cwd=root, check=False)
    if result.returncode:
        print(
            "Credential issuance failed. Check this installation's operator configuration.", file=sys.stderr
        )
        return 1
    path = directory / name
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o777 != 0o600:
        raise RuntimeError("Operator did not create the expected private credential file")
    print(f"Credential file: {path}")
    print("Read this file locally and paste its value into the account form. Remove it after use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
