"""Read-only compatibility views. Never rewrite a retained legacy artifact."""

from ..sources.models import Projection
from .identity import scope_key
from .models import Catalog, Series


def scope(old):
    return {
        "kind": "instant" if old["kind"] == "point" else "validity",
        "effective_from": old["effective_from"],
        "effective_to": old["effective_to"],
        "precision": "legacy",
        "timezone_basis": "legacy_unrecorded",
    }


def series(old):
    return Series.model_validate(
        {**old, "meaning": old["symbol"], "scope_kinds": ["instant", "validity"]}
    ).model_dump()


def view(profile):
    old = Projection.model_validate(profile).model_dump()
    return {
        "profile": "awm-adm-temporal-catalog/1",
        "namespace": old["namespace"],
        "entities": old["entities"],
        "predicates": [series(p) for p in old["predicates"]],
        "cells": [scope(c) for c in old["cells"]],
    }


def entry(symbol, old):
    p = next(p for p in old["projection"]["predicates"] if p["symbol"] == old["claim"]["predicate"])
    f = {
        **old["claim"],
        "temporal_scope": scope(old["cell"]),
        "observed_time": {"kind": "unknown"},
        "reported_time": {"kind": "unknown"},
        "occurrence_id": None,
    }
    return {
        "symbol": symbol,
        "claim": f,
        "series": series(p),
        "cell": f["temporal_scope"],
        "disputed": old["disputed"],
        "legacy": old,
    }


def is_catalog(profile):
    return isinstance(profile, dict) and profile.get("profile") == "awm-adm-temporal-catalog/1"


def validate(profile):
    return (Catalog if is_catalog(profile) else Projection).model_validate(profile).model_dump()


def extend(current, proposed):
    """Additive catalog extension preserves existing meaning, including legacy cells."""
    if not current:
        return validate(proposed)
    a = current if is_catalog(current) else view(current)
    b = proposed if is_catalog(proposed) else view(proposed)
    if a["namespace"] != b["namespace"]:
        raise ValueError("Evidence catalog cannot rename its accepted namespace")
    predicates = {p["symbol"]: p for p in a["predicates"]}
    for p in b["predicates"]:
        if p["symbol"] in predicates and p != predicates[p["symbol"]]:
            raise ValueError("An existing predicate's carrier and temporal meaning cannot change additively")
        predicates[p["symbol"]] = p
    cells = {scope_key(c): c for c in a["cells"]}
    for c in b["cells"]:
        cells.setdefault(scope_key(c), c)
    return Catalog.model_validate(
        {
            **a,
            "entities": list(dict.fromkeys(a["entities"] + b["entities"])),
            "predicates": list(predicates.values()),
            "cells": list(cells.values()),
        }
    ).model_dump()
