"""Recheck exact accepted dependent bodies in an ordinary private candidate."""

from ..engine import construction
from ..engine.acquisition import AcquisitionError


def bodies(body, base, contract, budget):
    pinned = body["task"].get("preserve_declarations", {})
    if not isinstance(pinned, dict) or len(pinned) > 32:
        raise AcquisitionError("Invalid dependent preservation bindings")
    accepted = base.document()["declarations"]
    result = {}
    for symbol, expected in pinned.items():
        budget.tick()
        if (
            symbol not in base.index
            or base.index[symbol] != expected
            or symbol not in contract["required_symbols"]
        ):
            raise AcquisitionError("Preserved declaration is not bound to the construction base")
        declaration = accepted[symbol]
        slots = construction.SLOTS[declaration["kind"]]
        if contract["interfaces"].get(symbol) != {k: v for k, v in declaration.items() if k not in slots}:
            raise AcquisitionError("Preserved declaration interface changed")
        result[symbol] = declaration
    return result


def seed(draft, retained, base, contract, budget):
    if not retained:
        return draft
    evidence = {
        "artifact_kind": "evidence",
        "evidence_kind": "provider_statement",
        "origin": "awm-adm:dependency-preservation",
        "scope": "Reuse of accepted syntax, checked anew; not empirical evidence or an imported proof.",
        "content": {
            "base_theory": base.version,
            "declarations": {s: base.index[s] for s in retained},
        },
    }
    definitions = {
        symbol: {slot: declaration.get(slot) for slot in construction.SLOTS[declaration["kind"]]}
        for symbol, declaration in retained.items()
        if construction.SLOTS[declaration["kind"]]
    }
    return construction.merge(
        draft,
        {
            "draft": {"definitions": definitions, "declarations": {}, "discard": [], "retractions": []},
            "evidence": [evidence],
        },
        contract,
        budget,
    )


def check(draft, retained):
    for symbol, declaration in retained.items():
        if draft["declarations"].get(symbol) != declaration or symbol in draft["retractions"]:
            raise AcquisitionError("Unrequested dependent definitions must remain unchanged", symbol=symbol)
