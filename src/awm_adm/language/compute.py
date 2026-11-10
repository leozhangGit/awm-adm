"""Language checking runs in the existing bounded, network-free compute child."""

from ..contracts import IntentDraft
from ..engine import validate_snapshot
from ..engine.artifacts import digest
from ..engine.data import encode
from ..runtime.protocol import unpack
from ..wire import decode
from .models import Proposal
from .parser import catalog, check_query, parse, validate_vocabulary


def compute(task, budget):
    checked = validate_snapshot(unpack(task["snapshot"]), budget=budget)
    model = checked["model"]
    if (
        model.version != task["context"]["theory_version"]
        or digest(encode(checked["support"])) != task["context"]["support_root"]
    ):
        raise ValueError("Language context does not match the accepted snapshot")
    metadata = validate_vocabulary(model, task["vocabulary"], budget)
    cat = catalog(model, metadata, budget)
    result = {"catalog": cat, "work": budget.used}
    if task["operation"] == "language_ask_catalog":
        from ..conversations.history import snapshot_metadata

        return {
            **result,
            "accepted_fact_projections": snapshot_metadata(checked, budget),
            "work": budget.used,
        }
    if task["operation"] in ("language_catalog", "language_vocabulary"):
        return result
    if task["operation"] == "language_revalidate":
        draft = IntentDraft.model_validate(task["draft"])
        if cat["digest"] != draft.catalog_digest or draft.status != "ready":
            raise ValueError("Interpretation catalog changed")
        check_query(model, draft.query.model_dump(), budget, task["result_ids"])
        return {**result, "work": budget.used, "valid": True}
    utterance = task["utterance"]
    proposal = None
    if task.get("provider_text") is not None:
        proposal = Proposal.model_validate(decode(task["provider_text"].encode()))
        if proposal.status != "ready":
            return {
                **result,
                "parsed": {
                    "status": proposal.status,
                    "query": None,
                    "assumptions": proposal.assumptions,
                    "clarification": proposal.clarification,
                    "choices": [],
                },
            }
        utterance = proposal.command
    parsed = parse(model, cat, utterance, budget, results=task["result_ids"])
    if proposal:
        parsed["assumptions"] = proposal.assumptions
    return {
        **result,
        "parsed": parsed,
        "proposed_command": proposal.command if proposal else None,
        "work": budget.used,
    }
