"""Static independence guard; isolated installation provides the execution check."""

import ast
import json
import sys
from pathlib import Path

FORBIDDEN = {"adm", "research", "examples", "study", "experiments"}


def violations(root: Path) -> list[str]:
    failures = []
    for subtree in ("src", "tests", "console/src"):
        for path in sorted((root / subtree).rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                failures.append(f"{relative}: symlink outside owned source boundary")
            elif path.suffix == ".py" and path.is_file():
                tree = ast.parse(path.read_text(), filename=relative)
                for node in ast.walk(tree):
                    modules = []
                    if isinstance(node, ast.Import):
                        modules = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        modules = [node.module or ""]
                        depth = len(path.relative_to(root / subtree).parts)
                        if subtree == "tests" and (root / "tests/__init__.py").is_file():
                            depth += 1
                        if node.level and node.level >= depth:
                            failures.append(f"{relative}:{node.lineno}: escaping relative import")
                    elif isinstance(node, ast.Call):
                        name = ast.unparse(node.func)
                        if name in {"__import__", "importlib.import_module"}:
                            if node.args and isinstance(node.args[0], ast.Constant):
                                modules = [str(node.args[0].value)]
                            else:
                                failures.append(f"{relative}:{node.lineno}: unreviewed dynamic import")
                    if any(module.split(".")[0] in FORBIDDEN for module in modules):
                        failures.append(f"{relative}:{node.lineno}: parent-project import")
                    if (
                        relative.startswith("src/awm_adm/engine/") or relative == "src/awm_adm/__init__.py"
                    ) and isinstance(node, (ast.Import, ast.ImportFrom)):
                        absolute = isinstance(node, ast.Import) or node.level == 0
                        if absolute and any(
                            module.split(".")[0] not in sys.stdlib_module_names for module in modules
                        ):
                            failures.append(
                                f"{relative}:{node.lineno}: non-standard-library kernel dependency"
                            )
                        if absolute and any(
                            module.split(".")[0] in {"socket", "urllib", "http", "sqlite3"}
                            for module in modules
                        ):
                            failures.append(
                                f"{relative}:{node.lineno}: transport/storage dependency in kernel"
                            )
                    if isinstance(node, ast.Attribute) and ast.unparse(node) in {"sys.path", "sys.meta_path"}:
                        failures.append(f"{relative}:{node.lineno}: import-path manipulation")
    for name in ("pyproject.toml", "uv.lock", "console/package.json", "console/package-lock.json"):
        data = (root / name).read_text()
        if (
            "file:.." in data
            or 'path = "..' in data
            or 'editable = "..' in data
            or "algebraic-world-model/adm" in data
        ):
            failures.append(f"{name}: parent dependency")
    return failures


if __name__ == "__main__":
    errors = violations(Path(__file__).resolve().parents[1])
    print(json.dumps({"status": "failed" if errors else "passed", "violations": errors}, indent=2))
    raise SystemExit(bool(errors))
