"""One bounded HTTPS call, fixed official destinations, no retries or redirects."""

import http.client
import ssl
import time

from ..wire import decode
from .diagnostics import account_outcome, response_metadata
from .wire import ANTHROPIC_VERSION, ENDPOINTS

MAX_RESPONSE = 2_097_152
MAX_ERROR_RESPONSE = 16_384


def https(provider, body, credential, timeout):
    host, path = ENDPOINTS[provider]
    connection = http.client.HTTPSConnection(host, timeout=timeout, context=ssl.create_default_context())
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if provider == "openai":
        headers["Authorization"] = "Bearer " + credential
    else:
        headers.update({"x-api-key": credential, "anthropic-version": ANTHROPIC_VERSION})
    end = time.monotonic() + timeout
    try:
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        # Read bounded errors solely to extract allowlisted codes. Never retain
        # arbitrary error bodies, headers or redirects in a dispatch outcome.
        maximum = MAX_RESPONSE if response.status == 200 else MAX_ERROR_RESPONSE
        chunks, size = [], 0
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            if connection.sock:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(65536, maximum + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum:
                if response.status != 200:
                    return response.status, b""
                raise ValueError("Provider response exceeds byte limit")
        return response.status, b"".join(chunks)
    finally:
        connection.close()


def usage(value):
    if not isinstance(value, dict):
        return None
    if any(
        type(value.get(k)) is not int or not 0 <= value[k] < 2**53 for k in ("input_tokens", "output_tokens")
    ):
        return None
    # Include Anthropic cache-read/create tokens when returned; no prompt caching
    # is requested, but reported cost must not be hidden if the provider uses it.
    extra = sum(
        value.get(k, 0)
        for k in ("cache_creation_input_tokens", "cache_read_input_tokens")
        if type(value.get(k, 0)) is int and value.get(k, 0) >= 0
    )
    return {"input_tokens": value["input_tokens"] + extra, "output_tokens": value["output_tokens"]}


def interpret(provider, raw, *, credential=""):
    try:
        if credential and credential.encode() in raw:
            raise ValueError("Credential reflection")
        response = decode(raw)
        from ..engine.diagnostics import capture, redact

        if credential and redact(response, credential) != response:
            raise ValueError("Credential reflection")
        if not isinstance(response, dict):
            raise ValueError
        result = {
            "status": "failed",
            "error": "invalid_response",
            "usage": usage(response.get("usage")),
            "text": None,
        }
        for k in ("id", "model"):
            value = response.get(k)
            if not isinstance(value, str) or not 1 <= len(value) <= 200 or any(ord(c) < 32 for c in value):
                raise ValueError
        result.update(response_id=response["id"], returned_model=response["model"])
        result["diagnostics"] = response_metadata(provider, response)
        texts = []
        if provider == "openai":
            state = response.get("status")
            if state in ("completed", "incomplete", "failed", "cancelled", "queued", "in_progress"):
                result["diagnostics"]["provider_status"] = state
            if response.get("status") == "incomplete":
                details = response.get("incomplete_details")
                reason = details.get("reason") if isinstance(details, dict) else None
                result["diagnostics"]["incomplete_reason"] = (
                    reason if reason in ("max_output_tokens", "content_filter", "steered") else "unknown"
                )
                return account_outcome({**result, "error": "output_incomplete"}, provider)
            if response.get("status") != "completed" or response.get("error") is not None:
                return account_outcome(result, provider)
            for item in response["output"]:
                if item.get("type") == "reasoning":
                    continue  # Never retain hidden reasoning bodies.
                if (
                    item.get("type") != "message"
                    or item.get("role") != "assistant"
                    or item.get("status") != "completed"
                ):
                    raise ValueError
                for part in item["content"]:
                    if part.get("type") == "refusal":
                        return account_outcome({**result, "error": "refusal"}, provider)
                    if part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                        raise ValueError
                    texts.append(part["text"])
        else:
            stop = response.get("stop_reason")
            if stop == "refusal":
                return account_outcome({**result, "error": "refusal"}, provider)
            if stop == "max_tokens":
                result["diagnostics"]["incomplete_reason"] = "max_output_tokens"
                return account_outcome({**result, "error": "output_incomplete"}, provider)
            if stop != "end_turn" or response.get("type") != "message" or response.get("role") != "assistant":
                return account_outcome(result, provider)
            for part in response["content"]:
                if part.get("type") in ("thinking", "redacted_thinking"):
                    continue
                if part.get("type") != "text" or not isinstance(part.get("text"), str):
                    raise ValueError
                texts.append(part["text"])
        if len(texts) != 1 or len(texts[0].encode()) > 262144:
            raise ValueError
        if (
            credential
            and capture(texts[0], secret=credential)["output_digest"] != capture(texts[0])["output_digest"]
        ):
            raise ValueError("Credential reflection")
        # Schema/meaning validation stays at the receiving ADM. No partial JSON salvage.
        return account_outcome({**result, "status": "succeeded", "error": None, "text": texts[0]}, provider)
    except (ValueError, KeyError, TypeError, AttributeError):
        return {"status": "failed", "error": "invalid_response", "usage": None, "text": None}


def http_diagnostics(status, raw):
    diagnostics = {"http_status": status}
    try:
        if len(raw) > MAX_ERROR_RESPONSE:
            return diagnostics
        value = decode(raw)
        error = value.get("error") if isinstance(value, dict) else None
        if isinstance(error, dict):
            code = error.get("code") or error.get("type")
            diagnostics["provider_error_code"] = (
                code
                if code
                in (
                    "insufficient_quota",
                    "rate_limit_exceeded",
                    "invalid_api_key",
                    "model_not_found",
                    "invalid_request_error",
                    "authentication_error",
                    "permission_error",
                    "rate_limit_error",
                    "overloaded_error",
                    "server_error",
                )
                else "unknown"
            )
    except (ValueError, TypeError):
        pass
    return diagnostics


def acquire(configuration, wire, credential, timeout, *, transport=https, recorded_index=0):
    if configuration["provider"] == "recorded":
        replies = configuration.get("recorded_responses", [])
        if not 0 <= recorded_index < len(replies):
            return {
                "status": "failed",
                "error": "recorded_exhausted",
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "text": None,
            }
        from ..engine.provider_wire import encode_wire

        return {
            "status": "succeeded",
            "error": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "text": encode_wire(replies[recorded_index]).decode(),
            "response_id": f"recorded-{recorded_index}",
            "returned_model": configuration["model"],
        }
    try:
        status, raw = transport(configuration["provider"], wire, credential, timeout)
        if status != 200:
            diagnostics = http_diagnostics(status, raw)
            code = (
                "provider_quota_exhausted"
                if status == 429 and diagnostics.get("provider_error_code") == "insufficient_quota"
                else "rate_limited"
                if status == 429
                else "authentication_failed"
                if status in (401, 403)
                else "unsupported_or_invalid_request"
                if status in (400, 404, 422)
                else "provider_error"
            )
            return account_outcome(
                {"status": "failed", "error": code, "usage": None, "text": None, "diagnostics": diagnostics},
                configuration["provider"],
            )
        result = interpret(configuration["provider"], raw, credential=credential)
        result.setdefault("diagnostics", {})["http_status"] = status
        return result
    except Exception:
        # Dispatch may have reached the provider. Do not echo credential-bearing exceptions.
        return {"status": "outcome_unknown", "error": "transport_uncertain", "usage": None, "text": None}
