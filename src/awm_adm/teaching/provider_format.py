"""Nonrecursive, model-neutral provider format; translates only to local Plan/1.

Type-node references describe finite type syntax, not learned declarations.
All semantic checks still run on the resulting local plan. No repair/coercion.
"""

from typing import Literal

from pydantic import Field

from ..contracts import ClosedModel, Identifier
from ..sources.models import Projection
from ..temporal_evidence.models import CatalogBatch
from ..wire import decode
from .diagnostics import PreparationError
from .field_guidance import OBJECTIVE, annotate_bounds
from .models import Material
from .readiness import Assessment
from .source_guidance import BOUNDS, ENTITIES, KIND, NAMESPACE, SHARED, SYMBOL, UNIT, VALUES

PROFILE = "awm-adm-teaching-reply/2"
MATERIAL_PROFILE = "awm-adm-teaching-reply/3"
SHARED_PROFILE = "awm-adm-teaching-reply/4"
TEMPORAL_PROFILE = "awm-adm-teaching-reply/5"


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


class SelectedMaterial(ClosedModel):
    projection: Projection
    material_ids: list[Identifier] = Field(min_length=1, max_length=36)


class SelectedChild(WireChild):
    material: SelectedMaterial | None


class SelectedPlan(WirePlan):
    children: list[SelectedChild] = Field(min_length=1, max_length=4)


class SelectedReply(WireReply):
    profile: Literal["awm-adm-teaching-reply/3"]
    plan: SelectedPlan | None


class MaterialSelection(ClosedModel):
    material_ids: list[Identifier] = Field(min_length=1, max_length=36)


class SharedChild(WireChild):
    material: MaterialSelection | None


class SharedPlan(ClosedModel):
    kind: Literal["capability", "facts", "correction", "mixed"]
    summary: str = Field(min_length=1, max_length=2000)
    types: list[TypeNode] = Field(max_length=128)
    source_projection: Projection | None
    children: list[SharedChild] = Field(min_length=1, max_length=4)
    aliases: list[Alias] = Field(max_length=128)
    parameters: list[Parameter] = Field(max_length=128)
    value_aliases: list[ValueAlias] = Field(max_length=128)
    requirements_json: str | None = Field(max_length=32768)


class SharedReply(WireReply):
    profile: Literal["awm-adm-teaching-reply/4"]
    plan: SharedPlan | None


class TemporalWirePlan(ClosedModel):
    kind: Literal["capability", "facts", "correction", "mixed"]
    summary: str = Field(min_length=1, max_length=2000)
    types: list[TypeNode] = Field(max_length=128)
    evidence_scope: CatalogBatch | None
    children: list[SharedChild] = Field(min_length=1, max_length=4)
    aliases: list[Alias] = Field(max_length=128)
    parameters: list[Parameter] = Field(max_length=128)
    value_aliases: list[ValueAlias] = Field(max_length=128)
    requirements_json: str | None = Field(max_length=32768)


class TemporalReply(WireReply):
    profile: Literal["awm-adm-teaching-reply/5"]
    plan: TemporalWirePlan | None


class AssessedTemporalReply(Assessment):
    profile: Literal["awm-adm-teaching-reply/6"]
    plan: TemporalWirePlan | None


class AssessedLegacyReply(Assessment):
    profile: Literal["awm-adm-teaching-reply/7"]
    plan: WirePlan | None


REUSE_TEMPORAL_PROFILE = "awm-adm-teaching-reply/8"
REUSE_LEGACY_PROFILE = "awm-adm-teaching-reply/9"


class ReaffirmingWireChild(WireChild):
    kind: Literal["capability", "facts", "correction", "reaffirmation"]
    reuse_symbols: list[str] = Field(max_length=32)


class ReaffirmingSelectedChild(ReaffirmingWireChild):
    material: MaterialSelection | None


class ReaffirmingWirePlan(WirePlan):
    kind: Literal["capability", "facts", "correction", "reaffirmation", "mixed"]
    children: list[ReaffirmingWireChild] = Field(min_length=1, max_length=4)


class ReaffirmingTemporalWirePlan(TemporalWirePlan):
    kind: Literal["capability", "facts", "correction", "reaffirmation", "mixed"]
    children: list[ReaffirmingSelectedChild] = Field(min_length=1, max_length=4)


