"""Sparse catalog limits, safe diagnostics and bounded provider context."""

import re

from ..runtime.protocol import RuntimeFault

PREDICATES = 65_536
CONTEXT_PREDICATES = 256


class CatalogCapacity(RuntimeFault):
    def __init__(self, existing, proposed, shared, merged, limit=PREDICATES):
        super().__init__(
            "catalog_capacity_exceeded",
            f"The combined evidence catalog needs {merged} predicates; its limit is {limit}. "
            "Existing knowledge is unchanged. Splitting the same additions does not reduce this total.",
        )
        self.diagnostic = {
            "code": self.code,
            "stage": "catalog_extension",
            "message": str(self),
            "resource": "predicates",
            "existing": existing,
            "proposed": proposed,
            "shared": shared,
            "required": merged,
            "limit": limit,
        }


def check_capacity(a, b, merged):
    if len(merged) > PREDICATES:
        existing, proposed = len(a["predicates"]), len(b["predicates"])
        raise CatalogCapacity(existing, proposed, existing + proposed - len(merged), len(merged))


def check_growth(current, proposed, limit):
    """A lower operating limit never invalidates retained knowledge or equal coverage."""
    if not proposed:
        return
    existing = {p["symbol"] for p in (current or {}).get("predicates", [])}
    future = {p["symbol"] for p in proposed["predicates"]}
    if future - existing and len(existing | future) > limit:
        raise CatalogCapacity(
            len(existing), len(future), len(existing & future), len(existing | future), limit
        )


def context_window(catalog, text):
    """Retrieval hint only. Never changes validation coverage or claims completeness."""
    predicates = catalog["predicates"]
    if len(predicates) <= CONTEXT_PREDICATES:
        return catalog, {"complete": True, "total_predicates": len(predicates)}
    words = set(re.findall(r"[\w]+", text.casefold()))

    def rank(p):
        terms = set(re.findall(r"[\w]+", (p["symbol"] + " " + p.get("meaning", "")).casefold()))
        return (-len(words & terms), p["symbol"])

    selected = sorted(predicates, key=rank)[:CONTEXT_PREDICATES]
    return {**catalog, "predicates": selected}, {
        "complete": False,
        "total_predicates": len(predicates),
        "included_predicates": len(selected),
        "selection": "lexical_relevance",
        "warning": "This is a partial retrieval hint, not exhaustive knowledge. Absence here does not establish absence from the model. Reuse exact known identities; clarify an uncertain identity instead of inventing a synonym.",
    }


def extraction_catalog(catalog, selected, *, external):
    """Explicit working set, checked against pinned policy; never guess source coverage."""
    if selected is not None:
        if len(set(selected)) != len(selected):
            raise RuntimeFault("invalid_input", "Catalog selection contains duplicate predicates")
        available = {p["symbol"]: p for p in catalog["predicates"]}
        if not set(selected) <= available.keys():
            raise RuntimeFault("invalid_input", "Catalog selection names an unknown predicate")
        return {**catalog, "predicates": [available[s] for s in selected]}
    if external and len(catalog["predicates"]) > CONTEXT_PREDICATES:
        raise RuntimeFault(
            "needs_specification",
            "Select up to 256 catalog predicates for this extraction. The accumulated catalog is larger; no source was silently omitted or provider call dispatched.",
        )
    return catalog
