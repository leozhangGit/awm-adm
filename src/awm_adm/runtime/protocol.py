"""Bounded internal data protocol; no serialized Python objects or executable code."""

import base64
import json

from ..engine.snapshots import SnapshotPackage

MAX_MESSAGE = 16_777_216


class RuntimeFault(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def dumps(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > MAX_MESSAGE:
        raise RuntimeFault("resource_exhausted", "Runtime message exceeds byte limit")
    return raw


def loads(raw):
    if len(raw) > MAX_MESSAGE:
        raise RuntimeFault("resource_exhausted", "Runtime message exceeds byte limit")
    return json.loads(raw)


def pack_core(snapshot):
    return {
        "manifest": base64.b64encode(snapshot.manifest).decode(),
        "files": {key: base64.b64encode(data).decode() for key, data in snapshot.files.items()},
    }


def unpack_core(value):
    if not isinstance(value, dict) or set(value) != {"manifest", "files"}:
        raise ValueError("Invalid snapshot transport")
    dumps(value)
    if not isinstance(value["files"], dict) or len(value["files"]) > 4096:
        raise ValueError("Invalid snapshot file map")
    return SnapshotPackage(
        base64.b64decode(value["manifest"], validate=True),
        {key: base64.b64decode(data, validate=True) for key, data in value["files"].items()},
    )


def temporal_features(snapshot):
    """Feature discovery is structural; raw source text never enables a feature."""
    features = set()
    for raw in snapshot.files.values():
        item = loads(raw)
        if isinstance(item, dict) and item.get("artifact_kind") == "evidence":
            content = item.get("content")
            if isinstance(content, dict) and str(content.get("profile", "")).startswith(
                "awm-adm-temporal-binding/"
            ):
                if content["profile"] != "awm-adm-temporal-binding/1":
                    raise ValueError("Unsupported temporal snapshot feature")
                features.add("temporal-evidence/1")
    return sorted(features)


def pack(snapshot):
    core = pack_core(snapshot)
    features = temporal_features(snapshot)
    if not features:
        return core
    from ..engine.artifacts import digest

    return {
        "profile": "awm-adm-service-snapshot/1",
        "required_features": features,
        "core": core,
        "core_digest": digest(dumps(core)),
    }


def unpack(value):
    from ..engine.artifacts import digest

    if isinstance(value, dict) and value.get("profile") == "awm-adm-service-snapshot/1":
        if set(value) != {"profile", "required_features", "core", "core_digest"}:
            raise ValueError("Invalid service snapshot envelope")
        dumps(value)
        if (
            value["required_features"] != ["temporal-evidence/1"]
            or digest(dumps(value["core"])) != value["core_digest"]
        ):
            raise ValueError("Unknown or mismatched required snapshot features")
        snapshot = unpack_core(value["core"])
        if temporal_features(snapshot) != value["required_features"]:
            raise ValueError("Snapshot feature declaration differs from evidence")
        return snapshot
    snapshot = unpack_core(value)
    if temporal_features(snapshot):
        raise ValueError("Temporal evidence requires its service snapshot envelope")
    return snapshot
