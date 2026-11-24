"""Service-owned preparation references, separate from accepted source profiles.

The manifest contains metadata only. Original bytes remain in immutable turns or
uploads. Provider selection never manufactures a source identity or trust group.
"""

import hashlib

from ..runtime.protocol import loads
from .diagnostics import PreparationError

PROFILE = "awm-adm-teaching-materials/1"


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def manifest(db, key, task):
    lineage = task.get("material_manifest", {}).get("lineage_id", task["id"])
    source_id = "teach_" + sha(key + ":" + lineage)[:40]
    entries = {}
    for entry in task["inputs"]:
        turn = db.execute("SELECT conversation,body FROM chat_turns WHERE id=?", (entry["id"],)).fetchone()
        if not turn or loads(turn["body"])["text"] != entry["text"]:
            raise PreparationError("materials", "original_mismatch")
        if entry["text"]:
            uid = "text_" + entry["id"]
            entries[uid] = {
                "id": uid,
                "kind": "message",
                "input_ids": [entry["id"]],
                "source_id": source_id,
                "item_id": "turn_" + entry["id"],
                "version_id": "v1",
                "media_type": "text/plain",
                "origin": "conversation:" + turn["conversation"] + "/turn:" + entry["id"],
                "supersedes_version": None,
                "byte_count": len(entry["text"].encode()),
                "content_digest": "sha256:" + sha(entry["text"]),
            }
        for meta in entry.get("attachments", []):
            row = db.execute("SELECT body FROM intake_material WHERE id=?", (meta["id"],)).fetchone()
            if not row or loads(row[0])["metadata"] != meta:
                raise PreparationError("materials", "selected_upload_unavailable")
            saved = loads(row[0])
            uid = "upload_" + meta["id"]
            if uid in entries:
                entries[uid]["input_ids"].append(entry["id"])
                continue
            entries[uid] = {
                "id": uid,
                "kind": "upload",
                "input_ids": [entry["id"]],
                **{k: v for k, v in saved["source"].items() if k != "content"},
                "attachment_id": meta["id"],
                "name": meta["name"],
                "byte_count": meta["byte_count"],
                "content_digest": meta["content_digest"],
            }
    if task.get("source_queue") and not any(e["kind"] == "upload" for e in entries.values()):
        entries["queue_" + lineage] = {
            "id": "queue_" + lineage,
            "kind": "queue",
            "source_id": source_id,
            "input_ids": [i["id"] for i in task["inputs"]],
        }
    return {
        "profile": PROFILE,
        "lineage_id": lineage,
        "entries": list(entries.values()),
        "evidence_group": "supplied_" + sha(key)[:40],
    }


def select(manifest, ids, input_ids):
    if not manifest or manifest.get("profile") != PROFILE:
        raise PreparationError("materials", "manifest_required")
    available = {e["id"]: e for e in manifest["entries"]}
    if not ids or len(ids) != len(set(ids)):
        raise PreparationError("materials", "duplicate_or_empty_selection")
    if any(uid not in available for uid in ids):
        raise PreparationError("materials", "unknown_material_reference")
    selected = [available[uid] for uid in ids]
    if any(not set(e["input_ids"]) & set(input_ids) for e in selected):
        raise PreparationError("materials", "unlinked_material_reference")
    return selected


def permissions(manifest, selected):
    # Supplied items are not independently authenticated sources. Preserve one
    # conservative group across lineages; existing owner policy remains authoritative.
    return [
        {
            "source_id": source,
            "attribution": "Supplied Teach material",
            "evidence_group": manifest["evidence_group"],
            "allow_external": False,
        }
        for source in dict.fromkeys(e["source_id"] for e in selected)
    ]


def bind_plan(value, manifest):
    """Map wire references to the existing closed local plan; retain selection separately."""
    bindings = []
    for child in value["children"]:
        material = child["material"]
        ids = material.pop("material_ids") if material else []
        bindings.append(ids)
        if material:
            selected = select(manifest, ids, child["input_ids"])
            material["sources"] = permissions(manifest, selected)
    return bindings


def originals(db, key, task, child, ids):
    saved = task["material_manifest"]
    if manifest(db, key, task) != saved:
        raise PreparationError("materials", "manifest_mismatch")
    selected = select(saved, ids, child["input_ids"])
    if child["material"]["sources"] != permissions(saved, selected):
        raise PreparationError("materials", "permission_mismatch")
    inputs = {i["id"]: i for i in task["inputs"]}
    sources = []
    for entry in selected:
        if entry["kind"] == "queue":
            continue
        if entry["kind"] == "upload":
            row = db.execute(
                "SELECT body FROM intake_material WHERE id=?", (entry["attachment_id"],)
            ).fetchone()
            source = loads(row[0])["source"]
        else:
            source = {
                k: entry[k]
                for k in ("source_id", "item_id", "version_id", "media_type", "origin", "supersedes_version")
            }
            source["content"] = inputs[entry["input_ids"][0]]["text"]
        if (
            "sha256:" + sha(source["content"]) != entry["content_digest"]
            or len(source["content"].encode()) != entry["byte_count"]
        ):
            raise PreparationError("materials", "original_digest_mismatch")
        sources.append(source)
    return sources
