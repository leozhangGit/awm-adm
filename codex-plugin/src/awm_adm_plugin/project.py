"""Explicit project context; never infer from server cwd."""

import sys
from pathlib import Path


def project_context(project_root: str | None, workspace_roots: list[str] | None) -> dict:
    """Resolve explicit host context; never infer a project from process cwd."""
    if project_root is None and workspace_roots:
        if len(workspace_roots) != 1:
            return {"state": "choose_project", "summary": "Select the project to use with AWM-ADM."}
        project_root = workspace_roots[0]
    if project_root is None:
        return {"state": "no_project", "summary": "Use AWM-ADM inside a project or select a project folder."}
    path = Path(project_root)
    if not path.is_absolute():
        return {"state": "invalid_project", "summary": "The selected project must have an absolute path."}
    try:
        path = path.resolve(strict=True)
        valid = path.is_dir()
    except (OSError, RuntimeError, ValueError):
        valid = False
    if not valid:
        return {"state": "invalid_project", "summary": "The selected project folder is unavailable."}
    # A plugin cache/source directory is not evidence of a selected user project.
    # launch.py selects this package's .venv; works for editable and wheel installs.
    package = Path(sys.prefix).resolve().parent
    if path == package or package in path.parents:
        return {"state": "invalid_project", "summary": "Select your project, not the plugin installation."}
    return {
        "state": "project_selected",
        "summary": "Project selected.",
        "project_root": str(path),
        "project_name": path.name,
        "context_source": "explicit_host_argument",
    }
