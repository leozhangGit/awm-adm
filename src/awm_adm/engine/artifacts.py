"""Exact-byte content addressing; storage is independent of domain semantics."""

from hashlib import sha256
from typing import Protocol

from .errors import InvalidIR, KnowledgeGap


def digest(data: bytes) -> str:
    return "sha256:" + sha256(data).hexdigest()


class ArtifactStore(Protocol):
    def put(self, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...


class MemoryStore:
    def __init__(self):
        self._blobs: dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        data = bytes(data)
        key = digest(data)
        self._blobs[key] = data
        return key

    def get(self, key: str) -> bytes:
        if key not in self._blobs:
            raise KnowledgeGap("Missing artifact", artifact=key)
        data = self._blobs[key]
        if digest(data) != key:
            raise InvalidIR("Artifact integrity failure", artifact=key)
        return data
