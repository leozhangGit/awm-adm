import json
from pathlib import Path
from unittest.mock import patch

import pytest

from awm_adm.engine import (
    Budget,
    Instance,
    SnapshotPackage,
    admit,
    read_snapshot,
    validate_snapshot,
    write_snapshot,
)
from awm_adm.engine.artifacts import digest
from awm_adm.engine.certificates import transition_table
from awm_adm.engine.data import encode, read_json, thaw
from awm_adm.engine.errors import ADMError, Conflict, InvalidIR, Rejected, ResourceLimit
from awm_adm.engine.snapshots import artifact_path

from .ported.helpers import fixture, integer
from .test_instance import capacity_policy, constant, evidence, publish, value_query

REFERENCE = Path(__file__).parent / "fixtures/v1/reference"


@pytest.mark.parametrize("domain,goal", [("access", "access.bob_access"), ("tanks", "tanks.four_litres")])
def test_exact_v1_golden_roots_artifact_bytes_and_table_encoding(domain, goal):
    golden = json.loads((REFERENCE / "golden.json").read_text())[domain]
    model = admit(fixture(domain)).model
    assert model.version == golden["theory_version"]
    assert model.index == golden["declarations"]
    assert {k: v.decode() for k, v in model.artifacts().items()} == golden["artifact_bytes"]
    table = transition_table(model, domain, goal)
    assert digest(encode(table)) == golden["table_digest"]
    table["states"].reverse()
    assert digest(encode(table)) != golden["table_digest"]


@pytest.mark.parametrize("name", ["empty", "access", "tanks", "learned-policy"])
def test_actual_v1_snapshots_rechecked_into_fresh_v2_instances(name):
    package = read_snapshot(REFERENCE / (name + ".adm"))
    assert read_json(package.manifest)["protocol"] == "adm/0.1"
    first = Instance.restore(package, mode="forward")
    second = Instance.restore(package, mode="backward")
    assert first.instance_id != second.instance_id
    assert first.model.version == second.model.version
    assert first.info()["receipt_sequence"] == 0
    new = first.export_snapshot()
    assert read_json(new.manifest)["protocol"] == "awm-adm/2"
    assert read_json(new.manifest)["format_version"] == "2.0"
    assert validate_snapshot(new)["model"].version == first.model.version
    assert first.lineage()[0]["package_id"] == package.package_id
    if name == "learned-policy":
        assert first.query(value_query())["value"] == 10
        before = first.context()
        assert publish(first, {"site.capacity": constant(12)})["status"] == "rejected"
        assert first.context() == before
        checked = validate_snapshot(new)
        origin = read_json(checked["blobs"][checked["support"]["site.capacity"]])
        assert origin["kind"] == "learning" and origin["candidate_id"] == "reference-learning"


def test_roundtrip_state_policy_and_independent_histories(tmp_path):
    source = Instance(mode="forward", policy=capacity_policy())
    publish(source, {"site.capacity": constant(10)}, "first")
    package = source.export_snapshot(state={"type": integer(0, 10), "value": 4})
    path = tmp_path / "model.adm"
    write_snapshot(package, path)
    restored = Instance.restore(read_snapshot(path), mode="backward")
    assert restored.initial_state()["value"] == 4
    assert restored.conformance() == source.conformance()
    assert restored.info()["receipt_sequence"] == 0
    publish(restored, {"other.local": constant(7)}, "own")
    assert "other.local" not in source.model.index
    with pytest.raises(InvalidIR):
        restored.export_snapshot(state=restored.initial_state())
    assert validate_snapshot(restored.export_snapshot())["state"] is None
    with pytest.raises(Conflict):
        write_snapshot(package, path)


def test_dormant_and_empty_v02_profiles_preserved():
    dormant = Instance(policy=capacity_policy())
    restored = Instance.restore(dormant.export_snapshot())
    assert publish(restored, {"site.capacity": constant(11)})["status"] == "rejected"
    empty = Instance(policy={"profile": "adm-conformance/0.2", "contracts": []})
    package = empty.export_snapshot()
    manifest = thaw(read_json(package.manifest))
    assert "adm-conformance/0.2" in manifest["required_profiles"]
    assert Instance.restore(package).conformance()["policy"]["profile"] == "adm-conformance/0.2"
    manifest["required_profiles"][-1] = "adm-conformance/0.1"
    with pytest.raises(ADMError):
        Instance.restore(SnapshotPackage(encode(manifest), package.files))
    manifest = thaw(read_json(package.manifest))
    del manifest["conformance_root"]
    with pytest.raises(InvalidIR):
        Instance.restore(SnapshotPackage(encode(manifest), package.files))


