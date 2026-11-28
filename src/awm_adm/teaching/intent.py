"""Portable records of caller intent, separate from generated proposal provenance."""

from copy import deepcopy
from typing import Literal

from pydantic import Field

from ..contracts import ClosedModel
from ..engine.artifacts import digest
from ..engine.data import encode, read_json, thaw

PROFILE = "awm-adm-teaching-intent/1"


class KnowledgeIntent(ClosedModel):
    role: Literal["adopted_rule", "adopted_premise", "observation", "unspecified"]
    basis: str = Field(min_length=1, max_length=2000)


def capture(task, child):
    """Only the coordinator calls this, from its retained task and selected child."""
    return {
        "profile": PROFILE,
        "task_id": task["id"],
        "conversation_id": task["conversation_id"],
        "submitted_at_ms": task["created_at_ms"],
        "authority": task.get("intent_authority", "recorded_teaching_task"),
        "inputs": deepcopy([i for i in task["inputs"] if i["id"] in child["input_ids"]]),
        "prepared_objective": child["objective"],
        "prepared_kind": child["kind"],
        "interpretation_assurance": "not_certified",
        "human_review": "not_established",
        "external_truth": "not_established",
    }


def attach(intent, declarations, retained, sources, support):
    """Bind a coordinator-captured request to exact proposed bodies, never proofs."""
    if not intent:
        return sources, support
    sources = list(sources)
    support = (
        deepcopy(support)
        if support is not None
        else {symbol: [digest(encode(e)) for e in sources] for symbol in declarations}
    )
    for symbol, declaration in declarations.items():
        if symbol in retained:
            continue  # Rechecking a dependent is not a fresh adoption of its meaning.
        note = {
            "artifact_kind": "evidence",
            "evidence_kind": "observation",
            "origin": "awm-adm:teaching-intent",
            "scope": "Record of the caller's teaching request, not external truth, certified interpretation or human review. Publication still requires local admission.",
            "content": {
                **intent,
                "symbol": symbol,
                "definition_digest": digest(encode(declaration)),
                "input_digest": digest(encode(intent["inputs"])),
            },
        }
        sources.append(note)
        support.setdefault(symbol, []).append(digest(encode(note)))
    return sources, support


def retain_support(checked, retained, sources, support):
    """Carry exact accepted evidence when a dependent body is checked again."""
    if not retained:
        return sources, support
    evidence = {digest(encode(e)): e for e in sources}
    support = deepcopy(support)
    for symbol in retained:
        origin = thaw(read_json(checked["blobs"][checked["support"][symbol]]))
        keys = origin["evidence"]
        for key in keys:
            evidence[key] = thaw(read_json(checked["blobs"][key]))
        support[symbol] = list(dict.fromkeys([*support.get(symbol, []), *keys]))
    return list(evidence.values()), support
