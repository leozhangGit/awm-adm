"""Release tooling preserves locked provenance and refuses unsafe rehearsal inputs."""

import hashlib
import importlib.metadata
import json
import runpy
import subprocess
import sys
import tomllib
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
inventory = runpy.run_path(str(ROOT / "scripts/dependency_inventory.py"))["inventory"]


def seed_inventory(root, monkeypatch):
    (root / "console/node_modules/example").mkdir(parents=True)
    (root / "deploy").mkdir()
    (root / "uv.lock").write_text(
        '[[package]]\nname = "awm-adm"\nversion = "0.3.0"\n'
        '[[package]]\nname = "example"\nversion = "1.0"\n'
        'source = { registry = "https://example.org/simple" }\n'
    )
    (root / "console/package-lock.json").write_text(
        json.dumps({"packages": {"node_modules/example": {"version": "1.0", "integrity": "fixture"}}})
    )
    (root / "console/node_modules/example/package.json").write_text(
        json.dumps({"version": "1.0", "license": "MIT", "_where": str(root)})
    )
    (root / "deploy/image-lock.json").write_text('{"images": {"example": "fixture"}}')
    metadata = Message()
    metadata["License-Expression"] = "MIT"
    metadata["License-File"] = "LICENSE"
    metadata["Private-Host-Path"] = str(root)
    dist = SimpleNamespace(version="1.0", metadata=metadata)
    monkeypatch.setattr(importlib.metadata, "distribution", lambda name: dist)
    return dist


def test_inventory_keeps_package_provenance_without_installation_metadata(tmp_path, monkeypatch):
    seed_inventory(tmp_path, monkeypatch)
    result = inventory(tmp_path)
    assert result["python"][0]["license"] == "MIT"
    assert result["python"][0]["license_files"] == ["LICENSE"]
    assert result["python"][0]["source"] == {"registry": "https://example.org/simple"}
    assert result["node"][0]["license"] == "MIT"
    assert result["node"][0]["integrity"] == "fixture"
    assert result["lock_sha256"]["uv.lock"] == hashlib.sha256((tmp_path / "uv.lock").read_bytes()).hexdigest()
    encoded = json.dumps(result)
    assert str(tmp_path) not in encoded
    assert "installed_" not in encoded and '"host"' not in encoded


@pytest.mark.parametrize("language", ["python", "node"])
def test_inventory_rejects_license_metadata_from_a_different_version(tmp_path, monkeypatch, language):
    dist = seed_inventory(tmp_path, monkeypatch)
    if language == "python":
        dist.version = "2.0"
    else:
        (tmp_path / "console/node_modules/example/package.json").write_text(
            '{"version": "2.0", "license": "different-license"}'
        )
    with pytest.raises(ValueError, match="differs from lock"):
        inventory(tmp_path)


def test_missing_distribution_metadata_remains_explicit(tmp_path, monkeypatch):
    seed_inventory(tmp_path, monkeypatch)

    def absent(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "distribution", absent)
    result = inventory(tmp_path)
    assert result["python"][0]["version"] == "1.0"
    assert result["python"][0]["license"] == "metadata unavailable"
    assert result["python"][0]["license_files"] == []


def test_committed_inventory_matches_locks_and_is_portable():
    result = json.loads((ROOT / "docs/dependency-inventory.json").read_text())
    for name, digest in result["lock_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    locked_python = tomllib.loads((ROOT / "uv.lock").read_text())["package"]
    assert {(p["name"], p["version"]) for p in result["python"]} == {
        (p["name"], p["version"]) for p in locked_python if p["name"] != "awm-adm"
    }
    locked_node = json.loads((ROOT / "console/package-lock.json").read_text())["packages"]
    assert {(p["path"], p["version"]) for p in result["node"]} == {
        (path, p["version"]) for path, p in locked_node.items() if path
    }
    assert result["container_images"] == json.loads((ROOT / "deploy/image-lock.json").read_text())["images"]
    assert "host" not in result
    assert all("installed_version" not in p for p in result["python"])
    assert all("installed_on_host" not in p for p in result["node"])


@pytest.mark.parametrize(
    "arguments, message",
    [
        ([], "--override"),
        (["--override", "missing.yaml"], "Compose override must exist"),
        (["--override", "missing.yaml", "--project", "awm-adm"], "dedicated release project"),
        *[
            (["--override", "missing.yaml", "--port", str(port)], "nonproduction port")
            for port in (8080, 8081, 0, 65536)
        ],
    ],
)
def test_rehearsal_invalid_setup_fails_before_credentials_or_output(tmp_path, arguments, message):
    output = tmp_path / "report"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_release_runtime.py"),
            "--package",
            str(tmp_path),
            "--project",
            "awm-adm-check-release-test",
            "--output",
            str(output),
            *arguments,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0 and message in result.stderr
    assert not output.exists()
    assert list(tmp_path.iterdir()) == []
