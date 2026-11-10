"""Bounded JSON decoding for public/configuration documents, not finite IR encoding."""

import json
import math

MAX_DOCUMENT_BYTES = 2_097_152
MAX_DEPTH = 32
MAX_NODES = 100_000


def check_tree(value):
    stack = [(value, 0)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if depth > MAX_DEPTH or count > MAX_NODES:
            raise ValueError("Document exceeds structural limits")
        if isinstance(node, dict):
            if not all(isinstance(key, str) for key in node):
                raise ValueError("JSON object keys must be strings")
            stack.extend((v, depth + 1) for v in node.values())
        elif isinstance(node, list):
            stack.extend((v, depth + 1) for v in node)
        elif type(node) is float:
            if not math.isfinite(node):
                raise ValueError("Nonfinite number")
        elif node is not None and type(node) not in (str, int, bool):
            raise ValueError("Unsupported JSON value")
    return value


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def _constant(_value):
    raise ValueError("Nonfinite number")


def decode(raw: bytes):
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("Document exceeds byte limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid UTF-8 JSON document") from exc
    return check_tree(value)


def canonical(value) -> bytes:
    """Transport/configuration identity only; never substitute for finite-v0 encoding."""
    check_tree(value)
    result = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    if len(result) > MAX_DOCUMENT_BYTES:
        raise ValueError("Document exceeds byte limit")
    return result
