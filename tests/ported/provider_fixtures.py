"""Authored wire fixtures; no provider acquisition or model-generated content."""

from copy import deepcopy

from awm_adm.engine.provider_format import FORMAT


def named(values, convert=lambda value: value):
    return [{"name": key, "value": convert(value)} for key, value in values.items()]


def wire_type(spec):
    result = deepcopy(spec)
    kind = spec.get("kind")
    if kind in ("record", "sum"):
        field = "fields" if kind == "record" else "variants"
        result[field] = named(spec[field], wire_type)
    elif kind == "vector":
        result["element"] = wire_type(spec["element"])
    elif kind == "refined":
        result.update(base=wire_type(spec["base"]), where=wire_expression(spec["where"]))
    return result


def wire_value(value):
    if isinstance(value, dict):
        return {"fields": named(value, wire_value)}
    if isinstance(value, list):
        return [wire_value(child) for child in value]
    return value


def wire_expression(expr):
    result, op = deepcopy(expr), expr["op"]
    if op == "literal":
        return {
            "op": op,
            "value": wire_value(expr["value"]),
            "type": wire_type(expr["type"]) if "type" in expr else None,
        }
    for field in ("record", "condition", "then", "else", "vector", "index", "body"):
        if field in expr:
            result[field] = wire_expression(expr[field])
    if "type" in expr:
        result["type"] = wire_type(expr["type"])
    if "fields" in expr:
        result["fields"] = named(expr["fields"], wire_expression)
    if "args" in expr:
        result["args"] = (
            named(expr["args"], wire_expression)
            if op == "call"
            else [wire_expression(arg) for arg in expr["args"]]
        )
    if op in ("tag", "match"):
        result["value"] = wire_expression(expr["value"])
    if op == "match":
        result["cases"] = named(
            expr["cases"], lambda case: {"bind": case["bind"], "body": wire_expression(case["body"])}
        )
    if op == "vector":
        result["items"] = [wire_expression(item) for item in expr["items"]]
    return result


def wire_declaration(body):
    result, kind = deepcopy(body), body["kind"]
    for field in (
        "type",
        "returns",
        "state",
        "parameters",
        "carrier",
        "left",
        "right",
        "base",
        "source",
        "target",
    ):
        if field in body:
            result[field] = wire_type(body[field])
    if "params" in body:
        result["params"] = named(body["params"], wire_type)
    for field in ("body", "legal", "next", "cost"):
        if field in body:
            result[field] = wire_expression(body[field])
    if kind == "transition" and "cost" not in body:
        result["cost"] = None
    return result


def wire_proposal(content):
    return {
        "format": FORMAT,
        "status": "candidate",
        "declarations": [
            {"symbol": symbol, "body": wire_declaration(body)} for symbol, body in content.items()
        ],
        "retractions": [],
        "summary": "Authored mathematical fixture; no external observation.",
    }


