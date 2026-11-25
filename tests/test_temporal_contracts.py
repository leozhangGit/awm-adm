"""Temporal semantics and the unchanged kernel feasibility gate; entirely offline."""

from copy import deepcopy

import pytest

from awm_adm.engine import Instance, build_candidate
from awm_adm.engine.data import encode
from awm_adm.runtime.protocol import pack, unpack
from awm_adm.sources.compute import declaration, evidence
from awm_adm.temporal import day_bounds
from awm_adm.temporal_evidence.identity import address, relation, resolve, scope_key
from awm_adm.temporal_evidence.models import Anchor, Catalog, Claim, Extracted, Scope

from .temporal_support import catalog, cell, fact


def with_identity(f):
    return Claim.model_validate(
        {
            **f,
            "claim_id": "example",
            "source": {
                "source_id": "fixture",
                "item_id": "record",
                "version_id": "one",
                "content_digest": "sha256:" + "0" * 64,
                "start_byte": 0,
                "end_byte": 1,
            },
        }
    ).model_dump()


def test_mixed_temporal_values_compile_without_new_kernel_primitives():
    p = catalog()
    inst = Instance()
    declarations = {f"observations.value{i}": declaration(p, fact(i)) for i in range(3)}
    candidate = build_candidate(
        inst._model,
        declarations,
        candidate_id="mixed-contract-prototype",
        evidence=[evidence({"synthetic": True})],
    )
    inst.receive(candidate, review_required=False)
    assert inst.decide_next()["status"] == "accepted"
    for i, expected in enumerate((7, 3, 14)):
        assert (
            inst._model.evaluate({"op": "call", "function": f"observations.value{i}", "args": {}})["value"]
            == expected
        )
    legacy = pack(inst.export_snapshot())
    assert pack(unpack(legacy)) == legacy
    with pytest.raises(ValueError, match="snapshot"):
        unpack(
            {
                "profile": "awm-adm-service-snapshot/1",
                "required_features": ["temporal-evidence/1"],
                "core": legacy,
            }
        )


def test_profile_is_closed_and_legacy_meaning_is_not_relaxed():
    from awm_adm.sources.models import Projection

    with pytest.raises(ValueError):
        Projection.model_validate(catalog())
    with pytest.raises(ValueError):
        Catalog.model_validate({**catalog(), "unvalidated": True})
    for i in range(3):
        f = Extracted.model_validate(fact(i)).model_dump()
        assert resolve(catalog(), f) == ([f["temporal_scope"]], None)


def test_semantic_conflicts_ignore_source_partition_and_catalog_growth():
    p = catalog()
    a = with_identity(fact())
    b = deepcopy(a)
    b["source"]["item_id"] = "other"
    b["value"]["value"] = 8
    s = p["predicates"][0]
    assert address(a, s) == address(b, s)
    assert relation(a, s, b, s) == "same"
    b["temporal_scope"]["timezone_basis"] = "America/New_York"
    assert address(a, s) == address(b, s)
    b["temporal_scope"]["effective_from"] = "2026-03-02T12:00:00Z"
    assert relation(a, s, b, s) == "distinct"


def test_precision_and_period_semantics_are_not_interchangeable():
    a = with_identity(fact(1))
    b = deepcopy(a)
    b["temporal_scope"] = cell(start="2026-03-02T12:00:00Z")
    s = catalog()["predicates"][1]
    assert relation(a, s, b, s) == "overlap"
    b["temporal_scope"] = cell(start="2026-03-08T00:00:00Z")
    assert relation(a, s, b, s) == "distinct"  # right boundary is excluded
    b["temporal_scope"] = cell("period_value", "2026-03-01T00:00:00Z", "2026-03-08T00:00:00Z")
    assert relation(a, s, b, s) == "distinct"
    a = with_identity(
        {
            **fact(),
            "temporal_scope": cell(
                "occurrence", "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z", precision="day"
            ),
        }
    )
    b = deepcopy(a)
    b["source"]["item_id"] = "second"
    assert relation(a, s, b, s) == "uncertain"
    assert address(a, s) != address(b, s)


@pytest.mark.parametrize(
    "change",
    [
        {"effective_from": "2026-02-30T00:00:00Z"},
        {"effective_from": "2026-03-01T12:00:00.1Z"},
        {"effective_to": "2026-03-01T12:00:01Z"},
        {"precision": "day"},
        {"timezone_basis": "Invalid/Zone"},
    ],
)
def test_invalid_exact_scope(change):
    with pytest.raises(ValueError):
        Scope.model_validate({**cell(), **change})


def test_dst_windows_and_unknown_clocks():
    start, end = day_bounds("2026-03-08", "America/New_York")
    assert (start, end) == ("2026-03-08T05:00:00Z", "2026-03-09T04:00:00Z")
    Scope.model_validate(cell("occurrence", start, end, precision="day", timezone_basis="America/New_York"))
    assert Anchor().model_dump()["kind"] == "unknown"
    with pytest.raises(ValueError):
        Anchor(kind="unknown", effective_from=start)


def test_descriptor_requires_explicit_period_and_report_meanings():
    for field, value in (("metric", None), ("actor", "someone")):
        p = catalog()
        p["predicates"][2][field] = value
        with pytest.raises(ValueError):
            Catalog.model_validate(p)
    p = catalog()
    p["cells"].append({**p["cells"][0], "timezone_basis": "America/New_York"})
    with pytest.raises(ValueError):
        Catalog.model_validate(p)
    a = catalog()
    b = deepcopy(a)
    b["cells"].reverse()
    assert {scope_key(s) for s in a["cells"]} == {scope_key(s) for s in b["cells"]}
    assert encode(a) != encode(b)  # transport preserves order; identity does not depend on it


def test_cumulative_catalog_limit_does_not_reinterpret_valid_larger_legacy_scope():
    from awm_adm.temporal_evidence.legacy import extend, view

    from .test_sources import profile

    old = profile()
    old["entities"] = [f"entity{i}" for i in range(128)]
    old["predicates"] = [{**old["predicates"][0], "symbol": f"p.value{i}"} for i in range(32)]
    # Legacy validation remains valid above the new Cartesian cap.
    from awm_adm.sources.models import Projection

    Projection.model_validate(old)
    before = encode(old)
    assert len(view(old)["entities"]) == 128
    with pytest.raises(ValueError, match="4096"):
        extend(old, view(old))
    assert encode(old) == before


def test_temporal_preparation_schema_is_published_and_has_no_model_branch():
    import json
    from pathlib import Path

    from awm_adm.teaching.prompt import specification
    from awm_adm.teaching.provider_format import response_schema

    actual = response_schema(temporal_evidence=True)
    assert json.loads(Path("contracts/teaching-temporal-reply.schema.json").read_text()) == actual
    task = {"objective": "Learn supplied evidence", "inputs": [], "material_manifest": {"entries": []}}
    a = specification(task, {}, {}, None)
    b = specification({**task, "provider_model": "another-provider-choice"}, {}, {}, None)
    # Capture the same default for the comparison; no model-specific semantic/schema changes.
    a["context"]["temporal_context"] = b["context"]["temporal_context"]
    assert a == b and a["prompt_version"] == "adm-teaching-preparation/18"


def test_calendar_window_resolves_default_zone_and_preserves_intent():
    import json

    from awm_adm.temporal_evidence.conversation import parse

    from .interaction_support import proposal

    q = {
        "op": "query_evidence",
        "intent": "observations_in",
        "entity_id": "chamber",
        "predicate": "chamber.reading",
        "scope": {"kind": "occurrence", "effective_on": "2026-03-08", "timezone": None},
    }
    parsed = parse(
        proposal("query evidence with " + json.dumps(q)),
        catalog(),
        [],
        {"system_timezone": "America/New_York"},
    )
    assert parsed["query"]["intent"] == "observations_in"
    assert parsed["query"]["scope"] == cell(
        "occurrence",
        "2026-03-08T05:00:00Z",
        "2026-03-09T04:00:00Z",
        precision="day",
        timezone_basis="America/New_York",
    )
