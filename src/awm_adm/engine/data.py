"""Strict JSON input and immutable internal syntax trees."""

import json
import re
from collections.abc import Mapping
from types import MappingProxyType

from .errors import InvalidIR, ResourceLimit

MAX_BYTES = 2_000_000
SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z")
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def shape(value, required, optional=()):
    if not isinstance(value, Mapping):
        raise InvalidIR("Expected an object")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing or extra:
        raise InvalidIR("Unexpected object fields", missing=sorted(missing), extra=sorted(extra))


def name(value, qualified=False):
    pattern = SYMBOL if qualified else NAME
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise InvalidIR("Invalid symbol or variable name", name=value)
    return value


def module_name(value):
    if not isinstance(value, str) or not value:
        raise InvalidIR("Module must be a namespace string")
    for part in value.split("."):
        name(part)
    return value


def freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    return value


def thaw(value):
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(v) for v in value]
    return value


def encode(value):
    return (
        json.dumps(thaw(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def read_json(source, *, encoded=True):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InvalidIR("Duplicate JSON key", key=key)
            result[key] = value
        return result

    def invalid_constant(value):
        raise InvalidIR("Non-JSON numeric constant", value=value)

    if encoded and isinstance(source, (str, bytes)):
        if len(source) > MAX_BYTES:
            raise ResourceLimit("Input exceeds size limit")
        try:
            source = json.loads(source, object_pairs_hook=pairs, parse_constant=invalid_constant)
        except (ValueError, UnicodeError, RecursionError) as error:
            raise InvalidIR("Invalid JSON document") from error
    count = 0

    def visit(value, depth=0):
        nonlocal count
        count += 1
        if count > 20_000 or depth > 64:
            raise ResourceLimit("Input exceeds syntax size or depth limit")
        if isinstance(value, Mapping):
            if any(not isinstance(k, str) for k in value):
                raise InvalidIR("Object keys must be strings")
            for child in value.values():
                visit(child, depth + 1)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child, depth + 1)
        elif type(value) is int:
            if value.bit_length() > 256:
                raise ResourceLimit("Input integer exceeds 256 bits")
        elif value is not None and type(value) not in (str, bool):
            raise InvalidIR("Only JSON objects, arrays, strings, integers, Booleans, and null are supported")

    visit(source)
    if len(encode(source)) > MAX_BYTES:
        raise ResourceLimit("Input exceeds size limit")
    return freeze(source)
