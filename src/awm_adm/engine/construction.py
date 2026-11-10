"""Receiver-owned interfaces and bounded, private theory construction.

Drafts are unaccepted data, never Models. Complete drafts use ordinary ordered
admission, including the entire independent behavioral policy.
"""

from copy import deepcopy

from .acquisition import AcquisitionError, check_proposal, check_size
from .artifacts import digest
from .data import encode, name, read_json, shape
from .errors import InvalidIR, ResourceLimit
from .model import declaration_references

PROFILE = "adm-private-draft/1"
MAX_DRAFT_BYTES = 262144
MAX_EVIDENCE_BYTES = 32768
SLOTS = {
    "type": (),
    "presentation": (),
    "function": ("body",),
    "goal": ("body",),
    "assertion": ("body",),
    "transition": ("legal", "next", "cost"),
}


class DraftIncomplete(AcquisitionError):
    code = "draft_incomplete"


def interfaces(contract):
    """Require exact metadata, not a partially specified declaration header."""
    headers = contract["interfaces"]
    for symbol, header in headers.items():
        kind = header.get("kind")
        if not isinstance(kind, str) or (
            kind == "presentation" and not isinstance(header.get("construction"), str)
        ):
            raise InvalidIR("Construction interface kind must be a string", symbol=symbol)
        fields = {
            "type": ("type",),
            "function": ("params", "returns"),
            "goal": ("state",),
            "assertion": ("params",),
            "transition": ("state", "parameters"),
        }.get(kind)
        if kind == "presentation":
            fields = {
                "product": ("left", "right", "project_left", "project_right"),
                "coproduct": ("left", "right", "inject_left", "inject_right"),
                "pullback": (
                    "left",
                    "right",
                    "base",
                    "left_map",
                    "right_map",
                    "project_left",
                    "project_right",
                ),
                "equalizer": ("source", "target", "first", "second", "include"),
            }.get(header.get("construction"))
            if fields is not None:
                fields = ("construction", "carrier", *fields)
        if fields is None:
            raise InvalidIR("Unsupported construction interface", symbol=symbol)
        shape(header, ("kind", *fields))
    return headers


def seed(contract):
    headers = interfaces(contract)
    local = {s: deepcopy(h) for s, h in headers.items() if not SLOTS[h["kind"]]}
    evidence = {
        "artifact_kind": "evidence",
        "evidence_kind": "provider_statement",
        "origin": "adm:interface-construction",
        "scope": "Receiver-supplied interface requirements; not an empirical observation or a proof.",
        "content": {"contract_digest": digest(encode(contract)), "interfaces": deepcopy(headers)},
    }
    key = digest(encode(evidence))
    draft = {
        "profile": PROFILE,
        "declarations": local,
        "retractions": [],
        "evidence": {key: evidence},
        "support": {s: [key] for s in local},
        "interface_evidence": key,
        "retraction_support": [],
    }
    _bounded(draft, contract)
    return draft


def _bounded(draft, contract):
    check_size({"declarations": draft["declarations"], "retractions": draft["retractions"]}, contract)
    if len(encode(draft["evidence"])) > MAX_EVIDENCE_BYTES or len(encode(draft)) > MAX_DRAFT_BYTES:
        raise ResourceLimit("Private construction draft exceeds its fixed storage allowance")
    read_json(draft)


