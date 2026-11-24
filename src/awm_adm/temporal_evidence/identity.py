"""Deterministic temporal identity. Presentation, sources and partitions are not precedence."""

from ..engine.artifacts import digest
from ..engine.data import encode


def scope_key(scope):
    # Equal UTC denotations do not become independent facts by changing display timezone.
    return digest(encode({k: scope.get(k) for k in ("kind", "effective_from", "effective_to")}))


def descriptor_key(series):
    return digest(encode(series))


def property_key(fact, series):
    return {
        "entity": fact["entity_id"],
        "predicate": series["symbol"],
        "statement_level": series.get("statement_level", "direct"),
        "qualifiers": series.get("qualifiers", []),
        "actor": series.get("actor"),
        "modality": series.get("modality"),
        "metric": series.get("metric"),
    }


def address(fact, series):
    value = {**property_key(fact, series), "scope": scope_key(fact["temporal_scope"])}
    if series.get("statement_level") == "reported":
        a = fact["reported_time"]
        if a["kind"] == "unknown":
            raise ValueError("A reported proposition requires a supported report occurrence")
        value["report"] = {k: a.get(k) for k in ("kind", "effective_from", "effective_to")}
        if a["kind"] == "window":
            value["report"]["occurrence"] = fact.get("occurrence_id") or digest(encode(fact["source"]))
    if fact["temporal_scope"]["kind"] == "occurrence":
        value["occurrence"] = fact.get("occurrence_id") or digest(encode(fact["source"]))
    return digest(encode(value))


def relation(a, sa, b, sb):
    if property_key(a, sa) != property_key(b, sb):
        return "distinct"
    if sa.get("statement_level") == "reported":
        if {k: a["reported_time"].get(k) for k in ("kind", "effective_from", "effective_to")} != {
            k: b["reported_time"].get(k) for k in ("kind", "effective_from", "effective_to")
        }:
            return "distinct"
    if sa.get("statement_level") == "reported" and a["reported_time"]["kind"] == "window":
        left = a.get("occurrence_id") or digest(encode(a["source"]))
        right = b.get("occurrence_id") or digest(encode(b["source"]))
        if left != right:
            return "uncertain"
    x, y = a["temporal_scope"], b["temporal_scope"]
    if "occurrence" in (x["kind"], y["kind"]):
        return "same" if address(a, sa) == address(b, sb) else "uncertain"
    if "period_value" in (x["kind"], y["kind"]):
        return "same" if x["kind"] == y["kind"] and scope_key(x) == scope_key(y) else "distinct"
    if scope_key(x) == scope_key(y):
        return "same"
    if x["kind"] == y["kind"] == "instant":
        return "distinct"
    if x["kind"] == "instant":
        overlap = y["effective_from"] <= x["effective_from"] < y["effective_to"]
    elif y["kind"] == "instant":
        overlap = x["effective_from"] <= y["effective_from"] < x["effective_to"]
    else:
        overlap = x["effective_from"] < y["effective_to"] and y["effective_from"] < x["effective_to"]
    return "overlap" if overlap else "distinct"


def resolve(catalog, fact):
    from .models import Catalog, Claim

    catalog = Catalog.model_validate(catalog).model_dump()
    # Extracted facts have no service-owned claim identity yet.
    if "claim_id" in fact:
        fact = Claim.model_validate(fact).model_dump()
    series = next((p for p in catalog["predicates"] if p["symbol"] == fact["predicate"]), None)
    if series is None or fact["entity_id"] not in catalog["entities"]:
        return [], "unknown_entity_or_predicate"
    if fact["assertion_kind"] != "assertion":
        return [], "non_assertion"
    value = fact["value"]
    if value["kind"] != series["kind"] or fact["unit"] != series["unit"]:
        return [], "type_or_unit_mismatch"
    if (value["kind"] == "integer" and not series["minimum"] <= value["value"] <= series["maximum"]) or (
        value["kind"] == "enum" and value["value"] not in series["values"]
    ):
        return [], "value_outside_carrier"
    if fact["temporal_scope"]["kind"] not in series["scope_kinds"]:
        return [], "temporal_meaning_mismatch"
    if series["statement_level"] == "reported" and fact["reported_time"]["kind"] == "unknown":
        return [], "unknown_report_occurrence"
    cells = [c for c in catalog["cells"] if scope_key(c) == scope_key(fact["temporal_scope"])]
    return ([fact["temporal_scope"]], None) if cells else ([], "outside_coverage")
