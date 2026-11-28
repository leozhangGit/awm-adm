"""Accumulated capacity is distinct from per-request coverage and accepted facts."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from awm_adm.engine.data import read_json, thaw
from awm_adm.runtime.protocol import RuntimeFault, unpack
from awm_adm.temporal_evidence.capacity import CatalogCapacity, context_window, extraction_catalog
from awm_adm.temporal_evidence.legacy import extend
from awm_adm.temporal_evidence.models import Catalog, CatalogBatch

from .temporal_support import catalog, fact
from .test_application import app_runtime as app_runtime
from .test_sources import ingest, install, project
from .test_temporal_evidence import ask


def many(start, count):
    p = catalog()
    p["entities"], p["cells"] = p["entities"][:1], p["cells"][:1]
    template = p["predicates"][0]
    p["predicates"] = [{**template, "symbol": f"record.p{i}"} for i in range(start, start + count)]
    return p


def test_18_plus_19_with_shared_identity_produces_36_without_redefinition():
    old, new = many(0, 18), many(17, 19)
    assert len(CatalogBatch.model_validate(new).predicates) == 19
    merged = extend(old, new)
    assert len(merged["predicates"]) == 36
    assert merged["predicates"][:18] == old["predicates"]
    assert len(old["predicates"]) == 18
    changed = deepcopy(new)
    changed["predicates"][0]["unit"] = "different"
    with pytest.raises(ValueError, match="meaning"):
        extend(old, changed)


def test_numeric_ceiling_and_safe_counts_not_raw_values():
    old = many(0, 65_536)
    assert len(Catalog.model_validate(old).predicates) == 65_536
    with pytest.raises(CatalogCapacity) as exc:
        extend(old, many(65_535, 2))
    assert exc.value.diagnostic == {
        "code": "catalog_capacity_exceeded",
        "stage": "catalog_extension",
        "message": str(exc.value),
        "resource": "predicates",
        "existing": 65_536,
        "proposed": 2,
        "shared": 1,
        "required": 65_537,
        "limit": 65_536,
    }
    assert "record.p" not in str(exc.value)
    with pytest.raises(ValidationError):
        CatalogBatch.model_validate(many(0, 33))
    with pytest.raises(ValidationError):
        Catalog.model_validate(many(0, 65_537))


def test_sparse_catalog_does_not_allocate_cartesian_facts():
    p = many(0, 1000)
    p["entities"] = [f"entity{i}" for i in range(128)]
    assert len(Catalog.model_validate(p).predicates) == 1000
    with pytest.raises(ValidationError, match="4096"):
        CatalogBatch.model_validate({**p, "predicates": p["predicates"][:32], "cells": catalog()["cells"]})


def test_provider_working_set_is_explicit_and_never_silently_selected():
    p = many(0, 300)
    with pytest.raises(RuntimeFault, match="Select up to 256"):
        extraction_catalog(p, None, external=True)
    chosen = extraction_catalog(p, ["record.p299"], external=True)
    assert chosen["predicates"] == p["predicates"][299:]
    with pytest.raises(RuntimeFault, match="unknown"):
        extraction_catalog(p, ["record.missing"], external=True)
    with pytest.raises(RuntimeFault, match="duplicate"):
        extraction_catalog(p, ["record.p0", "record.p0"], external=True)
    window, metadata = context_window(p, "record p299")
    assert metadata["complete"] is False
    assert len(window["predicates"]) == 256
    assert window["predicates"][0]["symbol"] == "record.p299"
    assert len(p["predicates"]) == 300


def test_incremental_growth_preserves_fact_and_independent_snapshot(app_runtime):
    rt = app_runtime
    key = rt.create("Synthetic sparse catalog")["id"]
    initial = catalog()
    install(rt, key, projection=initial)
    assert project(rt, key, ingest(rt, key, [fact(0)]))["status"] == "accepted"
    before = unpack(rt.store.snapshot(key))
    expanded = extend(initial, many(0, 40))
    rt.sources.coverage(
        key,
        {
            "expected_revision": rt.store.info(key)["revision_id"],
            "expected_generation": rt.sources.policy(key)["generation"],
            "kind": "extend",
            "projection": expanded,
            "reason": "Additional independent properties",
        },
    )
    after = unpack(rt.store.snapshot(key))
    for name, raw in before.files.items():
        if thaw(read_json(raw)).get("artifact_kind") in {"evidence", "declaration"}:
            assert after.files[name] == raw
    assert ask(rt, key)["result"]["value"]["value"] == 7
    copy = rt.create("Independent sparse copy", snapshot=rt.store.snapshot(key))["id"]
    assert ask(rt, copy)["result"]["value"]["value"] == 7
    bindings = [
        thaw(read_json(v))["content"]
        for v in after.files.values()
        if thaw(read_json(v)).get("artifact_kind") == "evidence"
        and isinstance(thaw(read_json(v)).get("content"), dict)
        and thaw(read_json(v))["content"].get("profile") == "awm-adm-temporal-binding/1"
    ]
    assert len(bindings) == 1
    assert len(bindings[0]["projection"]["predicates"]) == 1
    assert len(bindings[0]["projection"]["entities"]) == 1
    assert rt.learning.usage()["calls"] == 0


def test_preparation_window_is_explicit_and_does_not_include_full_catalog():
    from awm_adm.teaching.prompt import specification

    task = {"objective": "record p299", "inputs": [], "material_manifest": {"entries": []}}
    p = many(0, 300)
    spec = specification(task, {}, {}, {"projection": p, "sources": []})
    policy = spec["context"]["source_policy"]
    assert policy["catalog_selection"]["complete"] is False
    assert len(policy["projection"]["predicates"]) == 256
    assert policy["projection"] == policy["compatible_catalog"]
    assert len(p["predicates"]) == 300


def test_sparse_snapshot_interpretation_has_bounded_relevant_metadata(monkeypatch):
    from awm_adm.conversations.history import snapshot_metadata
    from awm_adm.engine import Budget
    from awm_adm.sources import compute

    profiles = [{**many(i, 1), "entities": [f"entity{i}"]} for i in range(40)]
    monkeypatch.setattr(
        compute, "projected", lambda *_: {str(i): {"projection": p} for i, p in enumerate(profiles)}
    )
    with pytest.raises(ValueError, match="disclosure bound"):
        snapshot_metadata({}, Budget())
    selected, details = snapshot_metadata({}, Budget(), utterance="entity39 record p39")
    assert details == {
        "complete": False,
        "total_profiles": 40,
        "included_profiles": 32,
        "selection": "lexical_relevance",
    }
    assert selected[0]["entities"] == ["entity39"]
    assert len(selected) == 32


def test_invalid_values_and_unknown_predicates_remain_held_after_catalog_growth():
    from awm_adm.temporal_evidence.identity import resolve
    from awm_adm.temporal_evidence.models import Extracted

    p = extend(catalog(), many(0, 40))
    wrong = Extracted.model_validate(fact(0, value=100)).model_dump()
    assert resolve(p, wrong) == ([], "value_outside_carrier")
    wrong["predicate"] = "not.known"
    assert resolve(p, wrong) == ([], "unknown_entity_or_predicate")
