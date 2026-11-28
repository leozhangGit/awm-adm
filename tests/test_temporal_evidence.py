"""Mixed temporal evidence through the real bounded service, without remote calls."""

# ruff: noqa: F811

from copy import deepcopy
from uuid import uuid4

import pytest

from awm_adm.runtime.protocol import unpack, unpack_core
from awm_adm.temporal_evidence.legacy import extend, view

from .temporal_support import catalog, cell, fact
from .test_application import app_runtime, execute  # noqa: F401
from .test_sources import ingest, install, project


def ask(rt, key, index=0, intent=None, scope=None, **kw):
    p = catalog()
    q = {
        "op": "query_evidence",
        "intent": intent or ["value_at", "value_throughout", "value_for_period"][index],
        "entity_id": p["entities"][index],
        "predicate": p["predicates"][index]["symbol"],
        "scope": scope or p["cells"][index],
        **kw,
    }
    rt.coordinator.submit(key, {"idempotency_key": str(uuid4()), "query": q})
    return execute(rt, key)


def test_mixed_query_roundtrip_and_no_temporal_coercion(app_runtime):
    rt = app_runtime
    key = rt.create("Mixed synthetic evidence")["instance_id"]
    install(rt, key, projection=catalog())
    assert project(rt, key, ingest(rt, key, [fact(i) for i in range(3)]))["status"] == "accepted"
    for i, v in enumerate((7, 3, 14)):
        result = ask(rt, key, i)
        assert result["status"] == "succeeded", result
        assert result["result"]["value"]["value"] == v
        assert result["result"]["value"]["value_metadata"]["unit"] == catalog()["predicates"][i]["unit"]
    assert (
        ask(rt, key, 0, "value_throughout", cell("validity", "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z"))[
            "status"
        ]
        == "needs_input"
    )
    assert ask(rt, key, 2, "value_at", cell())["status"] == "needs_input"
    snapshot = rt.store.snapshot(key)
    assert snapshot["profile"] == "awm-adm-service-snapshot/1"
    with pytest.raises(ValueError):
        unpack_core(snapshot)
    with pytest.raises(ValueError, match="envelope"):
        unpack(snapshot["core"])
    copy = rt.create("Independent copy", snapshot=snapshot)["instance_id"]
    assert copy != key
    assert ask(rt, copy, 2)["result"]["value"]["value"] == 14
    assert rt.learning.usage()["calls"] == 0


def test_temporal_exact_revision_modes_and_source_correction(app_runtime):
    rt = app_runtime
    key = rt.create("Temporal changes")["instance_id"]
    install(rt, key, projection=catalog())
    first = ingest(rt, key, [fact(2)], item="history")
    assert project(rt, key, first)["status"] == "accepted"
    old = rt.store.info(key)["theory_version"]
    assert project(rt, key, ingest(rt, key, [fact(2, 15)]))["status"] == "rejected"
    assert rt.store.info(key)["theory_version"] == old
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    assert project(rt, key, ingest(rt, key, [fact(2, 15)], item="revision"))["status"] == "accepted"
    assert ask(rt, key, 2)["result"]["value"]["value"] == 15
    ingest(rt, key, [fact(2, 16)], item="revision", version_id="v2", supersedes_version="v1")
    assert ask(rt, key, 2)["status"] == "needs_input"


