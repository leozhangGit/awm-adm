"""Validate public source boundaries and local documentation links without reading private stores."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote

from export_release import ROOT_DIRS, ROOT_FILES, excluded

ARCHIVAL_NAMES = {"V2_PLAN.md", "V2_IMPLEMENTATION_PLAN.md", "V3_PLAN.md", "V3_IMPLEMENTATION_PLAN.md"}
PRIVATE_TOKEN = re.compile(r"(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9_-]{40,}")
PRIVATE_KEY = re.compile(r"^-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----", re.MULTILINE)


def check(root: Path) -> list[str]:
    root = root.resolve()
    failures = []
    for name in ARCHIVAL_NAMES | {"verification", "development-history"}:
        if (root / name).exists():
            failures.append(f"{name}: development history belongs outside the public repository")
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md", "SECURITY.md"):
        if not (root / name).is_file():
            failures.append(f"{name}: missing public entry point")

    def visit(path):
        if excluded(path.name):
            return
        if path.is_symlink():
            failures.append(f"{path.relative_to(root)}: source symlink")
        elif path.is_dir():
            for child in sorted(path.iterdir()):
                visit(child)
        elif path.is_file():
            inspect(path)

    def inspect(path):
        relative = path.relative_to(root).as_posix()
        if path.suffix not in {".md", ".py", ".json", ".toml", ".ts", ".tsx", ".yaml", ".yml"}:
            return
        text = path.read_text()
        if PRIVATE_KEY.search(text) or PRIVATE_TOKEN.search(text):
            failures.append(f"{relative}: possible embedded credential; value withheld")
        if re.search(r"/(?:Users|home)/[A-Za-z0-9_.-]+/", text):
            failures.append(f"{relative}: machine-specific home path")
        if path.suffix != ".md":
            return
        if "Advanced V2 tools" in text:
            failures.append(f"{relative}: obsolete console label")
        # Examples in fenced code are not documentation navigation links.
        prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        for link in re.findall(r"\]\(([^)]+)\)", prose):
            target = link.strip().strip("<>").split("#", 1)[0]
            if not target or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target):
                continue
            resolved = (path.parent / unquote(target)).resolve()
            if not resolved.is_relative_to(root):
                failures.append(f"{relative}: documentation link escapes repository: {target}")
            elif not resolved.exists():
                failures.append(f"{relative}: missing documentation target: {target}")

    for name in sorted(ROOT_FILES | ROOT_DIRS):
        path = root / name
        if path.exists() or path.is_symlink():
            visit(path)
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    failures = check(args.root)
    print(json.dumps({"status": "failed" if failures else "passed", "failures": failures}, indent=2))
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
