"""Nonrecursive, model-neutral provider format; translates only to local Plan/1.

Type-node references describe finite type syntax, not learned declarations.
All semantic checks still run on the resulting local plan. No repair/coercion.
"""

from typing import Literal

from pydantic import Field

from ..contracts import ClosedModel, Identifier
from ..wire import decode
from .diagnostics import PreparationError
from .models import Material
from .source_guidance import BOUNDS, KIND, NAMESPACE, SYMBOL, VALUES

PROFILE = "awm-adm-teaching-reply/2"


class Member(ClosedModel):
    name: str = Field(min_length=1, max_length=128)
    type_id: Identifier


class TypeNode(ClosedModel):
    id: Identifier
    kind: Literal["bool", "int", "enum", "record", "sum", "vector", "ref"]
    minimum: int | None
    maximum: int | None
    values: list[str] = Field(max_length=64)
    members: list[Member] = Field(max_length=64)
    element_id: Identifier | None
    length: int | None = Field(ge=0, le=32)
    symbol: str | None


class Header(ClosedModel):
    symbol: str = Field(min_length=1, max_length=256)
    kind: Literal["type", "function", "assertion", "goal", "transition"]
    type_id: Identifier | None
    params: list[Member] = Field(max_length=32)
    returns_id: Identifier | None
    state_id: Identifier | None
    parameters_id: Identifier | None


class WireChild(ClosedModel):
    kind: Literal["capability", "facts", "correction"]
    objective: str = Field(min_length=1, max_length=2000)
    input_ids: list[Identifier] = Field(min_length=1, max_length=4)
    interfaces: list[Header] = Field(max_length=32)
    material: Material | None


class Alias(ClosedModel):
    alias: str = Field(min_length=1, max_length=100)
    targets: list[str] = Field(min_length=1, max_length=16)


class Parameter(ClosedModel):
    symbol: str
    parameter: str
    unit: str | None
    role: Literal["value", "entity", "time"] | None


class ValueAlias(ClosedModel):
    symbol: str
    parameter: str
    alias: str
    value_json: str = Field(max_length=4096)


class WirePlan(ClosedModel):
    kind: Literal["capability", "facts", "correction", "mixed"]
    summary: str = Field(min_length=1, max_length=2000)
    types: list[TypeNode] = Field(max_length=128)
    children: list[WireChild] = Field(min_length=1, max_length=4)
    aliases: list[Alias] = Field(max_length=128)
    parameters: list[Parameter] = Field(max_length=128)
    value_aliases: list[ValueAlias] = Field(max_length=128)
    requirements_json: str | None = Field(max_length=32768)


class WireReply(ClosedModel):
    profile: Literal["awm-adm-teaching-reply/2"]
    status: Literal["ready", "needs_clarification", "unsupported"]
    message: str = Field(min_length=1, max_length=2000)
    plan: WirePlan | None


def response_schema():
    """Inline the acyclic schema; limits and refinements remain local checks."""
    schema = WireReply.model_json_schema()
    definitions = schema.get("$defs", {})

    def simplify(node):
        if "$ref" in node:
            return simplify(definitions[node["$ref"].rsplit("/", 1)[1]])
        if "anyOf" in node:
            return {"anyOf": [simplify(n) for n in node["anyOf"]]}
        result = {k: node[k] for k in ("type", "enum") if k in node}
        if "const" in node:
            result["enum"] = [node["const"]]
        if node.get("type") == "object":
            result.update(properties={k: simplify(v) for k, v in node["properties"].items()})
            result.update(required=list(result["properties"]), additionalProperties=False)
        if "items" in node:
            result["items"] = simplify(node["items"])
        return result

    result = simplify(schema)
    projection = result["properties"]["plan"]["anyOf"][0]["properties"]["children"]["items"]["properties"][
        "material"
    ]["anyOf"][0]["properties"]["projection"]["properties"]
    # Annotations explain local constraints without changing the shallow wire grammar.
    projection["namespace"]["description"] = NAMESPACE
    predicate = projection["predicates"]["items"]["properties"]
    for name, description in (
        ("symbol", SYMBOL),
        ("kind", KIND),
        ("values", VALUES),
        ("minimum", BOUNDS),
        ("maximum", BOUNDS),
    ):
        predicate[name]["description"] = description
    # Unknown is a query result, never an owner projection time cell.
    cell = projection["cells"]["items"]
    cell["properties"]["kind"]["enum"] = ["point", "interval"]
    return result