def test_legacy_upgrade_preserves_bytes_and_exact_identity(app_runtime):
    from .test_sources import fact as old_fact
    from .test_sources import lookup
    from .test_sources import profile as old_profile

    rt = app_runtime
    key = rt.create("Legacy coexistence")["instance_id"]
    install(rt, key)
    assert project(rt, key, ingest(rt, key, [old_fact()]))["status"] == "accepted"
    before = rt.store.snapshot(key)
    old_query = lookup(rt, key, 2022)
    new = catalog()
    new["namespace"] = "history"
    merged = extend(old_profile(), new)
    rt.sources.coverage(
        key,
        {
            "expected_revision": rt.store.info(key)["revision_id"],
            "expected_generation": rt.sources.policy(key)["generation"],
            "kind": "extend",
            "projection": merged,
            "reason": "Additional independent temporal meanings",
        },
    )
    after = rt.store.snapshot(key)
    assert all(after["files"].get(k) == v for k, v in before["files"].items())
    assert lookup(rt, key, 2022)["result"]["value"]["value"] == old_query["result"]["value"]["value"] == 10
    assert project(rt, key, ingest(rt, key, [fact(2)]))["status"] == "accepted"
    assert lookup(rt, key, 2022)["result"]["value"]["value"] == 10
    assert ask(rt, key, 2)["result"]["value"]["value"] == 14
    # New exact evidence replaces the old cell only under forward admission, retaining its symbol.
    old_view = view(old_profile())
    scope = deepcopy(old_view["cells"][0])
    scope.update(precision="second", timezone_basis="UTC")
    f = {**old_fact(11), "temporal_scope": scope}
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    assert project(rt, key, ingest(rt, key, [f]))["status"] == "accepted"
    rt.coordinator.submit(
        key,
        {
            "idempotency_key": str(uuid4()),
            "query": {
                "op": "query_evidence",
                "intent": "value_throughout",
                "entity_id": "site",
                "predicate": "site.capacity",
                "scope": scope,
            },
        },
    )
    assert execute(rt, key)["result"]["value"]["value"] == 11


def test_overlap_cannot_bypass_backward_or_erase_forward_remainder(app_runtime):
    from .test_sources import finish, job

    rt = app_runtime
    key = rt.create("Overlap")["instance_id"]
    install(rt, key, projection=catalog())
    assert project(rt, key, ingest(rt, key, [fact(1)]))["status"] == "accepted"
    overlap = {**fact(1, 4), "temporal_scope": cell()}
    assert project(rt, key, ingest(rt, key, [overlap]))["status"] == "rejected"
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    source = ingest(rt, key, [overlap])
    ex = finish(rt, key, job(rt, key, source))
    episode = rt.sources.create_projection(
        key,
        {
            "idempotency_key": str(uuid4()),
            "expected_revision": rt.store.info(key)["revision_id"],
            "expected_generation": rt.sources.policy(key)["generation"],
            "claim_ids": [c["claim"]["claim_id"] for c in ex["result"]["claims"]],
        },
    )
    result = finish(rt, key, episode, "source_episodes")
    assert result["status"] in ("failed", "needs_specification"), result
    assert ask(rt, key, 1)["result"]["value"]["value"] == 3


def test_uncertain_occurrence_collection_paging_and_revision_bound_cursor(app_runtime):
    rt = app_runtime
    key = rt.create("Uncertain occurrences")["instance_id"]
    p = catalog()
    window = cell("occurrence", "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z", precision="day")
    p["cells"].append(window)
    install(rt, key, projection=p)
    for value in (7, 9):
        f = {**fact(0, value), "temporal_scope": window}
        assert project(rt, key, ingest(rt, key, [f]))["status"] == "accepted"
    assert ask(rt, key, 0)["status"] == "needs_input"
    first = ask(rt, key, 0, "observations_in", window, limit=1)
    result = first["result"]["value"]
    assert len(result["items"]) == 1 and result["scope"]["complete"] is False
    cursor = result["scope"]["next_cursor"]
    second = ask(rt, key, 0, "observations_in", window, limit=1, cursor=cursor)["result"]["value"]
    assert {result["items"][0]["value"], second["items"][0]["value"]} == {7, 9}
    assert second["scope"]["enumeration_complete"] is True
    assert second["scope"]["complete"] is False
    rt.store.change(key, rt.store.info(key)["policy_epoch"], mode="forward")
    assert ask(rt, key, 0, "observations_in", window, limit=1, cursor=cursor)["status"] != "succeeded"


