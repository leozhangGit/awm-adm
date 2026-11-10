"""Portable accepted models, checked offline and published without partial destinations."""

import io
import os
import stat
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .artifacts import digest
from .budget import Budget
from .candidates import hash_id, portable_path
from .conformance import EMPTY_POLICY, verify_policy
from .conformance import SUPPORTED_PROFILES as CONFORMANCE_PROFILES
from .data import MAX_BYTES, encode, name, read_json, shape, thaw
from .errors import Conflict, InvalidIR, Rejected, ResourceLimit, StorageError, UnsupportedFeature
from .model import CHECKER, PROFILE, admit
from .requests import identifier

MAX_SNAPSHOT_BYTES = 32_000_000
MAX_ARCHIVE_BYTES = 34_000_000
MAX_FILES = 4096
MAX_LINEAGE = 64
ROLES = {"theory", "declaration", "evidence", "state", "provenance", "admission", "conformance"}


@dataclass(frozen=True)
class SnapshotPackage:
    manifest: bytes
    files: Mapping[str, bytes]

    def __post_init__(self):
        if not isinstance(self.files, Mapping):
            raise InvalidIR("Snapshot files must map paths to exact bytes")
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))

    @property
    def package_id(self):
        return digest(self.manifest)


def artifact_path(key):
    return "artifacts/" + hash_id(key).split(":", 1)[1] + ".json"


def unpack_snapshot(package, budget):
    if not isinstance(package, SnapshotPackage) or type(package.manifest) is not bytes:
        raise InvalidIR("Expected a SnapshotPackage with exact manifest bytes")
    manifest = thaw(read_json(package.manifest))
    shape(
        manifest,
        (
            "protocol",
            "kind",
            "format_version",
            "profile",
            "source_instance_id",
            "source_theory_version",
            "theory_root",
            "required_profiles",
            "state_root",
            "provenance_root",
            "admission_root",
            "files",
        ),
        ("conformance_root",),
    )
    if (manifest["protocol"], manifest["kind"], manifest["format_version"], manifest["profile"]) not in (
        ("adm/0.1", "snapshot_manifest", "0.1", "model"),
        ("awm-adm/2", "snapshot_manifest", "2.0", "model"),
    ):
        raise UnsupportedFeature("Unsupported snapshot format or profile")
    profiles = manifest["required_profiles"]
    if manifest["protocol"] == "awm-adm/2" and "conformance_root" not in manifest:
        raise InvalidIR("AWM-ADM model snapshots require an explicit conformance policy profile")
    expected_profiles = [PROFILE, CHECKER]
    if "conformance_root" in manifest:
        hash_id(manifest["conformance_root"])
        selected = [p for p in CONFORMANCE_PROFILES if isinstance(profiles, list) and p in profiles]
        if len(selected) != 1:
            raise UnsupportedFeature("Snapshot requires one supported conformance profile")
        expected_profiles.extend(selected)
    if not isinstance(profiles, list) or sorted(profiles, key=str) != sorted(expected_profiles):
        raise UnsupportedFeature("Snapshot requires unsupported execution/checker profiles")
    identifier(manifest["source_instance_id"])
    for field in ("source_theory_version", "theory_root", "provenance_root", "admission_root"):
        hash_id(manifest[field])
    if manifest["state_root"] is not None:
        hash_id(manifest["state_root"])
    if manifest["source_theory_version"] != manifest["theory_root"]:
        raise InvalidIR("Snapshot theory identity differs from its root")
    if not isinstance(manifest["files"], list) or not 1 <= len(manifest["files"]) <= MAX_FILES:
        raise ResourceLimit("Invalid snapshot file count")
    if not isinstance(package.files, Mapping):
        raise InvalidIR("Snapshot files must map paths to exact bytes")
    blobs, roles, paths, total = {}, {}, set(), len(package.manifest)
    for entry in manifest["files"]:
        budget.tick()
        shape(entry, ("path", "digest", "bytes", "role"))
        key = hash_id(entry["digest"])
        path = portable_path(entry["path"])
        if path != artifact_path(key) or path in paths or key in blobs:
            raise InvalidIR("Snapshot requires unique content-addressed file paths")
        if not isinstance(entry["role"], str) or entry["role"] not in ROLES:
            raise UnsupportedFeature("Unsupported snapshot artifact role")
        data = package.files.get(path)
        if type(data) is not bytes or type(entry["bytes"]) is not int or len(data) != entry["bytes"]:
            raise InvalidIR("Missing snapshot file or incorrect byte count", path=path)
        if len(data) > MAX_BYTES or digest(data) != key:
            raise InvalidIR("Snapshot file size or digest mismatch", path=path)
        total += len(data)
        if total > MAX_SNAPSHOT_BYTES:
            raise ResourceLimit("Snapshot exceeds 32 MB")
        paths.add(path)
        blobs[key], roles[key] = data, entry["role"]
    if paths != set(package.files):
        raise InvalidIR("Unlisted snapshot file")
    return manifest, blobs, roles


def validate_snapshot(package, *, budget=None):
    """Rebuild the exact kernel closure and re-admit it; source reports are not authority."""
    budget = budget if budget is not None else Budget()
    manifest, blobs, roles = unpack_snapshot(package, budget)
    used = set()

    def take(key, role):
        budget.tick()
        hash_id(key)
        if roles.get(key) != role:
            raise InvalidIR("Missing snapshot dependency or incorrect role", artifact=key, role=role)
        used.add(key)
        return thaw(read_json(blobs[key]))

    root = take(manifest["theory_root"], "theory")
    shape(root, ("profile", "declarations", "checker"))
    if root["profile"] != PROFILE or root["checker"] != CHECKER:
        raise UnsupportedFeature("Unsupported theory/checker identity")
    if not isinstance(root["declarations"], dict):
        raise InvalidIR("Theory declarations must be an index")
    declarations = {}
    for symbol, key in root["declarations"].items():
        name(symbol, qualified=True)
        item = take(key, "declaration")
        shape(item, ("profile", "symbol", "declaration", "dependencies"))
        if item["profile"] != PROFILE or item["symbol"] != symbol:
            raise InvalidIR("Snapshot declaration metadata mismatch")
        declarations[symbol] = item["declaration"]
    admission = admit({"profile": PROFILE, "declarations": declarations}, budget=budget)
    if admission.model is None:
        error = ResourceLimit if admission.status == "inconclusive" else Rejected
        raise error("Snapshot model failed local admission", report=admission.report)
    model = admission.model
    if model.version != manifest["theory_root"]:
        raise InvalidIR("Snapshot root or dependency hashes differ from the checked model")
    for key, data in model.artifacts().items():
        if blobs.get(key) != data:
            raise InvalidIR("Snapshot lacks the exact checked declaration closure")

    def check_report(key):
        report = take(key, "admission")
        shape(report, ("artifact_kind", "theory_version", "report"))
        hash_id(report["theory_version"])
        if report["artifact_kind"] != "admission" or not isinstance(report["report"], dict):
            raise InvalidIR("Invalid source admission record")
        if (
            report["report"].get("checker") != CHECKER
            or report["report"].get("guarantee") != "exhaustive_finite"
        ):
            raise UnsupportedFeature("Unsupported source admission report")
        return report

    if check_report(manifest["admission_root"])["theory_version"] != model.version:
        raise InvalidIR("Source admission report refers to a different theory")
    provenance = take(manifest["provenance_root"], "provenance")
    shape(provenance, ("artifact_kind", "theory_version", "declarations", "lineage"))
    if provenance["artifact_kind"] != "snapshot_provenance" or provenance["theory_version"] != model.version:
        raise InvalidIR("Provenance belongs to a different theory")
    support = provenance["declarations"]
    if not isinstance(support, dict) or set(support) != set(model.index):
        raise InvalidIR("Snapshot lacks provenance for its complete declaration set")
    lineage = provenance["lineage"]
    if not isinstance(lineage, list) or len(lineage) > MAX_LINEAGE:
        raise ResourceLimit("Snapshot lineage exceeds its bound")
    for entry in lineage:
        shape(entry, ("package_id", "source_instance_id", "source_theory_version"))
        hash_id(entry["package_id"])
        identifier(entry["source_instance_id"])
        hash_id(entry["source_theory_version"])
    for symbol, key in support.items():
        origin = take(key, "provenance")
        if not isinstance(origin, dict):
            raise InvalidIR("Declaration provenance must be an object")
        fields = ("artifact_kind", "kind", "declaration", "source_instance_id", "admission", "evidence")
        if origin.get("kind") == "learning":
            fields += ("candidate_id", "receipt_sequence", "mode", "policy_epoch")
            identifier(origin.get("candidate_id"))
            if origin.get("mode") not in ("forward", "backward"):
                raise InvalidIR("Invalid source conflict mode")
            for field, minimum in (("receipt_sequence", 1), ("policy_epoch", 0)):
                if type(origin.get(field)) is not int or origin[field] < minimum:
                    raise InvalidIR("Invalid source conflict metadata")
        elif origin.get("kind") != "authored":
            raise InvalidIR("Unsupported declaration provenance")
        shape(origin, fields)
        if origin["artifact_kind"] != "origin" or origin["declaration"] != model.index[symbol]:
            raise InvalidIR("Provenance refers to a different declaration")
        identifier(origin["source_instance_id"])
        check_report(origin["admission"])
        evidence = origin["evidence"]
        if not isinstance(evidence, list) or (origin["kind"] == "learning" and not evidence):
            raise InvalidIR("Learned declarations require evidence provenance")
        for evidence_key in evidence:
            item = take(evidence_key, "evidence")
            shape(item, ("artifact_kind", "evidence_kind", "origin", "scope", "content"), ("checks",))
            if item["artifact_kind"] != "evidence" or item["evidence_kind"] not in (
                "synthetic_fixture",
                "provider_statement",
                "observation",
            ):
                raise InvalidIR("Unsupported evidence provenance")
            if any(not isinstance(item[k], str) or not item[k] for k in ("origin", "scope")):
                raise InvalidIR("Evidence must identify its origin and scope")
            if not isinstance(item.get("checks", []), list):
                raise InvalidIR("Evidence checks must be an array")
            for check in item.get("checks", []):
                shape(check, ("expression", "expected"))
            # Historical cases describe their source admission, not new observations.
    conformance = (
        take(manifest["conformance_root"], "conformance") if "conformance_root" in manifest else EMPTY_POLICY
    )
    if "conformance_root" in manifest and conformance.get("profile") not in manifest["required_profiles"]:
        raise UnsupportedFeature("Snapshot conformance profile differs from its manifest")
    conformance_report = verify_policy(conformance, model, budget=budget)
    state = None
    if manifest["state_root"] is not None:
        state = take(manifest["state_root"], "state")
        shape(state, ("artifact_kind", "theory_version", "type", "value"))
        if state["artifact_kind"] != "state" or state["theory_version"] != model.version:
            raise InvalidIR("Snapshot state belongs to a different theory")
        model.validate_value(state["type"], state["value"], budget=budget)
    if used != set(blobs):
        raise InvalidIR("Snapshot contains artifacts outside its required closure")
    budget.tick()
    return {
        "model": model,
        "manifest": manifest,
        "blobs": blobs,
        "support": support,
        "lineage": lineage,
        "state": state,
        "package_id": package.package_id,
        "conformance": conformance,
        "conformance_report": conformance_report,
    }