class ReaffirmingTemporalReply(Assessment):
    profile: Literal["awm-adm-teaching-reply/8"]
    plan: ReaffirmingTemporalWirePlan | None


class ReaffirmingLegacyReply(Assessment):
    profile: Literal["awm-adm-teaching-reply/9"]
    plan: ReaffirmingWirePlan | None


def expand_shared_projection(value, field="source_projection"):
    """Expand one explicit projection into the unchanged local child contract.

    No union, normalization, new coverage or inference from child objectives.
    Runs only for replies dispatched under the shared-projection profile.
    """
    from copy import deepcopy

    projection = value.pop(field)
    has_material = any(c["material"] is not None for c in value["children"])
    if has_material and projection is None:
        raise PreparationError("sources", "shared_projection_required")
    if not has_material and projection is not None:
        raise PreparationError("sources", "unused_shared_projection")
    for child in value["children"]:
        if child["material"] is not None:
            child["material"]["projection"] = deepcopy(projection)


def response_schema(
    *,
    material_refs=False,
    shared_projection=False,
    temporal_evidence=False,
    assessed=False,
    reaffirmation=False,
):
    """Inline the acyclic schema; limits and refinements remain local checks."""
    schema = (
        ReaffirmingTemporalReply
        if reaffirmation and temporal_evidence
        else ReaffirmingLegacyReply
        if reaffirmation
        else AssessedTemporalReply
        if assessed and temporal_evidence
        else AssessedLegacyReply
        if assessed
        else TemporalReply
        if temporal_evidence
        else SharedReply
        if shared_projection
        else SelectedReply
        if material_refs
        else WireReply
    ).model_json_schema()
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
    if assessed or reaffirmation:
        from .readiness import INSTRUCTIONS

        result["properties"]["missing_information"]["description"] = INSTRUCTIONS
    plan = result["properties"]["plan"]["anyOf"][0]["properties"]
    plan["children"]["items"]["properties"]["objective"]["description"] = OBJECTIVE
    if reaffirmation:
        plan["children"]["items"]["properties"]["reuse_symbols"]["description"] = (
            "For reaffirmation only: 1–32 unique existing qualified declaration symbols whose exact "
            "accepted definitions are retained. Use interfaces [] and material null. For all other "
            "kinds use []. Do not label a change or additional obligation as unchanged reuse."
        )
    if temporal_evidence:
        from ..temporal_evidence.guidance import ASSESSED_PREPARATION, INSTRUCTIONS, describe_scope

        plan["evidence_scope"]["description"] = ASSESSED_PREPARATION if assessed else INSTRUCTIONS
        catalog = plan["evidence_scope"]["anyOf"][0]["properties"]
        catalog["namespace"]["description"] = NAMESPACE
        catalog["entities"]["description"] = ENTITIES
        predicate = catalog["predicates"]["items"]["properties"]
        for name, description in (
            ("symbol", SYMBOL),
            ("unit", UNIT),
            ("kind", KIND),
            ("values", VALUES),
            ("minimum", BOUNDS),
            ("maximum", BOUNDS),
        ):
            predicate[name]["description"] = description
        describe_scope(catalog["cells"]["items"])
        return annotate_bounds(result, schema, definitions)
    if shared_projection:
        plan["source_projection"]["description"] = SHARED
        projection = plan["source_projection"]["anyOf"][0]["properties"]
    else:
        projection = plan["children"]["items"]["properties"]["material"]["anyOf"][0]["properties"][
            "projection"
        ]["properties"]
    # Annotations explain local constraints without changing the shallow wire grammar.
    projection["namespace"]["description"] = NAMESPACE
    projection["entities"]["description"] = ENTITIES
    predicate = projection["predicates"]["items"]["properties"]
    for name, description in (
        ("symbol", SYMBOL),
        ("unit", UNIT),
        ("kind", KIND),
        ("values", VALUES),
        ("minimum", BOUNDS),
        ("maximum", BOUNDS),
    ):
        predicate[name]["description"] = description
    # Unknown is a query result, never an owner projection time cell.
    cell = projection["cells"]["items"]
    cell["properties"]["kind"]["enum"] = ["point", "interval"]
    from ..temporal import INSTANT, SCOPE

    cell["description"] = SCOPE
    for name in ("effective_from", "effective_to"):
        cell["properties"][name]["description"] = INSTANT
    return annotate_bounds(result, schema, definitions)


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
