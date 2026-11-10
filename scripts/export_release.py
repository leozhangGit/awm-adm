"""Export the standalone product, excluding private data and development history."""

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import tomllib
from pathlib import Path

ROOT_FILES = {
    "AGENTS.md",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "Makefile",
    "pyproject.toml",
    "uv.lock",
    "compose.yaml",
    ".dockerignore",
    ".gitignore",
    ".python-version",
}
ROOT_DIRS = {
    "config",
    "console",
    "contracts",
    "deploy",
    "docs",
    "examples",
    "scripts",
    "src",
    "tests",
}
EXCLUDED = {
    ".git",
    ".venv",
    ".cache",
    ".local",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".DS_Store",
    "verification",
    "development-history",
}


def excluded(name):
    return (
        name in EXCLUDED
        or name.startswith(".env")
        or name.endswith(
            (
                ".pyc",
                ".db",
                ".db-wal",
                ".db-shm",
                ".sqlite",
                ".sqlite3",
                ".sqlite-wal",
                ".sqlite-shm",
                ".sqlite3-wal",
                ".sqlite3-shm",
                ".log",
                ".secret",
                ".pem",
                ".key",
                ".token",
            )
        )
    )


def export(root: Path, destination: Path):
    root = root.resolve()
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Export destination must be new")
    if any(parent.is_symlink() for parent in destination.parents):
        raise ValueError("Export destination parents cannot be symlinks")
    # Never recurse into our own output, even when a caller chooses a source directory.
    if destination.is_relative_to(root) and destination.relative_to(root).parts[0] in ROOT_DIRS:
        raise ValueError("Export destination cannot be inside an exported source directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".awm-export-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "package"
        stage.mkdir()

        def copy(path, target):
            if excluded(path.name):
                return
            if path.is_symlink():
                raise ValueError(f"Source symlinks cannot be exported: {path.relative_to(root)}")
            if path.is_dir():
                target.mkdir()
                for child in sorted(path.iterdir()):
                    copy(child, target / child.name)
            elif path.is_file():
                shutil.copyfile(path, target)
                target.chmod(0o644)
            else:
                raise ValueError("Only regular source files and directories may be exported")

        for name in sorted(ROOT_FILES | ROOT_DIRS):
            if (root / name).exists() or (root / name).is_symlink():
                copy(root / name, stage / name)
        metadata = tomllib.loads((stage / "pyproject.toml").read_text())
        project = metadata["project"]
        release_status = (
            metadata.get("tool", {})
            .get("awm-adm", {})
            .get("release", {})
            .get("status", "candidate_pending_joint_acceptance")
        )
        if release_status not in ("candidate_pending_joint_acceptance", "local_technical_release"):
            raise ValueError("Unknown source release status")
        files = {
            p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(stage.rglob("*"))
            if p.is_file()
        }
        manifest = {
            "profile": "awm-adm-source-release/1",
            "version": project["version"],
            "release_status": release_status,
            "target_platforms": ["linux/arm64"],
            "no_development_cache": True,
            "no_instance_data_or_credentials": True,
            "files": files,
        }
        (stage / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        os.rename(stage, destination)
    return manifest


def verify(root):
    manifest = json.loads((root / "release-manifest.json").read_text())
    actual = {}
    for p in root.rglob("*"):
        if p.is_symlink():
            raise ValueError("Export contains a symlink")
        if p.is_file() and p != root / "release-manifest.json":
            actual[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    if actual != manifest["files"]:
        raise ValueError("Export inventory or content differs from its manifest")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    manifest = (
        verify(args.destination)
        if args.verify
        else export(Path(__file__).resolve().parents[1], args.destination)
    )
    print(
        json.dumps(
            {
                "status": "verified" if args.verify else "exported",
                "version": manifest["version"],
                "files": len(manifest["files"]),
                "destination": str(args.destination.absolute()),
            }
        )
    )


if __name__ == "__main__":
    main()