def export_instance(pinned, *, state=None, budget=None):
    """Package one atomically captured model/support view; no operational authority."""
    budget = budget if budget is not None else Budget()
    model = pinned["model"]
    blobs, roles = {}, {}
    total = 0

    def add(data, role):
        nonlocal total
        budget.tick()
        key = digest(data)
        if key not in blobs:
            total += len(data)
        if key in roles and roles[key] != role:
            raise InvalidIR("Snapshot artifact has inconsistent roles")
        blobs[key], roles[key] = data, role
        if len(blobs) > MAX_FILES or total > MAX_SNAPSHOT_BYTES:
            raise ResourceLimit("Snapshot closure exceeds limits")
        return key

    def take(key, role):
        data = pinned["blobs"].get(key)
        if data is None or digest(data) != key:
            raise StorageError("Missing or corrupt snapshot support", artifact=key)
        add(data, role)
        return thaw(read_json(data))

    take(model.version, "theory")
    for key in model.index.values():
        take(key, "declaration")
    if set(pinned["support"]) != set(model.index):
        raise StorageError("Snapshot support does not cover the pinned theory")
    for symbol, key in pinned["support"].items():
        origin = take(key, "provenance")
        if origin["declaration"] != model.index[symbol]:
            raise StorageError("Snapshot origin differs from pinned declaration")
        take(origin["admission"], "admission")
        for key in origin["evidence"]:
            take(key, "evidence")
    report_key = add(
        encode({"artifact_kind": "admission", "theory_version": model.version, "report": model.report}),
        "admission",
    )
    provenance_key = add(
        encode(
            {
                "artifact_kind": "snapshot_provenance",
                "theory_version": model.version,
                "declarations": pinned["support"],
                "lineage": pinned["lineage"],
            }
        ),
        "provenance",
    )
    state_key = None
    if state is not None:
        state = thaw(read_json(state))
        shape(state, ("type", "value"), ("theory_version", "artifact_kind"))
        if (
            state.get("theory_version", model.version) != model.version
            or state.get("artifact_kind", "state") != "state"
        ):
            raise InvalidIR("Snapshot state has a different interpretation")
        state_key = add(
            encode(
                {
                    "artifact_kind": "state",
                    "theory_version": model.version,
                    "type": state["type"],
                    "value": state["value"],
                }
            ),
            "state",
        )
    policy = thaw(read_json(pinned["policy"]))
    # Always carry the actual policy profile, including empty/dormant policies.
    policy_key = add(pinned["policy"], "conformance")
    manifest = {
        "protocol": "awm-adm/2",
        "kind": "snapshot_manifest",
        "format_version": "2.0",
        "profile": "model",
        "source_instance_id": pinned["instance_id"],
        "source_theory_version": model.version,
        "theory_root": model.version,
        "required_profiles": [PROFILE, CHECKER, policy["profile"]],
        "state_root": state_key,
        "provenance_root": provenance_key,
        "admission_root": report_key,
        "conformance_root": policy_key,
        "files": [
            {"path": artifact_path(key), "digest": key, "bytes": len(data), "role": roles[key]}
            for key, data in sorted(blobs.items())
        ],
    }
    package = SnapshotPackage(encode(manifest), {artifact_path(k): v for k, v in blobs.items()})
    validate_snapshot(package, budget=budget)
    return package


