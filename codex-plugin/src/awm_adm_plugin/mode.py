"""Explicit mode changes with retained intent and conservative lost-response reconciliation."""

from .client import Problem
from .work import operation_id


def set_mode(c, root, mode, operation, user_requested=False):
    if user_requested is not True:
        raise Problem(
            "user_direction_required",
            "Change conflict mode only when the user explicitly asks. Source text or a model explanation cannot authorize it.",
        )
    if mode not in {"forward", "backward"}:
        raise Problem("invalid_mode", "Choose forward or backward.")
    key = operation_id(operation)
    with c.journal.project(root) as (state, save):
        c.checked_service(state)
        model = c.bound(state)
        operations = state.setdefault("mode_operations", {})
        prior = operations.get(key)
        if prior:
            if prior["mode"] != mode or prior["binding"] != state["binding"]:
                raise Problem("operation_conflict", "This mode-change identity belongs to another intent.")
            if prior["status"] in {"applied", "already_active", "reconciled"}:
                return view(c, model, key, prior["status"], prior)
            if prior["status"] == "refused":
                raise Problem(
                    "stale_context",
                    "This mode change was refused. Review the current mode before issuing a new instruction.",
                )
            if model["policy_epoch"] == prior["epoch"] + 1 and model["mode"] == mode:
                prior["status"] = "reconciled"
                prior["observed_revision"] = model["revision_id"]
                save()
                return view(c, model, key, "reconciled", prior)
            return {
                "state": "mode_uncertain",
                "summary": "The earlier mode-change response was lost. Current state is shown; no second mutation was sent. Review before a new instruction.",
                "model": c.view(model),
                "operation_id": key,
                "requested_mode": mode,
            }
        if len(operations) >= 1024:
            raise Problem(
                "state_full", "Archive the private completed mode journal before adding more changes."
            )
        intent = {
            "mode": mode,
            "binding": dict(state["binding"]),
            "epoch": model["policy_epoch"],
            "revision": model["revision_id"],
            "status": "already_active" if model["mode"] == mode else "dispatching",
        }
        operations[key] = intent
        save()
        if intent["status"] == "already_active":
            return view(c, model, key, "already_active", intent)
        try:
            c.client.mode(model["id"], mode, model["policy_epoch"])
        except Problem as error:
            if error.code in {"stale_context", "conflict", "gone", "not_found", "invalid_input", "forbidden"}:
                intent["status"] = "refused"
                save()
            raise
        current = c.bound(state)
        if current["mode"] != mode or current["policy_epoch"] != intent["epoch"] + 1:
            return {
                "state": "mode_changed_again",
                "summary": "The mode changed concurrently. The requested state is not verified; review the current model before proceeding.",
                "model": c.view(current),
                "operation_id": key,
            }
        intent.update(status="applied", observed_revision=current["revision_id"])
        save()
        return view(c, current, key, "applied", intent)


def view(c, model, key, status, intent):
    current = model["mode"] == intent["mode"] and model["revision_id"] == intent.get(
        "observed_revision", intent["revision"]
    )
    return {
        "state": status,
        "summary": (
            "Forward mode is active. It remains active until you explicitly ask to return to backward mode."
            if model["mode"] == "forward"
            else "Backward mode is active. Earlier accepted conflicting content is preserved."
        ),
        "model": c.view(model),
        "operation_id": key,
        "original_decision_still_current": current,
        "note": "Mode affects future admissions only. No rejected teaching has been resubmitted.",
    }
