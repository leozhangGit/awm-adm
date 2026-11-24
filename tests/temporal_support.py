"""Synthetic temporal contracts, independent of provider output."""

from awm_adm.temporal_evidence.models import Catalog


def cell(kind="instant", start="2026-03-01T12:00:00Z", end=None, **kw):
    return {
        "kind": kind,
        "effective_from": start,
        "effective_to": end,
        "precision": "second",
        "timezone_basis": "UTC",
        **kw,
    }


def catalog():
    return Catalog.model_validate(
        {
            "namespace": "observations",
            "entities": ["chamber", "room", "machine"],
            "predicates": [
                {
                    "symbol": "chamber.reading",
                    "kind": "integer",
                    "unit": "units",
                    "minimum": 0,
                    "maximum": 20,
                    "meaning": "Reading",
                    "scope_kinds": ["instant", "occurrence"],
                },
                {
                    "symbol": "room.capacity",
                    "kind": "integer",
                    "unit": "places",
                    "minimum": 0,
                    "maximum": 20,
                    "meaning": "Capacity valid throughout scope",
                    "scope_kinds": ["validity", "instant"],
                },
                {
                    "symbol": "machine.output",
                    "kind": "integer",
                    "unit": "items",
                    "minimum": 0,
                    "maximum": 20,
                    "meaning": "Whole-period production total",
                    "scope_kinds": ["period_value"],
                    "metric": "production-total",
                },
            ],
            "cells": [
                cell(),
                cell("validity", "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"),
                cell("period_value", "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z"),
            ],
        }
    ).model_dump()


def fact(index=0, value=None):
    p = catalog()
    pred = p["predicates"][index]
    return {
        "entity_id": p["entities"][index],
        "predicate": pred["symbol"],
        "value": {"kind": "integer", "value": [7, 3, 14][index] if value is None else value},
        "unit": pred["unit"],
        "temporal_scope": p["cells"][index],
        "assertion_kind": "assertion",
    }
