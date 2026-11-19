"""Read-only connection readiness; historical records never grant new authority."""

from ..runtime.protocol import RuntimeFault


def issue(code, message, action="connections"):
    return {"code": code, "message": message, "action": action}


def conversation(service, record):
    prefs = record.get("preferences") or {}
    if not prefs.get("direct"):
        return [
            issue(
                "historical_exchange",
                "This is saved history. Continue with a new Ask or Teach message.",
                "message",
            )
        ]
    try:
        service.runtime.interactions.connection_for(
            {"preferences": prefs},
            "ask_interpretation" if prefs["purpose"] == "ask" else "task_preparation",
        )
        return []
    except RuntimeFault as error:
        return [issue(error.code, str(error))]
