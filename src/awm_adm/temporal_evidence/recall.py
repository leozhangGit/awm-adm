"""Bounded recall of accepted evidence; no inferred time window or scalar choice."""

from .query import finish, gap
from .types import RecallQuery


def lookup(checked, query, entries, limits, budget, *, context=None):
    query = RecallQuery.model_validate(query).model_dump()
    selected = {(s["entity_id"], s["predicate"]) for s in query["selectors"]}
    rows = []
    for symbol, entry in entries.items():
        budget.tick()
        fact = entry["claim"]
        if (fact["entity_id"], fact["predicate"]) in selected:
            rows.append((symbol, entry))
    if any(e["disputed"] for _, e in rows):
        return gap(checked, query, budget, "disputed_source_support")
    return finish(checked, query, rows, limits, budget, collection=True, context=context)
