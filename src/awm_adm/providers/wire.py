"""Exact provider wires. Model IDs never select guidance, grammar or checks."""

from ..engine import construction_format, provider_format
from ..engine.artifacts import digest
from ..engine.data import encode
from ..engine.provider_prompt import (
    CONSTRUCTION_INSTRUCTIONS,
    CONSTRUCTION_PROMPT_VERSION,
    INSTRUCTIONS,
    PROMPT_VERSION,
)
from ..engine.provider_wire import ENCODING, encode_wire
from ..runtime.protocol import RuntimeFault

ENDPOINTS = {
    "openai": ("api.openai.com", "/v1/responses"),
    "anthropic": ("api.anthropic.com", "/v1/messages"),
}
ANTHROPIC_VERSION = "2026-10-21"


def specification(context=None, *, construction=True, connection_test=False):
    if connection_test:
        return {
            "instructions": 'Return the JSON object {"ok":true}. This is a bounded connection check.',
            "schema": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
            "context": {},
            "name": "adm_connection_test",
            "prompt_version": "connection-test/1",
        }
    contract = context["task"]["acquisition_contract"]
    return {
        "instructions": CONSTRUCTION_INSTRUCTIONS if construction else INSTRUCTIONS,
        "schema": construction_format.response_schema(contract)
        if construction
        else provider_format.response_schema(contract),
        "context": context,
        "name": "adm_construction_v1" if construction else "adm_candidate_v2",
        "prompt_version": CONSTRUCTION_PROMPT_VERSION if construction else PROMPT_VERSION,
    }


def make_wire(configuration, spec, max_output_tokens):
    required = {"json_schema"} | ({"recursive_refs"} if "$defs" in spec["schema"] else set())
    if not required.issubset(configuration["capabilities"]):
        raise RuntimeFault("unsupported", "Connection lacks the required structured-output capabilities")
    provider, model = configuration["provider"], configuration["model"]
    content = encode(spec["context"]).decode()
    if provider in ("openai", "recorded"):
        body = {
            "model": model,
            "instructions": spec["instructions"],
            "input": [{"role": "user", "content": content}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": spec["name"],
                    "strict": True,
                    "schema": spec["schema"],
                }
            },
            "store": False,
            "stream": False,
            "max_output_tokens": max_output_tokens,
            "service_tier": "default",
        }
    elif provider == "anthropic":
        body = {
            "model": model,
            "system": spec["instructions"],
            "messages": [{"role": "user", "content": content}],
            "output_config": {"format": {"type": "json_schema", "schema": spec["schema"]}},
            "max_tokens": max_output_tokens,
            "stream": False,
        }
    else:
        raise RuntimeFault("unsupported", "Unsupported provider")
    raw = encode_wire(body)
    # UTF-8 wire bytes plus framing/structured-output overhead is a conservative
    # reservation estimate, not a formally verified provider tokenizer bound.
    return raw, len(raw) + 4096


def provenance(spec, raw):
    return {
        "prompt_version": spec["prompt_version"],
        "prompt_hash": digest(spec["instructions"].encode()),
        "schema_hash": digest(encode(spec["schema"])),
        "schema_wire_hash": digest(encode_wire(spec["schema"])),
        "request_encoding": ENCODING,
        "request_hash": digest(raw),
    }