def reservations_proposal(capacity=2):
    """Build directly in wire syntax to exercise nested calls, updates and maps."""
    actors = ("alice", "bob", "carol")
    boolean, state_type, actor_type = (
        {"kind": "bool"},
        {"ref": "reservations.State"},
        {"ref": "reservations.Actor"},
    )

    def lit(value, type=None):
        return {"op": "literal", "value": value, "type": type}

    def var(name):
        return {"op": "var", "name": name}

    def op(operator, *args):
        return {"op": operator, "args": list(args)}

    def call(name, **args):
        return {"op": "call", "function": "reservations." + name, "args": named(args)}

    def get(actor, kind):
        return {"op": "get", "record": var("state"), "field": actor + "_" + kind}

    def branch(condition, yes, no):
        return {"op": "if", "condition": condition, "then": yes, "else": no}

    def function(params, returns, body):
        return {
            "kind": "function",
            "params": named(params),
            "returns": returns,
            "body": body,
        }

    count = {"kind": "int", "min": 0, "max": 3}
    definitions = {
        "Actor": {"kind": "type", "type": {"kind": "enum", "values": list(actors)}},
        "State": {
            "kind": "type",
            "type": {
                "kind": "record",
                "fields": named(
                    {actor + "_" + flag: boolean for actor in actors for flag in ("access", "reserved")}
                ),
            },
        },
        "capacity": function({}, {"kind": "int", "min": 1, "max": 3}, lit(capacity)),
        "occupied": function(
            {"state": state_type},
            count,
            op(
                "add",
                op(
                    "add",
                    branch(get("alice", "reserved"), lit(1), lit(0)),
                    branch(get("bob", "reserved"), lit(1), lit(0)),
                ),
                branch(get("carol", "reserved"), lit(1), lit(0)),
            ),
        ),
    }
    for name, flag in (("has_access", "access"), ("is_reserved", "reserved")):
        expression = get("carol", flag)
        for actor in reversed(actors[:2]):
            expression = branch(op("eq", var("actor"), lit(actor, actor_type)), get(actor, flag), expression)
        definitions[name] = function({"state": state_type, "actor": actor_type}, boolean, expression)
    definitions["valid"] = function(
        {"state": state_type},
        boolean,
        op(
            "and",
            *[op("or", op("not", get(actor, "reserved")), get(actor, "access")) for actor in actors],
            op("le", call("occupied", state=var("state")), call("capacity")),
        ),
    )
    definitions["can_reserve"] = function(
        {"state": state_type, "actor": actor_type},
        boolean,
        op(
            "and",
            call("valid", state=var("state")),
            call("has_access", state=var("state"), actor=var("actor")),
            op("not", call("is_reserved", state=var("state"), actor=var("actor"))),
            op("lt", call("occupied", state=var("state")), call("capacity")),
        ),
    )
    has_access = call("has_access", state=var("state"), actor=var("action"))
    is_reserved = call("is_reserved", state=var("state"), actor=var("action"))
    guards = {
        "grant": op("not", has_access),
        "revoke": op("and", has_access, op("not", is_reserved)),
        "reserve": call("can_reserve", state=var("state"), actor=var("action")),
        "release": is_reserved,
    }
    for action, guard in guards.items():
        flag, value = (
            ("access" if action in ("grant", "revoke") else "reserved"),
            action in ("grant", "reserve"),
        )
        updates = [
            {"op": "update", "record": var("state"), "fields": named({actor + "_" + flag: lit(value)})}
            for actor in actors
        ]
        successor = branch(
            op("eq", var("action"), lit("alice", actor_type)),
            updates[0],
            branch(op("eq", var("action"), lit("bob", actor_type)), updates[1], updates[2]),
        )
        definitions[action] = {
            "kind": "transition",
            "state": state_type,
            "parameters": actor_type,
            "legal": op("and", call("valid", state=var("state")), guard),
            "next": successor,
            "cost": None,
        }
    for name, target in (("two_reserved", 2), ("three_reserved", 3)):
        definitions[name] = {
            "kind": "goal",
            "state": state_type,
            "body": op(
                "and",
                call("valid", state=var("state")),
                op("ge", call("occupied", state=var("state")), lit(target)),
            ),
        }
    definitions["capacity_assumption"] = {
        "kind": "assertion",
        "params": [],
        "body": op("eq", call("capacity"), lit(capacity)),
    }
    definitions["valid_capacity"] = {
        "kind": "assertion",
        "params": named({"state": state_type}),
        "body": op(
            "or",
            op("not", call("valid", state=var("state"))),
            op("le", call("occupied", state=var("state")), call("capacity")),
        ),
    }
    definitions["reserve_requires_access"] = {
        "kind": "assertion",
        "params": named({"state": state_type, "actor": actor_type}),
        "body": op(
            "or",
            op("not", call("can_reserve", state=var("state"), actor=var("actor"))),
            call("has_access", state=var("state"), actor=var("actor")),
        ),
    }
    return {
        "format": FORMAT,
        "status": "candidate",
        "retractions": [],
        "declarations": [
            {"symbol": "reservations." + key, "body": body} for key, body in definitions.items()
        ],
        "summary": "Authored reservation rules for offline transport validation; not a provider-generated model.",
    }
