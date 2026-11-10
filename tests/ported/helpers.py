import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOOL = {"kind": "bool"}
UNIT = {"kind": "record", "fields": {}}


def fixture(name):
    return json.loads((ROOT / "tests/fixtures/v1" / "models" / (name + ".json")).read_text())


def literal(value, type=None):
    return {"op": "literal", "value": value, **({"type": type} if type is not None else {})}


def variable(name):
    return {"op": "var", "name": name}


def operator(op, *args):
    return {"op": op, "args": list(args)}


def function(params, returns, body):
    return {"kind": "function", "params": params, "returns": returns, "body": body}


def theory(**declarations):
    return {"profile": "finite-v0", "declarations": declarations}


def call(symbol, **args):
    return {"op": "call", "function": symbol, "args": args}


def integer(low, high):
    return {"kind": "int", "min": low, "max": high}
