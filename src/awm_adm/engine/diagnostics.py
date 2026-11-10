"""Bounded untrusted final-output excerpts; never HTTP envelopes or reasoning."""

import json

from .artifacts import digest
from .data import encode, read_json, thaw
from .errors import ADMError

OUTPUT_LIMIT = 16384


def redact(value, secret=None):
    if isinstance(value, str):
        if secret:
            for form in (secret, json.dumps(secret)[1:-1]):
                value = value.replace(form, "[redacted]")
        return value
    if isinstance(value, dict):
        return {redact(k, secret): redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secret) for v in value]
    return value


def capture(text, *, secret=None, limit=OUTPUT_LIMIT, semantic=False):
    # Decode a complete JSON text for redaction only; never salvage partial IR.
    # This also catches a credential represented with JSON Unicode escapes.
    if secret:
        try:
            parsed = json.loads(text)
            cleaned = redact(parsed, secret)
            if cleaned != parsed:
                text = json.dumps(cleaned, ensure_ascii=True)
        except (ValueError, RecursionError):
            pass
    data = redact(text, secret).encode("utf-8")
    result = {
        "output_digest": digest(data),
        "output_bytes": len(data),
        "output_excerpt": data[:limit].decode("utf-8", errors="ignore"),
        "truncated": len(data) > limit,
        "trust": "unaccepted_provider_output",
    }
    if semantic:
        try:
            # Only diagnostic equality, never executable recovery or admission.
            value = thaw(read_json(data))
            content = value.get("result", value) if isinstance(value, dict) else None
            if isinstance(content, dict):
                content.pop("summary", None)
                if isinstance(content.get("declarations"), list):
                    content["declarations"].sort(key=encode)
                if isinstance(content.get("retractions"), list):
                    content["retractions"].sort(key=encode)
                result["content_digest"] = digest(encode(value))
        except ADMError:
            pass
    return result


def bounded(value, limit=OUTPUT_LIMIT):
    data = encode(value)
    return value if len(data) <= limit else {"omitted": True, "digest": digest(data), "bytes": len(data)}
