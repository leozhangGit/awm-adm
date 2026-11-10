import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
violations = runpy.run_path(str(ROOT / "scripts/check_boundaries.py"))["violations"]


def test_owned_source_has_no_parent_imports():
    assert violations(ROOT) == []


def test_import_guard_rejects_parent_imports_path_injection_and_symlinks(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "console").mkdir()
    for path in ("pyproject.toml", "uv.lock", "console/package.json", "console/package-lock.json"):
        (tmp_path / path).write_text("")
    (tmp_path / "src/bad.py").write_text(
        "import adm\nfrom research import x\nimport sys\nsys.path.append('../')\n__import__('examples')\n"
    )
    (tmp_path / "src/linked.py").symlink_to(tmp_path / "src/bad.py")
    errors = violations(tmp_path)
    assert sum("parent-project import" in item for item in errors) == 3
    assert any("import-path manipulation" in item for item in errors)
    assert any("symlink" in item for item in errors)


def test_kernel_guard_rejects_http_framework_and_persistence_dependencies(tmp_path):
    (tmp_path / "src/awm_adm/engine").mkdir(parents=True)
    (tmp_path / "console").mkdir()
    for path in ("pyproject.toml", "uv.lock", "console/package.json", "console/package-lock.json"):
        (tmp_path / path).write_text("")
    (tmp_path / "src/awm_adm/engine/bad.py").write_text("import fastapi\nimport sqlite3\n")
    errors = violations(tmp_path)
    assert any("non-standard-library kernel dependency" in item for item in errors)
    assert any("transport/storage dependency in kernel" in item for item in errors)
