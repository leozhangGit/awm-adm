"""Public documentation and packaging checks report locations without leaking secrets."""

import json
import subprocess
import sys
from pathlib import Path

CHECKER = Path(__file__).parents[1] / "scripts/check_public_release.py"


def check(root):
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, json.loads(result.stdout)


def seed(root):
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md", "SECURITY.md"):
        (root / name).write_text("Public fixture\n")


def test_links_must_resolve_inside_the_public_tree(tmp_path):
    seed(tmp_path)
    (tmp_path / "README.md").write_text("[License](LICENSE)\n[External](https://example.org)\n")
    assert check(tmp_path) == (0, {"status": "passed", "failures": []})
    (tmp_path / "README.md").write_text("[Missing](absent.md)\n[Parent](../private.md)\n")
    code, report = check(tmp_path)
    assert code == 1
    assert any("missing documentation target" in item for item in report["failures"])
    assert any("escapes repository" in item for item in report["failures"])


def test_private_stores_are_not_scanned_but_embedded_credentials_fail_without_echo(tmp_path):
    seed(tmp_path)
    secret = "sk-" + "x" * 48
    (tmp_path / ".local").mkdir()
    (tmp_path / ".local/account.md").write_text(secret)
    assert check(tmp_path)[0] == 0
    (tmp_path / "README.md").write_text(secret)
    code, report = check(tmp_path)
    assert code == 1
    assert "credential" in str(report)
    assert secret not in str(report)


def test_archival_documents_and_source_symlinks_are_rejected(tmp_path):
    seed(tmp_path)
    (tmp_path / "verification").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src/escape.py").symlink_to(tmp_path / "README.md")
    code, report = check(tmp_path)
    assert code == 1
    assert any("development history" in item for item in report["failures"])
    assert any("source symlink" in item for item in report["failures"])
