"""Selected clarification material travels together through ordinary source intake."""

from ..learning.service import fingerprint
from ..sources.bundles import PROFILE, build
from ..teaching.materials import originals, permissions


def enabled(task):
    return (
        task.get("source_context_profile") == PROFILE
        and task.get("previous_task_id")
        and not task.get("source_queue")
    )


def source_id(task, child):
    return "teach_context_" + fingerprint({"task": task["id"], "child": child["id"]}).split(":")[1][:40]


def permission(task, child):
    return {
        "source_id": source_id(task, child),
        "attribution": "Selected Teach material with clarification",
        "evidence_group": task["material_manifest"]["evidence_group"],
        "allow_external": True,
    }


def selected(db, key, task, child):
    # Include linked textual replies, never unselected uploads or unrelated history.
    ids = set(child["material_ids"])
    entries = task["material_manifest"]["entries"]
    ids.update(
        e["id"] for e in entries if e["kind"] == "message" and set(e["input_ids"]) & set(child["input_ids"])
    )
    entries = [e for e in entries if e["id"] in ids]
    bound = {
        **child,
        "material": {**child["material"], "sources": permissions(task["material_manifest"], entries)},
    }
    sources = originals(db, key, task, bound, [e["id"] for e in entries])
    packet = build(sources, source_id(task, child), child["id"])
    return sources, packet
