"""Validation and normalization of the local request protocol."""

from collections.abc import Mapping

from .data import module_name, name, read_json, shape, thaw
from .errors import InvalidIR, UnsupportedFeature

LIMITS = {
    "max_work": (None, 100_000_000),
    "max_duration_ms": (None, 3_600_000),
    "max_states": (10_000, 1_000_000),
    "max_search_bytes": (16_000_000, 256_000_000),
}


def identifier(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise InvalidIR("Identifiers must contain between 1 and 200 characters")
    return value


def validate_request(source):
    request = thaw(read_json(source))
    shape(request, ("protocol", "kind", "idempotency_key", "profile", "query", "limits", "on_gap"))
    if request["protocol"] != "adm/0.1" or request["kind"] != "request":
        raise InvalidIR("Unsupported request envelope")
    if request["profile"] != "finite-v0":
        raise UnsupportedFeature("Unsupported request profile", profile=request["profile"])
    identifier(request["idempotency_key"])
    if request["on_gap"] not in ("learn", "report"):
        raise InvalidIR("on_gap must be learn or report")
    limits = request["limits"]
    shape(limits, ("max_work", "max_duration_ms"), ("max_states", "max_search_bytes"))
    for key, (default, maximum) in LIMITS.items():
        value = limits.setdefault(key, default)
        if type(value) is not int or not 1 <= value <= maximum:
            raise InvalidIR("Invalid request limit", limit=key, maximum=maximum)
    query = request["query"]
    if not isinstance(query, Mapping):
        raise InvalidIR("query must be an object")
    op = query.get("op")
    if op == "capabilities":
        shape(query, ("op",))
    elif op in ("evaluate", "check_claim"):
        key = "expression" if op == "evaluate" else "proposition"
        shape(query, ("op", "module", key))
        module_name(query["module"])
        if not isinstance(query[key], Mapping):
            raise InvalidIR("Expression or proposition must be an object")
    elif op == "find_plan":
        shape(query, ("op", "module", "initial_state", "goal"), ("max_depth", "transitions"))
        module_name(query["module"])
        name(query["goal"], qualified=True)
        if "max_depth" in query and (type(query["max_depth"]) is not int or query["max_depth"] < 0):
            raise InvalidIR("max_depth must be a nonnegative integer")
        if "transitions" in query:
            if not isinstance(query["transitions"], list):
                raise InvalidIR("transitions must be an array")
            for symbol in query["transitions"]:
                name(symbol, qualified=True)
            if len(query["transitions"]) != len(set(query["transitions"])):
                raise InvalidIR("Duplicate selected transition")
    elif op == "check_certificate":
        shape(query, ("op", "certificate", "backend"))
        if not isinstance(query["certificate"], Mapping):
            raise InvalidIR("certificate must be a data object")
        if query["backend"] not in ("finite", "lean"):
            raise UnsupportedFeature("Unsupported certificate backend")
    elif op == "explain":
        shape(query, ("op", "result_id"))
        identifier(query["result_id"])
    else:
        raise UnsupportedFeature("Unsupported request operation", operation=op)
    return request