def test_attributed_period_reports_keep_target_and_reporting_time_separate(app_runtime):
    rt = app_runtime
    key = rt.create("Reported plans")["instance_id"]
    p = catalog()
    p["predicates"][2].update(statement_level="reported", actor="Fixture planner", modality="forecast")
    install(rt, key, projection=p)
    for day, value in ((1, 14), (2, 16)):
        f = {
            **fact(2, value),
            "reported_time": {
                "kind": "exact",
                "effective_from": f"2026-02-0{day}T12:00:00Z",
                "effective_to": None,
                "precision": "second",
                "timezone_basis": "UTC",
            },
        }
        assert project(rt, key, ingest(rt, key, [f]))["status"] == "accepted"
    assert ask(rt, key, 2)["status"] == "needs_input"
    answer = ask(
        rt,
        key,
        2,
        reported_time={
            "kind": "exact",
            "effective_from": "2026-02-02T12:00:00Z",
            "effective_to": None,
            "precision": "second",
            "timezone_basis": "UTC",
        },
    )["result"]["value"]
    assert answer["value"] == 16
    assert answer["value_metadata"]["statement_level"] == "reported"
    reports = ask(rt, key, 2, "reports_about")["result"]["value"]
    assert len(reports["items"]) == 2 and reports["scope"]["complete"] is True


def test_source_revision_preserves_dependent_body_and_correction_holds_native_queries(app_runtime):
    from awm_adm.engine import Instance, build_candidate
    from awm_adm.runtime.protocol import pack
    from awm_adm.sources.compute import evidence

    rt = app_runtime
    key = rt.create("Dependency source")["instance_id"]
    install(rt, key, projection=catalog())
    accepted = project(rt, key, ingest(rt, key, [fact()]))
    symbol = next(iter(accepted["result"]["cells"]))
    inst = Instance.restore(unpack(rt.store.snapshot(key)), mode="forward")
    body = {
        "kind": "function",
        "params": {},
        "returns": {"kind": "bool"},
        "body": {
            "op": "le",
            "args": [
                {"op": "call", "function": symbol, "args": {}},
                {"op": "literal", "value": 10, "type": {"kind": "int", "min": 0, "max": 20}},
            ],
        },
    }
    candidate = build_candidate(
        inst._model,
        {"derived.low": body},
        candidate_id="dependent-fixture",
        evidence=[evidence({"synthetic": True})],
    )
    inst.receive(candidate, review_required=False)
    assert inst.decide_next()["status"] == "accepted"
    copy = rt.create("Dependent model", mode="forward", snapshot=pack(inst.export_snapshot()))["instance_id"]
    install(rt, copy, projection=catalog())
    assert project(rt, copy, ingest(rt, copy, [fact(0, 12)], item="new-observation"))["status"] == "accepted"
    query = {
        "op": "evaluate",
        "module": "derived",
        "expression": {"op": "call", "function": "derived.low", "args": {}},
    }
    value = rt.query(copy, query)
    assert value["result"]["value"] is False
    from awm_adm.engine import validate_snapshot

    checked = validate_snapshot(unpack(rt.store.snapshot(copy)))
    assert checked["model"].document()["declarations"]["derived.low"] == body
    ingest(rt, copy, [fact(0, 13)], item="new-observation", version_id="v2", supersedes_version="v1")
    assert rt.query(copy, query)["result"]["status"] == "needs_input"
    imported = rt.create("Held dependent copy", snapshot=rt.store.snapshot(copy))["instance_id"]
    assert rt.query(imported, query)["result"]["status"] == "needs_input"