def merge(draft, reply, contract, budget):
    """Apply one complete normalized update atomically; do not infer definitions."""
    shape(reply, ("draft", "evidence"))
    update = reply["draft"]
    shape(update, ("definitions", "declarations", "discard", "retractions"))
    if (
        not isinstance(update["definitions"], dict)
        or not isinstance(update["declarations"], dict)
        or not isinstance(update["discard"], list)
        or not isinstance(update["retractions"], list)
        or not isinstance(reply["evidence"], list)
        or not reply["evidence"]
    ):
        raise InvalidIR("Construction update requires maps, lists, and explicit evidence")
    check_size(update, contract)
    headers = interfaces(contract)
    definitions = {}
    for symbol, slots in update["definitions"].items():
        budget.tick()
        if symbol not in headers or not SLOTS[headers[symbol]["kind"]]:
            raise AcquisitionError("Only requested executable slots may be supplied", symbol=symbol)
        if slots is None:
            continue  # Explicit keep; never a missing-value placeholder in executable IR.
        shape(slots, SLOTS[headers[symbol]["kind"]])
        for field, expression in slots.items():
            if not isinstance(expression, dict) and not (field == "cost" and expression is None):
                raise InvalidIR(
                    "Definition slots must contain expression objects", symbol=symbol, field=field
                )
        definitions[symbol] = {**deepcopy(headers[symbol]), **deepcopy(slots)}
        if definitions[symbol].get("kind") == "transition" and definitions[symbol]["cost"] is None:
            del definitions[symbol]["cost"]
    if set(update["declarations"]) & set(headers):
        raise AcquisitionError("Known interfaces are constructed locally; supply only their definition slots")
    definitions.update(deepcopy(update["declarations"]))
    for symbol in update["retractions"]:
        name(symbol, qualified=True)
    discarded = update["discard"]
    for symbol in discarded:
        name(symbol, qualified=True)
        if (
            symbol not in draft["declarations"]
            or symbol in definitions
            or (symbol in headers and not SLOTS[headers[symbol]["kind"]])
        ):
            raise AcquisitionError(
                "Cannot discard an absent, updated, or receiver-constructed declaration", symbol=symbol
            )
    if len(discarded) != len(set(discarded)):
        raise InvalidIR("Duplicate draft discard")
    result = deepcopy(draft)
    for symbol in discarded:
        result["declarations"].pop(symbol)
        result["support"].pop(symbol)
    sources = {digest(encode(e)): deepcopy(e) for e in reply["evidence"]}
    result["evidence"].update(sources)
    for symbol, declaration in definitions.items():
        budget.tick()
        result["declarations"][symbol] = declaration
        result["support"][symbol] = sorted(
            set(sources) | ({result["interface_evidence"]} if symbol in headers else set())
        )
    result["retractions"] = sorted(update["retractions"])
    result["retraction_support"] = sorted(sources) if result["retractions"] else []
    used = {result["interface_evidence"], *result["retraction_support"]}
    for keys in result["support"].values():
        used.update(keys)
    result["evidence"] = {k: v for k, v in result["evidence"].items() if k in used}
    check_proposal(result["declarations"], result["retractions"], contract, budget, complete=False)
    _bounded(result, contract)
    return result


def complete(draft, contract, base, budget):
    missing = set(contract["required_symbols"]) - draft["declarations"].keys()
    available = (draft["declarations"].keys() | base.index.keys()) - set(draft["retractions"])
    dependencies = set()
    for declaration in draft["declarations"].values():
        budget.tick()
        dependencies.update(declaration_references(declaration) - available)
    if missing or dependencies:
        raise DraftIncomplete(
            "Private draft needs additional definitions",
            missing_symbols=sorted(missing),
            missing_dependencies=sorted(dependencies),
        )
    check_proposal(draft["declarations"], draft["retractions"], contract, budget)


def view(draft, contract):
    """Provider-facing work only; evidence remains in the local audit record."""
    return {
        "trust": "unaccepted_private_draft",
        "declarations": deepcopy(draft["declarations"]),
        "retractions": list(draft["retractions"]),
        "missing_symbols": sorted(set(contract["required_symbols"]) - draft["declarations"].keys()),
        "definition_slots": {
            s: list(SLOTS[h["kind"]]) for s, h in interfaces(contract).items() if SLOTS[h["kind"]]
        },
        "digest": digest(encode(draft)),
    }


def fingerprint(draft):
    return {"declarations": draft["declarations"], "retractions": draft["retractions"]}
