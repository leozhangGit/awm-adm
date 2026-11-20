"""Installation exports must not carry working-store credentials, caches or escaping links."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "release_export", Path(__file__).parents[1] / "scripts/export_release.py"
)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def test_export_is_self_contained_and_verification_detects_change(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nversion = "0.2.0.dev10"\n')
    for path in [
        "src/code.py",
        ".local/secrets/owner-token",
        ".cache/wheel",
        "console/node_modules/module.js",
        "config/.env",
        "src/state.db",
        "src/state.db-journal",
        "src/state.sqlite-journal",
        "src/state.sqlite3-journal",
        "src/.codex/config.toml",
        "config/.npmrc",
        "config/.git-credentials",
        "config/.netrc",
        "config/.mcp.json",
        "config/secrets/value",
        "config/credentials/value",
        "config/provider-secrets/value",
        "config/admin-credentials/value",
        "config/backups/archive.zip",
        "config/id_ed25519",
        "config/id_rsa",
        "config/client.p12",
        "config/client.pfx",
        "config/client.jks",
        "config/owner-token",
        "config/gateway-master-key",
        "config/openai-key",
        "config/anthropic-key",
        "config/credentials.json",
        "config/service-account-private.json",
        "unknown-secret.txt",
    ]:
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("authored test content")
    target = tmp_path / "export"
    result = exporter.export(root, target)
    assert set(result["files"]) == {"pyproject.toml", "src/code.py"}
    assert exporter.verify(target) == result
    with pytest.raises(ValueError, match="must be new"):
        exporter.export(root, target)
    (target / "src/code.py").write_text("changed")
    with pytest.raises(ValueError, match="differs"):
        exporter.verify(target)


def test_public_npm_build_configuration_is_retained(tmp_path):
    root = tmp_path / "source"
    (root / "console").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nversion = "0.3.0"\n')
    (root / "console/.npmrc").write_text("engine-strict=true\n")
    result = exporter.export(root, tmp_path / "export")
    assert set(result["files"]) == {"pyproject.toml", "console/.npmrc"}


def test_plugin_source_is_public_but_runtime_and_private_state_are_not(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nversion = "0.3.0"\n')
    public = {"plugin.json", "mcp.json", "uv.lock", "src/connector.py", "skills/project/SKILL.md"}
    private = {".venv/bin/python", ".local/bindings.json", ".cache/package", ".codex/config.toml"}
    for relative in public | private:
        path = root / "codex-plugin" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Synthetic packaging fixture")
    result = exporter.export(root, tmp_path / "export")
    assert set(result["files"]) == {"pyproject.toml"} | {"codex-plugin/" + p for p in public}


def test_export_rejects_symlinks_and_recursive_destination_without_partial_package(tmp_path):
    root = tmp_path / "source"
    (root / "src").mkdir(parents=True)
    (root / "src/escape").symlink_to(tmp_path)
    target = tmp_path / "export"
    with pytest.raises(ValueError, match="symlink"):
        exporter.export(root, target)
    assert not target.exists()
    with pytest.raises(ValueError, match="inside"):
        exporter.export(root, root / "src/export")


def test_release_designation_is_explicit_and_unknown_status_fails(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    metadata = root / "pyproject.toml"
    metadata.write_text('[project]\nversion = "0.2.0"\n')
    candidate = exporter.export(root, tmp_path / "candidate")
    assert candidate["release_status"] == "candidate_pending_joint_acceptance"
    metadata.write_text(
        '[project]\nversion = "0.2.0"\n[tool.awm-adm.release]\nstatus = "local_technical_release"\n'
    )
    released = exporter.export(root, tmp_path / "released")
    assert released["release_status"] == "local_technical_release"
    assert exporter.verify(tmp_path / "released") == released
    metadata.write_text('[project]\nversion = "0.2.0"\n[tool.awm-adm.release]\nstatus = "unknown"\n')
    with pytest.raises(ValueError, match="Unknown source release status"):
        exporter.export(root, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_public_export_includes_contracts_and_license_but_not_development_history(tmp_path):
    root = tmp_path / "source"
    (root / "contracts/workflows").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nversion = "0.3.0"\n')
    for name in (
        "V3_PLAN.md",
        "V2_IMPLEMENTATION_PLAN.md",
        "LICENSE",
        "CONTRIBUTING.md",
        "contracts/workflows/defaults.json",
        "verification/private-report.md",
        "docs/private.token",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Authored packaging fixture\n")
    result = exporter.export(root, tmp_path / "export")
    assert {"LICENSE", "CONTRIBUTING.md", "contracts/workflows/defaults.json"} <= set(result["files"])
    assert not {
        "V3_PLAN.md",
        "V2_IMPLEMENTATION_PLAN.md",
        "verification/private-report.md",
        "docs/private.token",
    } & set(result["files"])
    assert exporter.verify(tmp_path / "export") == result
