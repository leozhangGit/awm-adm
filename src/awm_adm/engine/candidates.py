"""Complete, content-addressed learning packages; no filesystem paths are opened here."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath

from .artifacts import digest
from .data import MAX_BYTES, encode, name, read_json, shape, thaw
from .errors import InvalidIR, KnowledgeGap, ResourceLimit, UnsupportedFeature
from .model import declaration_references
from .requests import identifier

MAX_PACKAGE_BYTES = 8_000_000


def hash_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise InvalidIR("Invalid artifact digest")
    return value


def portable_path(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise InvalidIR("Invalid attachment path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise InvalidIR("Attachment path must be a normalized package-relative path")
    return value


@dataclass(frozen=True)
class CandidatePackage:
    envelope: bytes
    attachments: Mapping[str, bytes]


def unpack(package):
    """Validate receipt integrity; semantic checking happens after arrival is recorded."""
    if not isinstance(package, CandidatePackage) or type(package.envelope) is not bytes:
        raise InvalidIR("Expected a CandidatePackage with exact envelope bytes")
    envelope = thaw(read_json(package.envelope))
    shape(
        envelope,
        (
            "protocol",
            "kind",
            "candidate_id",
            "profile",
            "base_theory",
            "proposals",
            "retractions",
            "addressed_gaps",
            "attachments",
        ),
    )
    if envelope["protocol"] != "adm/0.1" or envelope["kind"] != "learning_candidate":
        raise InvalidIR("Unsupported candidate envelope")
    if envelope["profile"] != "finite-v0":
        raise UnsupportedFeature("Unsupported candidate profile")
    identifier(envelope["candidate_id"])
    hash_id(envelope["base_theory"])
    for field in ("proposals", "retractions", "addressed_gaps", "attachments"):
        if not isinstance(envelope[field], list):
            raise InvalidIR("Candidate field must be an array", field=field)
    if not envelope["proposals"] and not envelope["retractions"]:
        raise InvalidIR("Candidate must propose or retract content")
    symbols = set()
    for proposal in envelope["proposals"]:
        shape(proposal, ("symbol", "artifact"))
        name(proposal["symbol"], qualified=True)
        hash_id(proposal["artifact"])
        if proposal["symbol"] in symbols:
            raise InvalidIR("Duplicate proposed symbol")
        symbols.add(proposal["symbol"])
    for field, validator in (("retractions", hash_id), ("addressed_gaps", identifier)):
        seen = set()
        for value in envelope[field]:
            validator(value)
            if value in seen:
                raise InvalidIR("Duplicate candidate entry", field=field)
            seen.add(value)
    if not isinstance(package.attachments, Mapping):
        raise InvalidIR("Attachments must map paths to bytes")
    blobs, paths, roles = {}, {}, {}
    total = len(package.envelope)
    for entry in envelope["attachments"]:
        shape(entry, ("path", "digest", "bytes", "role"))
        path, key = portable_path(entry["path"]), hash_id(entry["digest"])
        if path in paths or key in roles:
            raise InvalidIR("Duplicate attachment path or digest")
        if entry["role"] not in ("declaration", "evidence"):
            raise UnsupportedFeature("Only declaration and evidence attachments are supported")
        data = package.attachments.get(path)
        if type(data) is not bytes or type(entry["bytes"]) is not int or len(data) != entry["bytes"]:
            raise InvalidIR("Missing attachment or incorrect byte count", path=path)
        if len(data) > MAX_BYTES or digest(data) != key:
            raise InvalidIR("Attachment size or digest mismatch", path=path)
        total += len(data)
        if total > MAX_PACKAGE_BYTES:
            raise ResourceLimit("Candidate package exceeds 8 MB")
        blobs[key], paths[path], roles[key] = data, key, entry["role"]
    if set(paths) != set(package.attachments):
        raise InvalidIR("Unlisted attachment supplied")
    for proposal in envelope["proposals"]:
        if roles.get(proposal["artifact"]) != "declaration":
            raise InvalidIR("Proposed declaration attachment is missing")
    package_hash = digest(encode({"envelope": digest(package.envelope), "attachments": paths}))
    return envelope, blobs, paths, package_hash


def build_candidate(
    base, declarations, *, candidate_id, evidence, retractions=(), addressed_gaps=(), evidence_by_symbol=None
):
    """Construct a transport package; this does not admit its proposed model."""
    declarations = thaw(read_json(declarations))
    if not isinstance(declarations, dict):
        raise InvalidIR("declarations must be an object")
    attachments, entries = {}, []

    def attach(path, value, role):
        data = encode(value)
        key = digest(data)
        attachments[path] = data
        entries.append({"path": path, "digest": key, "bytes": len(data), "role": role})
        return key

    evidence_keys = [attach(f"evidence/{i}.json", value, "evidence") for i, value in enumerate(evidence)]
    if evidence_by_symbol is not None:
        if set(evidence_by_symbol) != set(declarations) or any(
            not isinstance(refs, list) or not refs or any(key not in evidence_keys for key in refs)
            for refs in evidence_by_symbol.values()
        ):
            raise InvalidIR("Declaration evidence support must reference supplied evidence")
    proposals = []
    index = base.index
    for number, (symbol, body) in enumerate(sorted(declarations.items())):
        external = declaration_references(body) - declarations.keys()
        if external - index.keys():
            raise KnowledgeGap(
                "Candidate uses unknown base dependencies", symbols=sorted(external - index.keys())
            )
        artifact = {
            "artifact_kind": "declaration",
            "profile": "finite-v0",
            "symbol": symbol,
            "dependencies": {s: index[s] for s in sorted(external)},
            "evidence": evidence_keys if evidence_by_symbol is None else evidence_by_symbol[symbol],
            "body": body,
        }
        key = attach(f"declarations/{number}.json", artifact, "declaration")
        proposals.append({"symbol": symbol, "artifact": key})
    try:
        retired = [index[symbol] for symbol in retractions]
    except KeyError as error:
        raise InvalidIR("Retraction must refer to a symbol in the base model") from error
    envelope = {
        "protocol": "adm/0.1",
        "kind": "learning_candidate",
        "candidate_id": candidate_id,
        "profile": "finite-v0",
        "base_theory": base.version,
        "proposals": proposals,
        "retractions": retired,
        "addressed_gaps": list(addressed_gaps),
        "attachments": entries,
    }
    package = CandidatePackage(encode(envelope), attachments)
    unpack(package)
    return package