def replace_artifact(package, key, new_value):
    manifest = thaw(read_json(package.manifest))
    files = dict(package.files)
    raw = encode(new_value)
    new_key = digest(raw)
    files.pop(artifact_path(key))
    files[artifact_path(new_key)] = raw
    for item in manifest["files"]:
        if item["digest"] == key:
            item.update(path=artifact_path(new_key), digest=new_key, bytes=len(raw))
    for field in ("state_root", "conformance_root", "provenance_root", "admission_root"):
        if manifest.get(field) == key:
            manifest[field] = new_key
    return SnapshotPackage(encode(manifest), files)


def test_recomputed_state_and_policy_digests_cannot_bypass_semantic_recheck():
    source = Instance(
        {"profile": "finite-v0", "declarations": {"site.capacity": constant(10)}}, policy=capacity_policy()
    )
    package = source.export_snapshot(state={"type": integer(0, 10), "value": 4})
    m = read_json(package.manifest)
    bad_state = {
        "artifact_kind": "state",
        "theory_version": source.model.version,
        "type": integer(0, 10),
        "value": 11,
    }
    with pytest.raises(ADMError):
        Instance.restore(replace_artifact(package, m["state_root"], bad_state))
    with pytest.raises(Rejected):
        Instance.restore(replace_artifact(package, m["conformance_root"], capacity_policy(11)))


def test_missing_evidence_tampered_bytes_unknown_profiles_and_imported_proofs_fail():
    package = read_snapshot(REFERENCE / "learned-policy.adm")
    manifest = thaw(read_json(package.manifest))
    evidence_entry = next(x for x in manifest["files"] if x["role"] == "evidence")
    files = dict(package.files)
    files.pop(evidence_entry["path"])
    with pytest.raises(ADMError):
        Instance.restore(SnapshotPackage(package.manifest, files))
    files = dict(package.files)
    files[evidence_entry["path"]] += b" "
    with pytest.raises(ADMError):
        Instance.restore(SnapshotPackage(package.manifest, files))
    for field, value in [
        ("required_profiles", ["unknown/1"]),
        ("proof_status", "lean_kernel"),
        ("format_version", "99"),
    ]:
        with pytest.raises(ADMError):
            Instance.restore(SnapshotPackage(encode({**manifest, field: value}), package.files))


def test_export_uses_one_pinned_model_support_pair_during_learning():
    source = Instance(mode="forward")
    publish(source, {"site.capacity": constant(10)}, "first")
    before = source.context()
    from awm_adm.engine import snapshots

    original = snapshots.export_instance

    def during(pinned, **options):
        publish(source, {"site.capacity": constant(12)}, "second")
        return original(pinned, **options)

    with patch.object(snapshots, "export_instance", side_effect=during):
        package = source.export_snapshot()
    assert validate_snapshot(package)["model"].version == before["theory_version"]
    assert source.model.version != before["theory_version"]
    assert Instance.restore(package).query(value_query())["value"] == 10


def test_exhaustion_never_returns_partial_snapshot_or_archive(tmp_path):
    source = Instance(fixture("tanks"))
    package = source.export_snapshot()
    with pytest.raises(ResourceLimit):
        source.export_snapshot(budget=Budget(max_work=1))
    with pytest.raises(ResourceLimit):
        Instance.restore(package, budget=Budget(max_work=1))
    path = tmp_path / "partial.adm"
    with pytest.raises(ResourceLimit):
        write_snapshot(package, path, budget=Budget(max_work=1))
    assert not path.exists()


def test_reexport_is_deterministic_and_contains_no_live_authority():
    source = Instance(mode="forward")
    publish(source, {"site.capacity": constant(10)}, "first", records=[evidence()])
    source.query(value_query())
    first, second = source.export_snapshot(), source.export_snapshot()
    assert first.manifest == second.manifest and first.files == second.files
    m = read_json(first.manifest)
    assert set(x["role"] for x in m["files"]) <= {
        "theory",
        "declaration",
        "evidence",
        "admission",
        "provenance",
        "state",
        "conformance",
    }
    restored = Instance.restore(first)
    assert restored._receipts == {} and restored._results == {}


def test_restored_baseline_precedes_new_receipts_in_both_modes():
    source = Instance(mode="forward")
    publish(source, {"site.capacity": constant(10)}, "source-first")
    package = source.export_snapshot()
    for mode, expected, status in (("forward", 12, "accepted"), ("backward", 10, "rejected")):
        clone = Instance.restore(package, mode=mode)
        decision = publish(clone, {"site.capacity": constant(12)}, "local-first")
        assert decision["receipt_sequence"] == 1
        assert decision["status"] == status
        assert clone.query(value_query())["value"] == expected
    assert source.query(value_query())["value"] == 10
