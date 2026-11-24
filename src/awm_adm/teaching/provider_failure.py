"""Readable preparation failures from retained local transport diagnostics."""

from ..contracts import ProviderDiagnostics

MESSAGES = {
    "provider_timeout": "Teaching preparation timed out while waiting for a complete provider response.",
    "authentication_failed": "The provider rejected authentication for teaching preparation.",
    "provider_quota_exhausted": "The provider reported insufficient quota for teaching preparation.",
    "rate_limited": "The provider rate-limited teaching preparation.",
    "unsupported_or_invalid_request": "The provider rejected the preparation request or model identifier.",
    "provider_error": "The provider returned an error during teaching preparation.",
    "output_incomplete": "The provider returned incomplete teaching preparation output.",
    "invalid_response": "The provider returned an invalid preparation response.",
    "refusal": "The provider declined the teaching preparation request.",
    "provider_usage_exceeded_reservation": "The provider reported usage beyond the preparation reservation.",
    "authority_changed": "Preparation was not dispatched because its context or connection authority changed.",
    "transport_uncertain": "Teaching preparation ended without a confirmed provider result.",
    "gateway_restarted": "The provider gateway restarted before a preparation result was recorded.",
}

TRANSPORT_MESSAGES = {
    "dns": "Teaching preparation could not resolve the provider's network address.",
    "tls": "Teaching preparation encountered a secure-connection error.",
    "connection": "Teaching preparation encountered a network connection error.",
    "http_protocol": "Teaching preparation encountered an HTTP communication error.",
    "response_too_large": "The provider response exceeded the preparation transport's byte limit.",
    "child_start_failed": "The gateway could not start its provider-call process.",
    "child_exit": "The gateway's provider-call process exited without a complete result.",
    "child_output_too_large": "The gateway's provider-call result exceeded its byte limit.",
    "child_output_invalid": "The gateway's provider-call process returned an invalid result.",
}


def preparation_failure(grant_id, outcome, limits):
    diagnostic = ProviderDiagnostics.model_validate(outcome.get("diagnostics") or {}).model_dump(
        exclude_none=True
    )
    code = outcome.get("error")
    code = code if code in MESSAGES else "provider_call_failed"
    message = TRANSPORT_MESSAGES.get(diagnostic.get("transport_failure")) or MESSAGES.get(
        code, "The teaching preparation call failed."
    )
    if code == "provider_timeout" and diagnostic.get("timeout_ms") is not None:
        message += f" The call's available time was {diagnostic['timeout_ms'] / 1000:g} seconds."
    if code == "output_incomplete" and diagnostic.get("incomplete_reason") == "max_output_tokens":
        message += " The provider reported that the output-token limit was reached."
    if outcome["status"] == "outcome_unknown":
        message += " Provider completion and token usage are unknown."
    message += " No learning started and no new knowledge was accepted. This call was not retried."
    return {
        "stage": "provider",
        "code": code,
        "message": message,
        "grant_id": grant_id,
        "dispatch_status": outcome["status"],
        "configured_timeout_ms": limits["max_duration_ms"],
        "provider_diagnostics": diagnostic,
        "usage": outcome.get("usage"),
        "usage_unresolved": outcome.get("usage") is None and outcome["status"] != "not_dispatched",
        "automatic_retry": False,
    }
