"""Ordered provider JSON, separate from canonical content-addressed artifacts."""

import json

from .data import read_json, thaw

ENCODING = "ordered-json/1"


def encode_wire(value):
    """Keep deliberate schema property order under the ordinary strict JSON limits.

    Structured generators may emit properties in schema order. Artifact encoding
    still sorts keys for stable model identities; it must not serialize this wire.
    """
    checked = thaw(read_json(value, encoded=False))
    return (json.dumps(checked, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )
