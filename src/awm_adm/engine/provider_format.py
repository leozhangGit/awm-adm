"""Schema-constrained acquisition syntax and bounded translation to finite-v0.

This is a wire format, not a new executable language. The schema and local
decoder share one grammar. Translation only restores named maps and removes
explicitly absent optional fields; admission still establishes semantics.
"""

import re
from copy import deepcopy

from .acquisition import check_size, validate_contract
from .data import read_json, thaw
from .errors import InvalidIR

FORMAT = "adm-finite-proposal/2"


def _object(**properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _ref(key):
    return {"$ref": "#/$defs/" + key}


def _enum(*values):
    return {"type": "string", "enum": list(values)}


def _array(items, **limits):
    return {"type": "array", "items": items, **limits}


def _grammar():
    string, integer = {"type": "string"}, {"type": "integer"}
    name = {"type": "string", "pattern": r"[A-Za-z_][A-Za-z0-9_]*"}
    symbol = {"type": "string", "pattern": r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+"}
    # JSON Schema patterns match substrings unless explicitly anchored.
    name["pattern"] = "^" + name["pattern"] + "$"
    symbol["pattern"] = "^" + symbol["pattern"] + "$"
    t, e = _ref("type"), _ref("expression")
    definitions = {
        "type_fields": _array(_ref("named_type"), maxItems=64),
        "parameters": _array(_ref("named_type")),
        "expression_fields": _array(_ref("named_expression")),
        "cases": _array(_ref("named_case")),
        "value_fields": _array(_ref("named_value")),
        "named_type": _object(name=name, value=t),
        "named_expression": _object(name=name, value=e),
        "named_case": _object(name=name, value=_ref("case")),
        "named_value": _object(name=string, value=_ref("value")),
        "case": _object(bind=name, body=e),
        "nullable_type": {"anyOf": [t, {"type": "null"}]},
        "nullable_expression": {"anyOf": [e, {"type": "null"}]},
        # Objects inside literal data have a wrapper, so arbitrary keys never
        # become schema properties. Arrays and scalar values stay native JSON.
        "object_value": _object(fields=_ref("value_fields")),
        "value": {
            "anyOf": [
                {"type": "boolean"},
                integer,
                string,
                {"type": "null"},
                _array(_ref("value")),
                _ref("object_value"),
            ]
        },
        "literal": _object(op=_enum("literal"), value=_ref("value"), type=_ref("nullable_type")),
        "transition": _object(
            kind=_enum("transition"), state=t, parameters=t, legal=e, next=e, cost=_ref("nullable_expression")
        ),
    }
    definitions["type"] = {
        "anyOf": [
            _object(ref=symbol),
            _object(kind=_enum("bool")),
            _object(kind=_enum("int"), min=integer, max=integer),
            _object(kind=_enum("enum"), values=_array(string, maxItems=64)),
            _object(kind=_enum("record"), fields=_ref("type_fields")),
            _object(kind=_enum("sum"), variants=_ref("type_fields")),
            _object(kind=_enum("vector"), element=t, length={"type": "integer", "minimum": 0, "maximum": 32}),
            _object(kind=_enum("refined"), base=t, where=e),
        ]
    }
    definitions["expression"] = {
        "anyOf": [
            _ref("literal"),
            _object(op=_enum("var"), name=name),
            _object(op=_enum("get"), record=e, field=name),
            _object(op=_enum("record"), fields=_ref("expression_fields")),
            _object(op=_enum("update"), record=e, fields=_ref("expression_fields")),
            _object(**{"op": _enum("if"), "condition": e, "then": e, "else": e}),
            _object(op=_enum("tag"), type=t, tag=name, value=e),
            _object(op=_enum("match"), value=e, cases=_ref("cases")),
            _object(op=_enum("vector"), type=t, items=_array(e, maxItems=32)),
            _object(op=_enum("index"), vector=e, index=e),
            _object(op=_enum("forall", "exists"), var=name, type=t, body=e),
            _object(op=_enum("call"), function=symbol, args=_ref("expression_fields")),
            _object(op=_enum("not"), args=_array(e, minItems=1, maxItems=1)),
            _object(op=_enum("and", "or"), args=_array(e)),
            _object(
                op=_enum("eq", "ne", "lt", "le", "gt", "ge", "add", "sub", "mul", "min", "max"),
                args=_array(e, minItems=2, maxItems=2),
            ),
        ]
    }
    presentations = []
    for construction, type_fields, map_fields in (
        ("product", ("left", "right"), ("project_left", "project_right")),
        ("coproduct", ("left", "right"), ("inject_left", "inject_right")),
        ("pullback", ("left", "right", "base"), ("left_map", "right_map", "project_left", "project_right")),
        ("equalizer", ("source", "target"), ("first", "second", "include")),
    ):
        presentations.append(
            _object(
                kind=_enum("presentation"),
                construction=_enum(construction),
                carrier=t,
                **{key: t for key in type_fields},
                **{key: symbol for key in map_fields},
            )
        )
    definitions["declaration"] = {
        "anyOf": [
            _object(kind=_enum("type"), type=t),
            _object(kind=_enum("function"), params=_ref("parameters"), returns=t, body=e),
            _ref("transition"),
            _object(kind=_enum("goal"), state=t, body=e),
            _object(kind=_enum("assertion"), params=_ref("parameters"), body=e),
            *presentations,
        ]
    }
    return {
        **_object(
            format=_enum(FORMAT),
            status=_enum("candidate", "needs_evidence"),
            declarations=_array(_object(symbol=symbol, body=_ref("declaration"))),
            retractions=_array(symbol),
            summary=string,
        ),
        "$defs": definitions,
    }


_SCHEMA = _grammar()
_MAPS = frozenset(("type_fields", "parameters", "expression_fields", "cases", "value_fields"))
_KINDS = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}


def response_schema(contract=None):
    """Fresh wire grammar with receiver-owned task bounds."""
    contract = validate_contract(contract)
    schema = deepcopy(_SCHEMA)
    declarations = schema["properties"]["declarations"]
    declarations["maxItems"] = contract["max_declarations"]
    allowed = contract["allowed_helpers"]
    if allowed is not None:
        symbols = contract["required_symbols"] + allowed
        if symbols:
            declarations["items"]["properties"]["symbol"] = _enum(*symbols)
        declarations["maxItems"] = min(declarations["maxItems"], len(symbols))
    retractions = schema["properties"]["retractions"]
    retractions["maxItems"] = (
        len(contract["allowed_retractions"]) if contract["allowed_retractions"] is not None else 64
    )
    if contract["allowed_retractions"]:
        retractions["items"] = _enum(*contract["allowed_retractions"])
    return schema


def _resolve(spec, definitions):
    if "$ref" in spec:
        ref = spec["$ref"]
        if not ref.startswith("#/$defs/") or ref.removeprefix("#/$defs/") not in definitions:
            raise InvalidIR("Unknown structured schema reference", reference=ref)
        return definitions[ref.removeprefix("#/$defs/")]
    return spec


def _matches(value, spec, definitions, budget):
    """Select disjoint grammar alternatives without speculative recursive work."""
    budget.tick()
    spec = _resolve(spec, definitions)
    if "anyOf" in spec:
        return any(_matches(value, alternative, definitions, budget) for alternative in spec["anyOf"])
    if type(value) is not _KINDS[spec["type"]]:
        return False
    if spec["type"] == "object":
        for key, child in spec["properties"].items():
            if "enum" in child and value.get(key) not in child["enum"]:
                return False
        # A type reference has no discriminator; require its distinguishing key.
        if set(spec["properties"]) == {"ref"} and "ref" not in value:
            return False
    return True


def _invalid(message, path):
    raise InvalidIR(message, path=path or "/")


def _decode(value, spec, budget, path, *, definitions=None):
    budget.tick()
    # Bind once to this schema; recursive branches must never use a global fallback.
    if definitions is None:
        definitions = spec.get("$defs", {})
    if "$ref" in spec:
        key = spec["$ref"].removeprefix("#/$defs/")
        result = _decode(value, _resolve(spec, definitions), budget, path, definitions=definitions)
        if key in _MAPS:
            mapped = {}
            for index, entry in enumerate(result):
                budget.tick()
                if entry["name"] in mapped:
                    _invalid("Duplicate name in structured declaration", f"{path}/{index}/name")
                mapped[entry["name"]] = entry["value"]
            return mapped
        if key == "object_value":
            return result["fields"]
        if key in ("literal", "transition"):
            optional = "type" if key == "literal" else "cost"
            if result[optional] is None:
                del result[optional]
        return result
    if "anyOf" in spec:
        choices = [option for option in spec["anyOf"] if _matches(value, option, definitions, budget)]
        if len(choices) != 1:
            _invalid("Unknown or ambiguous structured syntax alternative", path)
        return _decode(value, choices[0], budget, path, definitions=definitions)
    kind = spec["type"]
    if type(value) is not _KINDS[kind]:
        _invalid("Expected structured " + kind, path)
    if kind == "object":
        if set(value) != set(spec["properties"]):
            _invalid("Unexpected structured object fields", path)
        return {
            key: _decode(value[key], child, budget, path + "/" + key, definitions=definitions)
            for key, child in spec["properties"].items()
        }
    if kind == "array":
        if len(value) < spec.get("minItems", 0) or len(value) > spec.get("maxItems", len(value)):
            _invalid("Wrong structured array length", path)
        return [
            _decode(child, spec["items"], budget, f"{path}/{index}", definitions=definitions)
            for index, child in enumerate(value)
        ]
    if "enum" in spec and value not in spec["enum"]:
        _invalid("Unsupported structured value", path)
    if "pattern" in spec and re.fullmatch(spec["pattern"], value) is None:
        _invalid("Invalid structured name", path)
    if kind == "integer" and (value < spec.get("minimum", value) or value > spec.get("maximum", value)):
        _invalid("Structured integer outside format bounds", path)
    return value


def decode_proposal(source, budget, contract=None):
    """Validate all wire syntax and translate atomically, without executing it.

    The caller handles proposal status and symbol/retraction conflicts. JSON
    size/depth/integer limits apply before and after translation. Error paths
    identify the failing node without echoing full provider output.
    """
    budget.tick()
    contract = validate_contract(contract)
    check_size(source, contract)
    value = thaw(read_json(source))
    result = _decode(value, response_schema(contract), budget, "")
    budget.tick()
    return thaw(read_json(result))
