"""Small conversational adapter; all answers still come from the local query path."""

from ..temporal import day_bounds, timezone_name
from ..wire import decode
from .types import EvidenceQuery, RecallQuery


def parse(proposal, projection, accepted, temporal_context):
    if proposal["command"].startswith("recall evidence with "):
        query = RecallQuery.model_validate(
            decode(proposal["command"][len("recall evidence with ") :].encode())
        ).model_dump()
        profiles = ([projection] if projection else []) + list(accepted)
        if not all(
            any(
                selector["entity_id"] in p["entities"]
                and selector["predicate"] in {x["symbol"] for x in p["predicates"]}
                for p in profiles
            )
            for selector in query["selectors"]
        ):
            return {
                **proposal,
                "status": "needs_clarification",
                "query": None,
                "clarification": "Which accepted subject and property do you mean?",
            }
        return {**proposal, "query": query}
    supplied = decode(proposal["command"][len("query evidence with ") :].encode())
    raw = supplied.get("scope") if isinstance(supplied, dict) else None
    resolution = None
    if isinstance(raw, dict) and set(raw) == {"kind", "effective_on", "timezone"}:
        if raw["kind"] == "instant":
            raise ValueError("A calendar day is not an exact instant")
        zone = timezone_name(
            raw["timezone"]
            if raw["timezone"] is not None
            else (temporal_context or {}).get("system_timezone")
        )
        try:
            start, end = day_bounds(raw["effective_on"], zone)
        except ValueError as error:
            if "skipped or repeated" not in str(error):
                raise
            return {
                **proposal,
                "status": "needs_clarification",
                "query": None,
                "clarification": "That calendar boundary is skipped or repeated in the selected timezone. Which exact time and offset do you mean?",
            }
        supplied["scope"] = {
            "kind": raw["kind"],
            "effective_from": start,
            "effective_to": end,
            "precision": "day",
            "timezone_basis": zone,
        }
        resolution = {
            "date": raw["effective_on"],
            "timezone": zone,
            "timezone_source": "explicit" if raw["timezone"] else "system",
            "effective_from": start,
            "effective_to": end,
        }
    query = EvidenceQuery.model_validate(supplied).model_dump()
    profiles = ([projection] if projection else []) + list(accepted)
    if not any(
        query["entity_id"] in p["entities"] and query["predicate"] in {x["symbol"] for x in p["predicates"]}
        for p in profiles
    ):
        return {
            **proposal,
            "status": "needs_clarification",
            "query": None,
            "clarification": "Which accepted subject and property do you mean?",
        }
    return {**proposal, "query": query, **({"temporal_resolution": resolution} if resolution else {})}


def readable(body, display):
    if body["status"] != "succeeded":
        return {
            "disputed_source_support": "The supporting evidence is disputed. The model cannot give a supported answer yet.",
            "ambiguous_temporal_meaning_or_report": "Several reported versions match. Which report or observation do you mean?",
            "value_varies_within_period": "The supported value changes within that period. Which narrower time should I check?",
        }.get(
            body.get("historical_reason"),
            "The model has no supported answer for that temporal meaning and scope. More evidence or a clearer scope is needed."
            if body["status"] == "needs_input"
            else "The local temporal check did not complete; no answer was established.",
        )
    values = body["values"]
    scope = values.get("scope", {})
    meta = body.get("value_metadata") or {}
    if "items" in values:
        items = values["items"]
        if not items:
            text = "No matching accepted records were found. This does not establish that no event occurred."
        else:
            lines = []
            for item in items[:32]:
                when = item["scope"]
                a = item["attribution"]
                value = (
                    "Yes" if item["value"] is True else "No" if item["value"] is False else str(item["value"])
                )
                line = f"{value} {item['unit']}; {when['kind']}: {when['effective_from']}"
                if when.get("effective_to"):
                    line += " to " + when["effective_to"] + " (end excluded)"
                if a.get("actor"):
                    line += f"; {a['modality']} reported by {a['actor']}"
                if item.get("meaning"):
                    line = item["meaning"] + "\nRecorded value: " + line
                lines.append(line)
            text = "Accepted records:\n" + "\n".join(lines)
        if scope.get("kind") == "accepted_evidence_recall":
            text += "\nThese are saved records with their original scopes, not a new calculation or a current-state assertion."
            if scope.get("unmatched_selectors"):
                text += " Some requested subjects or properties have no supported records."
        if scope.get("relation") == "possibly_overlapping":
            text += "\nIncludes observations whose uncertain time windows may overlap the requested period."
        if not scope.get("complete") or len(items) > 32:
            text += "\nThis is a partial view; older or additional matching records may remain."
        if len(text) > 16000:
            return text[:15700] + (
                "\nSome records or details are omitted from this summary. "
                "The full result retains the records and whether more matches remain."
            )
        return text
    text = "Model answer: " + display(body) + "."
    q = meta.get("query_scope", {})
    labels = {
        "instant": "At the requested instant",
        "validity": "Throughout the requested interval",
        "period_value": "For the specified period as a whole",
    }
    text += "\n" + labels.get(q.get("kind"), "Within the requested scope") + ", based on accepted evidence."
    if meta.get("statement_level") == "reported":
        text += f" This is a {meta.get('modality')} reported by {meta.get('actor')}, not confirmation of the actual outcome."
    return text
