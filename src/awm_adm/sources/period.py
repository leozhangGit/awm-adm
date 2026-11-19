"""Whole-period historical lookup over checked finite cells; no inference from coverage."""

from ..engine.execution import execute
from ..engine.results import bind_result, claim


def lookup(checked, query, entries, limits, budget):
    start, end = query["effective_from"], query["effective_to"]
    cells = []
    reason = None
    for symbol, entry in entries.items():
        budget.tick()
        fact, cell = entry["claim"], entry["cell"]
        if fact["entity_id"] != query["entity_id"] or fact["predicate"] != query["predicate"]:
            continue
        if cell["kind"] == "point":
            if start <= cell["effective_from"] < end:
                reason = "point_support_cannot_establish_period"
            continue
        left, right = max(start, cell["effective_from"]), min(end, cell["effective_to"])
        if left < right:
            cells.append((left, right, symbol, entry))
    cursor = start
    for left, right, _, entry in sorted(cells, key=lambda c: (c[0], c[1], c[2])):
        budget.tick()
        if left != cursor:
            reason = reason or "unknown_or_ambiguous_scope"
        if entry["disputed"]:
            reason = "disputed_source_support"
        cursor = max(cursor, right)
    if cursor != end:
        reason = reason or "unknown_or_ambiguous_scope"
    result, facts, carrier = None, [], None
    if not reason:
        for _, _, symbol, entry in cells:
            budget.tick()
            value = execute(
                checked["model"],
                {
                    "op": "evaluate",
                    "module": symbol.rsplit(".", 1)[0],
                    "expression": {"op": "call", "function": symbol, "args": {}},
                },
                limits,
                budget=budget,
            )
            if value["status"] != "succeeded":
                return bind_result(checked["model"].version, query, value, [])
            current = (entry["claim"]["value"]["kind"], entry["claim"]["unit"])
            if result is not None and (value["value"] != result["value"] or current != carrier):
                reason = "value_varies_within_period"
                break
            result, carrier = value, current
            facts.append(
                {
                    "claim": entry["claim"],
                    "cell": entry["cell"],
                    "symbol": symbol,
                    "evidence_group": entry["evidence_group"],
                    "support_status": "active",
                }
            )
    if reason or result is None:
        return bind_result(
            checked["model"].version,
            query,
            {
                "status": "needs_input",
                "error": {"code": "needs_evidence", "message": reason or "unknown_or_ambiguous_scope"},
                "unknown": True,
                "work": budget.used,
                "guarantee": None,
            },
            [],
        )
    result.update(
        facts=facts,
        work=budget.used,
        scope={
            "kind": "historical_period",
            "effective_from": start,
            "effective_to": end,
            "symbols": sorted(f["symbol"] for f in facts),
        },
    )
    bind_result(checked["model"].version, query, result, [claim("computed_value", "local_interpreter")])
    result["assurance"]["empirical_fidelity"] = "conditional_on_declared_sources"
    return result
