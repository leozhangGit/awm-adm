"""Bounded adapters around the owned acquisition and admission core."""

import base64

from ..engine import (
    Instance,
    build_candidate,
    construction,
    construction_format,
    provider_format,
    validate_snapshot,
)
from ..engine.acquisition import check_proposal, validate_contract
from ..engine.candidates import CandidatePackage
from ..engine.data import thaw
from ..engine.diagnostics import bounded, capture
from ..engine.errors import ADMError
from ..providers.wire import make_wire, provenance, specification
from ..runtime.protocol import pack, unpack


def package(value):
    return CandidatePackage(
        base64.b64decode(value["envelope"], validate=True),
        {k: base64.b64decode(v, validate=True) for k, v in value["attachments"].items()},
    )


def transport(value):
    return {
        "envelope": base64.b64encode(value.envelope).decode(),
        "attachments": {k: base64.b64encode(v).decode() for k, v in value.attachments.items()},
    }


def compute(task, budget):
    operation = task["operation"]
    checked = validate_snapshot(unpack(task["snapshot"]), budget=budget)
    base = checked["model"]
    body = task["body"]
    contract = validate_contract(body["task"]["acquisition_contract"])
    draft = task.get("draft") or (construction.seed(contract) if body["construction"] else None)
    if operation in ("learning_prepare", "learning_admit") and body["publication"] == "checked_auto":
        owner = (
            checked["conformance"]
            if operation == "learning_prepare"
            else validate_snapshot(unpack(task["current_snapshot"]), budget=budget)["conformance"]
        )
        if not owner.get("contracts") and not owner.get("invariants"):
            from ..engine.errors import Rejected

            raise Rejected("Automatic publication requires nonempty independent owner requirements")
    if operation == "learning_prepare":
        context = {
            "task": {**body["task"], "acquisition_contract": contract},
            "accepted_theory": base.version,
            "feedback": task.get("feedback", []),
        }
        if body["disclose_model"]:
            context["model"] = base.document()
        if draft:
            context["construction"] = construction.view(draft, contract)
        spec = specification(context, construction=body["construction"])
        raw, estimate = make_wire(task["connection"], spec, body["call_limits"]["max_output_tokens"])
        return {
            "wire": base64.b64encode(raw).decode(),
            "input_estimate": estimate,
            "provenance": provenance(spec, raw),
            "draft": draft,
            "work": budget.used,
        }
    if operation == "learning_decode":
        output = task["outcome"]["text"]
        diagnostic = capture(output, semantic=True)
        try:
            value = (
                construction_format.decode_update(output.encode(), budget, contract)
                if body["construction"]
                else provider_format.decode_proposal(output.encode(), budget, contract)
            )
            if value.get("status") == "needs_evidence":
                return {"status": "needs_evidence", "diagnostic": diagnostic, "work": budget.used}
            evidence = {
                "artifact_kind": "evidence",
                "evidence_kind": "provider_statement",
                "origin": "awm-adm:acquisition",
                "scope": "Untrusted proposal; checked locally before publication. No external truth claim.",
                "content": {"provenance": task["provenance"], "summary": value.get("summary", "Acquisition")},
            }
            if body["construction"]:
                draft = construction.merge(
                    draft, {"draft": value["draft"], "evidence": [evidence]}, contract, budget
                )
                construction.complete(draft, contract, base, budget)
                declarations, retractions = draft["declarations"], draft["retractions"]
                sources, support = list(draft["evidence"].values()), draft["support"]
            else:
                declarations = {entry["symbol"]: entry["body"] for entry in value["declarations"]}
                if len(declarations) != len(value["declarations"]):
                    from ..engine.errors import InvalidIR

                    raise InvalidIR("Duplicate declaration symbol")
                retractions = value["retractions"]
                check_proposal(declarations, retractions, contract, budget)
                sources, support = [evidence], None
            candidate = build_candidate(
                base,
                declarations,
                candidate_id=task["candidate_id"],
                evidence=sources,
                retractions=retractions,
                evidence_by_symbol=support,
            )
            return {
                "status": "complete",
                "package": transport(candidate),
                "preview": {"declarations": declarations, "retractions": retractions},
                "draft": draft,
                "diagnostic": diagnostic,
                "work": budget.used,
            }
        except ADMError as error:
            return {
                "status": "partial" if error.code == "draft_incomplete" else "invalid",
                "draft": draft,
                "diagnostic": {**diagnostic, "error": bounded(error.as_dict())},
                "work": budget.used,
            }
    if operation == "learning_admit":
        current = validate_snapshot(unpack(task["current_snapshot"]), budget=budget)
        context = task["context"]
        instance = Instance(
            current["model"].document(), mode=context["mode"], policy=current["conformance"], budget=budget
        )
        # Restore an owned revision, not a new snapshot-derived instance. Historical
        # origins and lineage remain immutable; only the new receipt gains support.
        instance._instance_id = context["instance_id"]
        instance._epoch = context["policy_epoch"]
        instance._sequence = task["receipt_sequence"] - 1
        instance._blobs = dict(current["blobs"])
        instance._support = dict(current["support"])
        instance._lineage = thaw(current["lineage"])
        instance._models[base.version] = base
        instance.receive(package(task["package"]), review_required=False)
        decision = instance.decide_next(budget=budget)
        result = {
            "status": decision["status"],
            "decision": bounded(decision["decision"]),
            "work": budget.used,
        }
        if decision["status"] == "accepted":
            result.update(
                snapshot=pack(instance.export_snapshot(budget=budget)),
                context=instance.info(),
                work=budget.used,
            )
        return result
    raise ValueError("Unknown learning computation")
