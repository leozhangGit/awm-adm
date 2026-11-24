"""Immutable selected-material packets; ordinary source validation is unchanged.

Offsets refer to the original UTF-8 bytes in the packet payload. The packet is
itself the source of extracted claims and survives in accepted snapshot evidence.
"""

import hashlib
import json

PREFIX = "ADM selected material /1\n"
PROFILE = "awm-adm-selected-material/1"


def build(sources, source_id, identity):
    parts, payload, offset = [], [], 0
    for source in sources:
        raw = source["content"].encode()
        parts.append(
            {
                **{k: source[k] for k in ("source_id", "item_id", "version_id", "origin", "media_type")},
                "content_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "start_byte": offset,
                "end_byte": offset + len(raw),
            }
        )
        payload.append(source["content"])
        offset += len(raw) + 2
    header = json.dumps({"profile": PROFILE, "parts": parts}, ensure_ascii=False, separators=(",", ":"))
    return {
        "source_id": source_id,
        "item_id": identity,
        "version_id": "v1",
        "media_type": "text/plain",
        "origin": "Selected Teach material: " + identity,
        "supersedes_version": None,
        "content": PREFIX + header + "\n\n" + "\n\n".join(payload),
    }


def references(content):
    """Read verified original references for conservative source-correction holds.

    Invalid or ordinary text has no packet dependencies. This is not an assertion
    validator and does not confer trust on the content or its source labels.
    """
    if not content.startswith(PREFIX):
        return []
    try:
        header, payload = content[len(PREFIX) :].split("\n\n", 1)
        value, raw = json.loads(header), payload.encode()
        if value["profile"] != PROFILE or not 1 <= len(value["parts"]) <= 100:
            return []
        result = []
        end = -2
        for part in value["parts"]:
            start, stop = part["start_byte"], part["end_byte"]
            if (
                type(start) is not int
                or type(stop) is not int
                or start != end + 2
                or not start < stop <= len(raw)
            ):
                return []
            segment = raw[start:stop]
            segment.decode()
            if part["content_digest"] != "sha256:" + hashlib.sha256(segment).hexdigest():
                return []
            identity = [part[k] for k in ("source_id", "item_id", "version_id")]
            if any(not isinstance(value, str) or not value for value in identity):
                return []
            result.append(identity)
            end = stop
        return result if end == len(raw) else []
    except (ValueError, KeyError, TypeError, UnicodeError):
        return []