@pytest.mark.parametrize("field", ["unit", "span", "bridge", "descriptor"])
def test_cold_import_refuses_semantically_forged_but_hash_consistent_evidence(app_runtime, field):
    from awm_adm.engine import Instance, validate_snapshot
    from awm_adm.engine.artifacts import digest
    from awm_adm.engine.data import encode, read_json, thaw
    from awm_adm.runtime.protocol import RuntimeFault, pack

    rt = app_runtime
    key = rt.create("Cold temporal integrity")["id"]
    install(rt, key, projection=catalog())
    assert project(rt, key, ingest(rt, key, [fact()]))["status"] == "accepted"
    instance = Instance.restore(unpack(rt.store.snapshot(key)))
    symbol, origin_key = next(iter(instance._support.items()))
    origin = thaw(read_json(instance._blobs[origin_key]))
    notes = [thaw(read_json(instance._blobs[k])) for k in origin["evidence"]]
    meta = next(e for e in notes if e["content"]["profile"] == "awm-adm-temporal-binding/1")
    if field == "unit":
        meta["content"]["claim"]["unit"] = "different-unit"
    elif field == "span":
        meta["content"]["claim"]["source"]["end_byte"] = 999999
    elif field == "bridge":
        meta["content"]["legacy_bridge"] = {"projection": {}, "cell": {}}
    else:
        meta["content"]["descriptor_digest"] = "sha256:" + "0" * 64
    origin["evidence"] = []
    for note in notes:
        key_hash = digest(encode(note))
        instance._blobs[key_hash] = encode(note)
        origin["evidence"].append(key_hash)
    origin_key = digest(encode(origin))
    instance._blobs[origin_key] = encode(origin)
    instance._support[symbol] = origin_key
    snapshot = instance.export_snapshot()
    validate_snapshot(snapshot)  # Core hashes are sound; semantic adapter must still refuse.
    before = rt.store.list()
    with pytest.raises((ValueError, RuntimeFault)):
        rt.create("Refuse malformed meaning", snapshot=pack(snapshot))
    assert [row for row in rt.store.list() if row["status"] == "ready"] == before
    assert rt.store.list()[-1]["status"] == "failed"


def test_temporal_replacement_cannot_override_independent_requirements(app_runtime):
    from .test_application import client
    from .test_instance import capacity_policy

    rt = app_runtime
    key = rt.create("Protected temporal meaning", mode="forward")["id"]
    install(rt, key, projection=catalog())
    accepted = project(rt, key, ingest(rt, key, [fact(0, 10)]))
    symbol = next(iter(accepted["result"]["cells"]))
    policy = capacity_policy()
    policy["contracts"][0]["required_symbols"] = [symbol]
    policy["contracts"][0]["checks"][0]["expression"]["function"] = symbol
    with client(rt) as http:
        response = http.put(
            f"/api/v1/adms/{key}/requirements",
            json={
                "expected_epoch": rt.store.info(key)["policy_epoch"],
                "policy": policy,
            },
        )
        assert response.status_code == 200, response.text
    before = rt.store.info(key)
    assert project(rt, key, ingest(rt, key, [fact(0, 11)]))["status"] == "rejected"
    assert rt.store.info(key) == before
    assert ask(rt, key)["result"]["value"]["value"] == 10


def test_schema_upgrade_changes_no_legacy_domain_rows_or_retained_results(app_runtime):
    from awm_adm.runtime.storage import migrate

    from .test_sources import lookup

    rt = app_runtime
    key = rt.create("Legacy migration fixture")["id"]
    install(rt, key)
    assert project(rt, key, ingest(rt, key))["status"] == "accepted"
    assert lookup(rt, key, 2021)["status"] == "succeeded"
    snapshot = rt.store.snapshot(key)
    with rt.store.db(key) as db:
        # 17 and 18 have identical domain tables. Recreate the supported migration input.
        db.execute("PRAGMA user_version=17")
        before = list(db.iterdump())
        migrate(db, "instance")
        assert db.execute("PRAGMA user_version").fetchone()[0] == 19
        assert list(db.iterdump()) == before
    assert rt.store.snapshot(key) == snapshot
