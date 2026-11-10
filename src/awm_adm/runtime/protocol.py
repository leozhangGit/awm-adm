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


def pack(snapshot):
    return {
        "manifest": base64.b64encode(snapshot.manifest).decode(),
        "files": {key: base64.b64encode(data).decode() for key, data in snapshot.files.items()},
    }


def unpack(value):
    if not isinstance(value, dict) or set(value) != {"manifest", "files"}:
        raise ValueError("Invalid snapshot transport")
    dumps(value)
    if not isinstance(value["files"], dict) or len(value["files"]) > 4096:
        raise ValueError("Invalid snapshot file map")
    return SnapshotPackage(
        base64.b64decode(value["manifest"], validate=True),
        {key: base64.b64decode(data, validate=True) for key, data in value["files"].items()},
    )
