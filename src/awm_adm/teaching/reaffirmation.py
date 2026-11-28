"""Checked reuse of accepted definitions; no provider-generated executable content."""

from ..engine import build_candidate
from ..engine.construction import SLOTS
from ..engine.data import encode, name
from ..engine.errors import InvalidIR
from .diagnostics import PreparationError
from .intent import attach, retain_support


def pins(model, plan, budget):
    accepted = model.document()["declarations"]
    revised = {s for c in plan["children"] for s in c["interfaces"]}
    selected = set()
    result = []
    for child in plan["children"]:
        current = {}
        for symbol in child.get("reuse_symbols", []):
            budget.tick()
            name(symbol, qualified=True)
            if symbol not in model.index:
                raise PreparationError("reaffirmation", "unknown_reuse_symbol")
            if symbol in revised or symbol in selected:
                raise PreparationError("reaffirmation", "overlapping_reuse")
            if accepted[symbol]["kind"] not in SLOTS:
                raise PreparationError("reaffirmation", "unsupported_reuse_kind")
            selected.add(symbol)
            current[symbol] = model.index[symbol]
        result.append(current)
    return result


def headers(model, selected):
    accepted = model.document()["declarations"]
    return {
        symbol: {k: v for k, v in accepted[symbol].items() if k not in SLOTS[accepted[symbol]["kind"]]}
        for symbol in selected
    }


def candidate(checked, selected, intent, candidate_id, budget):
    base = checked["model"]
    if not selected or len(selected) > 32 or not intent:
        raise InvalidIR("Reaffirmation requires bounded pinned declarations and caller intent")
    declarations = {}
    for symbol, expected in selected.items():
        budget.tick()
        if base.index.get(symbol) != expected:
            raise InvalidIR("Reaffirmation declaration changed since preparation")
        declarations[symbol] = base.document()["declarations"][symbol]
    sources, support = retain_support(checked, selected, [], {})
    sources, support = attach(intent, declarations, set(), sources, support)
    package = build_candidate(
        base, declarations, candidate_id=candidate_id, evidence=sources, evidence_by_symbol=support
    )
    return package, declarations


def unchanged(before, after, selected):
    # Defense in depth around ordinary admission, not a replacement for it.
    if encode(before.document()) != encode(after.document()):
        raise InvalidIR("Reaffirmation cannot change accepted definitions")
    return {"symbols": sorted(selected), "definitions_unchanged": True, "acquisition_calls": 0}
