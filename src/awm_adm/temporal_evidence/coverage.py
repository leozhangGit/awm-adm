"""Bounded additive coverage and explicit window holds across evidence profiles."""

from .identity import scope_key
from .legacy import extend, is_catalog, view
from .legacy import scope as legacy_scope
from .models import Catalog


def retained(entry, profile):
    if not is_catalog(profile):
        return entry["cell"] in profile["cells"]
    scope = (
        entry["cell"] if entry.get("profile") == "awm-adm-temporal-binding/1" else legacy_scope(entry["cell"])
    )
    return (
        entry["claim"]["entity_id"] in profile["entities"]
        and entry["claim"]["predicate"] in {p["symbol"] for p in profile["predicates"]}
        and scope_key(scope) in {scope_key(c) for c in profile["cells"]}
    )


def check(task, checked, budget):
    from ..sources.compute import temporal_entries

    old = task["old_projection"]
    new = task["projection"]
    if not is_catalog(new):
        raise ValueError("Temporal catalog cannot be downgraded to a legacy projection")
    new = Catalog.model_validate(new).model_dump()
    normalized = old if is_catalog(old) else view(old)
    merged = extend(old, new)
    if task["kind"] == "extend" and (
        {scope_key(c) for c in merged["cells"]} != {scope_key(c) for c in new["cells"]}
        or set(merged["entities"]) != set(new["entities"])
        or {p["symbol"] for p in merged["predicates"]} != {p["symbol"] for p in new["predicates"]}
    ):
        raise ValueError("Extension must retain accepted catalog coverage")
    descriptors = {p["symbol"]: p for p in new["predicates"]}
    if any(p != descriptors.get(p["symbol"]) for p in normalized["predicates"]) or not set(
        normalized["entities"]
    ) <= set(new["entities"]):
        raise ValueError("Coverage cannot redefine or remove accepted semantic carriers")
    temporal_entries(checked, budget)  # verify the complete retained support before policy publication