def unique(items, key, stage):
    result = {}
    for item in items:
        uid = key(item)
        if uid in result:
            raise PreparationError(stage, "duplicate_identity")
        result[uid] = item
    return result


def inactive(value, allowed, stage):
    if any(v not in (None, []) for k, v in value.items() if k not in allowed):
        raise PreparationError(stage, "unused_field")


def local_plan(value, budget):
    nodes = unique(value["types"], lambda n: n["id"], "types")
    used = set()
    expanded = 0

    def type_spec(uid, path=()):
        nonlocal expanded
        budget.tick()
        expanded += 1
        if uid not in nodes or uid in path:
            raise PreparationError("types", "missing_or_cyclic_type")
        if len(path) >= 24 or expanded > 4096:
            raise PreparationError("types", "type_expansion_limit")
        used.add(uid)
        n = nodes[uid]
        kind = n["kind"]
        fields = {
            "bool": (),
            "int": ("minimum", "maximum"),
            "enum": ("values",),
            "record": ("members",),
            "sum": ("members",),
            "vector": ("element_id", "length"),
            "ref": ("symbol",),
        }[kind]
        inactive(n, {"id", "kind", *fields}, "types")
        if any(n[f] is None for f in fields):
            raise PreparationError("types", "missing_type_field")
        if kind == "ref":
            return {"ref": n["symbol"]}
        result = {"kind": kind}
        if kind == "int":
            result.update(min=n["minimum"], max=n["maximum"])
        elif kind == "enum":
            result["values"] = n["values"]
        elif kind in {"record", "sum"}:
            members = unique(n["members"], lambda m: m["name"], "types")
            result["fields" if kind == "record" else "variants"] = {
                name: type_spec(m["type_id"], (*path, uid)) for name, m in members.items()
            }
        elif kind == "vector":
            result.update(element=type_spec(n["element_id"], (*path, uid)), length=n["length"])
        return result

    children = []
    for child in value["children"]:
        headers = unique(child["interfaces"], lambda h: h["symbol"], "interfaces")
        mapped = {}
        for symbol, h in headers.items():
            fields = {
                "type": ("type_id",),
                "function": ("params", "returns_id"),
                "assertion": ("params",),
                "goal": ("state_id",),
                "transition": ("state_id", "parameters_id"),
            }[h["kind"]]
            inactive(h, {"symbol", "kind", *fields}, "interfaces")
            header = {"kind": h["kind"]}
            for field in fields:
                if field == "params":
                    params = unique(h[field], lambda p: p["name"], "interfaces")
                    header[field] = {name: type_spec(p["type_id"]) for name, p in params.items()}
                else:
                    header[field.removesuffix("_id")] = type_spec(h[field])
            mapped[symbol] = header
        children.append({**child, "interfaces": mapped})
    if used != set(nodes):
        raise PreparationError("types", "unreferenced_type")
    vocabulary = {"aliases": {}, "parameter_units": {}, "parameter_roles": {}, "value_aliases": {}}
    for alias, row in unique(value["aliases"], lambda a: a["alias"], "vocabulary").items():
        vocabulary["aliases"][alias] = row["targets"]
    for (symbol, param), row in unique(
        value["parameters"], lambda p: (p["symbol"], p["parameter"]), "vocabulary"
    ).items():
        for field, source in (("parameter_units", "unit"), ("parameter_roles", "role")):
            if row[source] is not None:
                vocabulary[field].setdefault(symbol, {})[param] = row[source]
    for (symbol, param, alias), row in unique(
        value["value_aliases"], lambda p: (p["symbol"], p["parameter"], p["alias"]), "vocabulary"
    ).items():
        try:
            item = decode(row["value_json"].encode())
        except ValueError as error:
            raise PreparationError("vocabulary", "invalid_value_json") from error
        vocabulary["value_aliases"].setdefault(symbol, {}).setdefault(param, {})[alias] = item
    try:
        requirements = (
            decode(value["requirements_json"].encode()) if value["requirements_json"] is not None else None
        )
    except ValueError as error:
        raise PreparationError("requirements", "invalid_requirements_json") from error
    return {
        "kind": value["kind"],
        "summary": value["summary"],
        "children": children,
        "vocabulary": vocabulary,
        "requirements": requirements,
    }
