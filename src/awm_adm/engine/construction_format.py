"""Structured knowledge updates: executable slots or new typed declarations."""

from copy import deepcopy

from .acquisition import check_size, validate_contract
from .construction import SLOTS, interfaces
from .data import read_json, thaw
from .errors import InvalidIR
from .provider_format import _SCHEMA, _array, _decode, _enum, _object, _ref

FORMAT = "adm-construction/1"


def response_schema(contract):
    contract = validate_contract(contract)
    headers = interfaces(contract)
    definitions = {}
    for symbol, header in headers.items():
        slots = SLOTS[header["kind"]]
        if slots:
            definitions[symbol] = {
                "anyOf": [
                    _object(
                        **{
                            key: _ref("nullable_expression" if key == "cost" else "expression")
                            for key in slots
                        }
                    ),
                    {"type": "null"},
                ]
            }
    symbol_schema = deepcopy(_SCHEMA["properties"]["declarations"]["items"]["properties"]["symbol"])
    unknown = (
        None
        if contract["allowed_helpers"] is None
        else sorted((set(contract["required_symbols"]) | set(contract["allowed_helpers"])) - headers.keys())
    )
    new_symbol = _enum(*unknown) if unknown else symbol_schema
    declarations = _array(
        _object(symbol=new_symbol, body=_ref("declaration")),
        maxItems=contract["max_declarations"]
        if unknown is None
        else min(len(unknown), contract["max_declarations"]),
    )
    retractions = _array(
        _enum(*contract["allowed_retractions"]) if contract["allowed_retractions"] else symbol_schema,
        maxItems=64 if contract["allowed_retractions"] is None else len(contract["allowed_retractions"]),
    )
    # The root is an object. The nested discriminated result prevents a missing-
    # evidence status from carrying executable changes, including empty fillers.
    result = {
        "anyOf": [
            _object(
                status=_enum("draft"),
                definitions=_object(**definitions),
                declarations=declarations,
                discard=_array(symbol_schema, maxItems=contract["max_declarations"]),
                retractions=retractions,
                summary={"type": "string"},
            ),
            _object(status=_enum("needs_evidence"), summary={"type": "string"}),
        ]
    }
    return {**_object(format=_enum(FORMAT), result=result), "$defs": deepcopy(_SCHEMA["$defs"])}


def decode_update(source, budget, contract):
    check_size(source, contract)
    result = _decode(thaw(read_json(source)), response_schema(contract), budget, "")["result"]
    if result["status"] == "needs_evidence":
        return result
    declarations = {}
    for entry in result["declarations"]:
        if entry["symbol"] in declarations:
            raise InvalidIR("Duplicate new declaration symbol", symbol=entry["symbol"])
        declarations[entry["symbol"]] = entry["body"]
    return {
        "status": "draft",
        "summary": result["summary"],
        "draft": {
            "definitions": result["definitions"],
            "declarations": declarations,
            "discard": result["discard"],
            "retractions": result["retractions"],
        },
    }