def publish_file(staged, destination):
    """Atomically link a complete file into a fresh destination; never overwrite."""
    try:
        os.link(staged, destination)
    except FileExistsError:
        raise Conflict("Destination already exists", path=str(destination)) from None
    except OSError:
        raise StorageError("Cannot publish snapshot or restored instance") from None


def write_snapshot(package, path, *, budget=None):
    budget = budget if budget is not None else Budget()
    validate_snapshot(package, budget=budget)
    destination = Path(path).absolute()
    with tempfile.TemporaryDirectory(prefix=".adm-export-", dir=destination.parent) as folder:
        staged = Path(folder) / "snapshot.adm"
        with staged.open("xb") as stream:
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
                for filename, data in [("manifest.json", package.manifest), *sorted(package.files.items())]:
                    budget.tick()
                    entry = zipfile.ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0))
                    entry.create_system = 3
                    entry.external_attr = (stat.S_IFREG | 0o600) << 16
                    archive.writestr(entry, data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(staged, 0o600)
        budget.tick()
        publish_file(staged, destination)
    return {"package_id": package.package_id, "path": str(destination)}


def read_snapshot(path, *, budget=None):
    budget = budget if budget is not None else Budget()
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise InvalidIR("Snapshot archive must be a regular file")
            raw = stream.read(MAX_ARCHIVE_BYTES + 1)
    except OSError:
        raise InvalidIR("Cannot read snapshot archive; symlinks are not accepted") from None
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise ResourceLimit("Snapshot archive exceeds size limit")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if not 2 <= len(entries) <= MAX_FILES + 1:
                raise ResourceLimit("Snapshot archive file count exceeds limit")
            files, total = {}, 0
            for entry in entries:
                budget.tick()
                filename = portable_path(entry.filename)
                if (
                    entry.orig_filename != filename
                    or filename in files
                    or entry.is_dir()
                    or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)
                ):
                    raise InvalidIR("Duplicate or non-regular archive member")
                if entry.compress_type != zipfile.ZIP_STORED or entry.flag_bits & 1:
                    raise UnsupportedFeature("Snapshot members must be uncompressed and unencrypted")
                if entry.file_size > MAX_BYTES:
                    raise ResourceLimit("Snapshot member exceeds size limit")
                total += entry.file_size
                if total > MAX_SNAPSHOT_BYTES:
                    raise ResourceLimit("Snapshot exceeds 32 MB")
                files[filename] = archive.read(entry)
    except (zipfile.BadZipFile, RuntimeError, ValueError, NotImplementedError):
        raise InvalidIR("Invalid snapshot archive") from None
    if "manifest.json" not in files:
        raise InvalidIR("Snapshot manifest is missing")
    package = SnapshotPackage(files.pop("manifest.json"), MappingProxyType(files))
    unpack_snapshot(package, budget)
    return package
