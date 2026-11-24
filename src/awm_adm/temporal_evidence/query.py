"""Bounded local temporal queries. No interpolation, aggregation or provider reasoning."""

import base64

from ..engine.artifacts import digest
from ..engine.data import encode, read_json, thaw
from ..engine.execution import execute
from ..engine.results import bind_result, claim
from .identity import descriptor_key
from .types import EvidenceQuery


def intersects(a, b, relation="contained"):
    left, right = a["effective_from"], a.get("effective_to")
    if right is None:
        return b["effective_from"] <= left < b["effective_to"]
    if relation == "contained":
        return b["effective_from"] <= left and right <= b["effective_to"]
    return left < b["effective_to"] and b["effective_from"] < right


def lookup(checked, query, entries, limits, budget, *, context=None):
    query = EvidenceQuery.model_validate(query).model_dump()
    intent, scope = query["intent"], query["scope"]
    rows = []

    for symbol, e in entries.items():
        budget.tick()
        f = e["claim"]
        c = e["cell"]
        s = e["series"]
        if (f["entity_id"], f["predicate"]) != (query["entity_id"], query["predicate"]):
            continue
        reported = s.get("statement_level") == "reported"
        if intent == "reports_about" and not reported:
            continue
        if intent == "observations_in" and reported:
            continue
        if query["reported_time"] is not None:
            if not reported:
                continue
            a = f["reported_time"]
            b = query["reported_time"]
            if b["kind"] == "unknown":
                raise ValueError("Unknown reported time is not a filter")
            if a["kind"] == "unknown":
                continue
            if b["kind"] == "exact":
                if a["kind"] != "exact" or a["effective_from"] != b["effective_from"]:
                    continue
            elif not intersects(a, b, query["relation"]):
                continue
        match = False
        if intent == "value_at":
            at = scope["effective_from"]
            match = (c["kind"] == "instant" and c["effective_from"] == at) or (
                c["kind"] == "validity" and c["effective_from"] <= at < c["effective_to"]
            )
        elif intent == "value_throughout":
            match = c["kind"] == "validity" and intersects(c, scope, "possibly_overlapping")
        elif intent == "value_for_period":
            match = c["kind"] == "period_value" and (c["effective_from"], c["effective_to"]) == (
                scope["effective_from"],
                scope["effective_to"],
            )
        elif intent == "observations_in":
            match = c["kind"] in ("instant", "occurrence") and intersects(c, scope, query["relation"])
        else:
            match = intersects(c, scope, query["relation"])
        if match:
            rows.append((symbol, e))
    collection = intent in ("observations_in", "reports_about")
    if not rows and not collection:
        return gap(checked, query, budget, "no_supported_temporal_meaning_for_scope")
    if any(e["disputed"] for _, e in rows):
        return gap(checked, query, budget, "disputed_source_support")
    if not collection:
        identities = {descriptor_key(e["series"]) for _, e in rows}
        reports = {
            encode({k: e["claim"].get(k) for k in ("reported_time", "occurrence_id")})
            for _, e in rows
            if e["series"].get("statement_level") == "reported"
        }
        if len(identities) > 1 or len(reports) > 1:
            return gap(checked, query, budget, "ambiguous_temporal_meaning_or_report")
        if intent == "value_throughout":
            cursor = scope["effective_from"]
            for _, e in sorted(rows, key=lambda r: r[1]["cell"]["effective_from"]):
                budget.tick()
                c = e["cell"]
                if c["effective_from"] > cursor:
                    return gap(checked, query, budget, "incomplete_validity_coverage")
                cursor = max(cursor, min(scope["effective_to"], c["effective_to"]))
            if cursor != scope["effective_to"]:
                return gap(checked, query, budget, "incomplete_validity_coverage")
        if len({encode(e["claim"]["value"]) for _, e in rows}) != 1:
            return gap(checked, query, budget, "value_varies_within_period")
    return finish(checked, query, rows, limits, budget, collection=collection, context=context)


def gap(checked, query, budget, reason):
    return bind_result(
        checked["model"].version,
        query,
        {
            "status": "needs_input",
            "error": {"code": "needs_evidence", "message": reason},
            "unknown": True,
            "work": budget.used,
            "guarantee": None,
        },
        [],
    )


def finish(checked, query, rows, limits, budget, *, collection, context=None):
    """Evaluate validated evidence and bind one bounded, cursor-addressed result."""
    recall = query["op"] == "recall_evidence"
    intent, scope = ("recall", None) if recall else (query["intent"], query["scope"])
    support_root = digest(encode(checked["support"]))
    rows.sort(key=lambda r: (r[1]["cell"]["effective_from"], r[0]))
    key = digest(
        encode(
            {
                "query": {k: v for k, v in query.items() if k != "cursor"},
                "theory": checked["model"].version,
                "support": support_root,
                "context": context,
            }
        )
    )
    offset = 0
    if query["cursor"]:
        try:
            cursor = thaw(read_json(base64.b64decode(query["cursor"], validate=True)))
        except Exception as error:
            raise ValueError("Invalid temporal cursor") from error
        if set(cursor) != {"binding", "after"} or cursor["binding"] != key:
            raise ValueError("Stale temporal cursor")
        keys = [s for s, _ in rows]
        if cursor["after"] not in keys:
            raise ValueError("Temporal cursor does not belong to the query")
        offset = keys.index(cursor["after"]) + 1
    page = rows[offset : offset + query["limit"]] if collection else rows
    next_cursor = None
    if collection and offset + len(page) < len(rows):
        next_cursor = base64.b64encode(encode({"binding": key, "after": page[-1][0]})).decode()
    result = None
    facts = []
    items = []
    for symbol, e in page:
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
        result = value
        facts.append(
            {
                "symbol": symbol,
                "claim": e["claim"],
                "cell": e["cell"],
                "series": e["series"],
                "support_status": "active",
            }
        )
        items.append(
            {
                "value": value["value"],
                "unit": e["claim"]["unit"],
                "scope": e["cell"],
                "attribution": {k: e["series"].get(k) for k in ("statement_level", "actor", "modality")},
                "reported_time": e["claim"].get("reported_time"),
                "observed_time": e["claim"].get("observed_time"),
                "symbol": symbol,
                "claim_id": e["claim"]["claim_id"],
            }
        )
        if recall:
            items[-1].update(
                entity_id=e["claim"]["entity_id"],
                predicate=e["claim"]["predicate"],
                meaning=e["series"]["meaning"],
                qualifiers=e["series"].get("qualifiers", []),
                metric=e["series"].get("metric"),
                source=e["claim"]["source"],
                occurrence_id=e["claim"].get("occurrence_id"),
            )
    resolved = {
        "kind": "temporal_evidence",
        "intent": intent,
        "subject_scope": scope,
        "support_root": support_root,
        "symbols": [s for s, _ in page],
        "descriptors": sorted({descriptor_key(e["series"]) for _, e in page}),
        "complete": next_cursor is None and offset == 0,
        "enumeration_complete": next_cursor is None,
        "next_cursor": next_cursor,
        "relation": "recorded_scopes" if recall else query["relation"],
    }
    if recall:
        matched = {(e["claim"]["entity_id"], e["claim"]["predicate"]) for _, e in rows}
        resolved.update(
            kind="accepted_evidence_recall",
            selectors=query["selectors"],
            unmatched_selectors=[
                s for s in query["selectors"] if (s["entity_id"], s["predicate"]) not in matched
            ],
        )
    if collection:
        result = {"status": "succeeded", "items": items, "work": budget.used}
    result.update(facts=facts, scope=resolved, work=budget.used)
    if not collection:
        e = rows[0][1]
        result["value_metadata"] = {
            "unit": e["claim"]["unit"],
            "query_scope": scope,
            "intent": intent,
            "statement_level": e["series"]["statement_level"],
            "actor": e["series"].get("actor"),
            "modality": e["series"].get("modality"),
            "metric": e["series"].get("metric"),
            "reported_time": e["claim"].get("reported_time"),
            "complete": True,
        }
    bind_result(
        checked["model"].version,
        query,
        result,
        [
            claim(
                "accepted_collection" if collection else "computed_value",
                "local_temporal_adapter" if collection else "local_interpreter",
            )
        ],
    )
    result["assurance"]["empirical_fidelity"] = "conditional_on_declared_sources"
    return result
