"""Bounded descriptions of checked publication differences, never provider claims."""

import json

from ..engine.artifacts import digest
from ..engine.data import encode

LIMIT = 32
BYTE_LIMIT = 12000


def expression(value, depth=0, remaining=None):
    remaining = [128] if remaining is None else remaining
    remaining[0] -= 1
    if remaining[0] < 0 or depth > 6 or not isinstance(value, dict):
        return "[structured expression]"
    op = value.get("op")
    if op == "literal":
        return clipped(json.dumps(value.get("value"), ensure_ascii=False))
    if op == "var":
        return value["name"]
    if op == "call":
        return (
            value["function"]
            + "("
            + ", ".join(
                f"{k}={expression(v, depth + 1, remaining)}" for k, v in value.get("args", {}).items()
            )
            + ")"
        )
    args = value.get("args", [])
    operators = {
        "add": " + ",
        "sub": " − ",
        "mul": " × ",
        "eq": " = ",
        "lt": " < ",
        "le": " ≤ ",
        "and": " and ",
        "or": " or ",
    }
    if isinstance(args, list) and args and op in operators:
        return "(" + operators[op].join(expression(a, depth + 1, remaining) for a in args) + ")"
    return "[structured expression]"


def clipped(text):
    return text if len(text) <= 480 else text[:480] + " [abbreviated]"


def carrier(value):
    if "ref" in value:
        return value["ref"]
    if value["kind"] == "int":
        return f"whole numbers {value['min']}–{value['max']}"
    if value["kind"] == "bool":
        return "true or false"
    return "[structured type]"


def description(body, fact=None):
    if body is None:
        return None
    if fact:
        claim, cell = fact["claim"], fact["cell"]
        text = (
            f"{claim['entity_id']}: {claim['predicate']} = "
            f"{json.dumps(claim['value']['value'], ensure_ascii=False)} {claim['unit']}; "
            + (
                f"at {cell['effective_from']}"
                if cell["kind"] in ("point", "instant")
                else f"{cell['effective_from']} to {cell['effective_to'] or 'open end'} (end excluded)"
            )
        )
        if fact.get("profile") == "awm-adm-temporal-binding/1":
            text += "; " + cell["kind"]
            series = fact["series"]
            if series.get("statement_level") == "reported":
                clock = claim["reported_time"]
                text += f"; reported by {series['actor']} ({series['modality']}) at {clock['effective_from']}"
                if clock.get("effective_to"):
                    text += " to " + clock["effective_to"] + " (uncertain occurrence; end excluded)"
            if series.get("metric"):
                text += "; metric " + series["metric"]
        text += "; support held" if fact["disputed"] else "; accepted source support"
    elif body["kind"] == "function":
        params = ", ".join(f"{k}: {carrier(v)}" for k, v in body["params"].items()) or "no inputs"
        text = f"({params}) returns {expression(body['body'])}; output {carrier(body['returns'])}"
    elif "body" in body:
        text = body["kind"] + ": " + expression(body["body"])
    else:
        text = body["kind"] + " declaration"
    # Do not turn a shortened or structurally unsupported rendering into exact meaning.
    raw = encode(body)
    return {
        "definition": body if len(raw) <= 2048 else None,
        "definition_complete": len(raw) <= 2048,
        "text": text[:480],
        "abbreviated": len(text) > 480
        or "[structured expression]" in text
        or "[structured type]" in text
        or "[abbreviated]" in text
        or (body["kind"] != "function" and not fact),
        "definition_digest": digest(raw),
    }


def publication_effects(current, instance, budget, *, before_facts=None, after_facts=None):
    before, after = current["model"].index, instance._model.index
    old, new = current["model"].document()["declarations"], instance._model.document()["declarations"]
    changed = sorted(s for s in after if before.get(s) != after[s])
    support_changed = sorted(s for s in after if current["support"].get(s) != instance._support[s])
    removed = sorted(set(before) - set(after))
    effects = {
        "added": sorted(set(after) - set(before)),
        "replaced": sorted(s for s in changed if s in before),
        "removed": removed,
        "declarations": {s: after[s] for s in changed},
        "support_changed": support_changed,
        "support": {s: instance._support[s] for s in support_changed},
    }
    symbols = sorted(set(changed) | set(support_changed) | set(removed))
    entries = []
    used = 0
    for symbol in symbols[:LIMIT]:
        budget.tick()
        a, b = old.get(symbol), new.get(symbol)
        dependencies = (
            sorted(d for d in instance._model.dependencies(symbol) if before.get(d) != after.get(d))
            if b
            else []
        )
        kind = (
            "added"
            if a is None
            else "removed"
            if b is None
            else "definition_changed"
            if encode(a) != encode(b)
            else "preserved_dependent"
            if dependencies
            else "evidence_changed"
            if symbol in support_changed
            else "rebound"
        )
        entry = {
            "symbol": symbol,
            "kind": kind,
            "before": description(a, (before_facts or {}).get(symbol)),
            "after": description(b, (after_facts or {}).get(symbol)),
            "before_declaration": before.get(symbol),
            "after_declaration": after.get(symbol),
            "before_support": current["support"].get(symbol),
            "after_support": instance._support.get(symbol),
            "changed_dependencies": dependencies[:LIMIT],
            "dependencies_complete": len(dependencies) <= LIMIT,
        }
        for side, facts in (("before", before_facts), ("after", after_facts)):
            if facts and symbol in facts:
                f = facts[symbol]
                entry[side + "_fact"] = {
                    "entity": f["claim"]["entity_id"],
                    "predicate": f["claim"]["predicate"],
                    "value": f["claim"]["value"],
                    "unit": f["claim"]["unit"],
                    "cell": f["cell"],
                    "source": f["claim"]["source"],
                    "support_held": f["disputed"],
                    **(
                        {
                            "series": f["series"],
                            "reported_time": f["claim"]["reported_time"],
                            "observed_time": f["claim"]["observed_time"],
                        }
                        if f.get("profile") == "awm-adm-temporal-binding/1"
                        else {}
                    ),
                }
        size = len(encode(entry))
        if used + size > BYTE_LIMIT:
            break
        entries.append(entry)
        used += size
    effects["change_report"] = {
        "profile": "awm-adm-publication-changes/1",
        "entries": entries,
        "total": len(symbols),
        "complete": len(entries) == len(symbols),
        "before_theory": current["model"].version,
        "after_theory": instance._model.version,
        "mode": instance.info()["mode"],
    }
    return effects


def sentence(entry):
    fact = entry.get("after_fact") or entry.get("before_fact")
    symbol = f"{fact['entity']}: {fact['predicate']}" if fact else entry["symbol"]
    kind = entry["kind"]
    old = (entry.get("before") or {}).get("text")
    new = (entry.get("after") or {}).get("text")
    if any((entry.get(side) or {}).get("abbreviated") for side in ("before", "after")):
        old, new = (old or "not present") + " [abbreviated]", (new or "not present") + " [abbreviated]"
    if kind == "preserved_dependent":
        return (
            f"Kept {symbol} unchanged: {new}. Rechecked against updated "
            + ", ".join(entry["changed_dependencies"])
            + "; its answers may change."
        )
    if kind == "definition_changed":
        return f"Changed {symbol}: before {old}; now {new}."
    if kind == "added":
        return f"Added {symbol}: {new}."
    if kind == "removed":
        return f"Removed {symbol} from active knowledge: previously {old}. History is retained."
    if kind == "evidence_changed":
        return f"Updated evidence for {symbol}; its definition is unchanged. Before: {old}; now: {new}."
    return f"Rechecked {symbol} without changing its definition."


def summarize(receipts):
    entries, publications, complete, used, total = [], [], True, 0, 0
    for receipt in receipts:
        if receipt["status"] != "accepted":
            continue
        report = (receipt.get("effects") or {}).get("change_report")
        publications.append(
            {
                k: receipt.get(k)
                for k in ("receipt_id", "objective_id", "decision_revision", "accepted_revision", "mode")
            }
        )
        if not report:
            complete = False
            continue  # Historical receipts without a checked diff are not guessed from prose.
        complete &= report["complete"]
        total += report["total"]
        for entry in report["entries"]:
            value = {
                **entry,
                "receipt_id": receipt["receipt_id"],
                "revision_id": receipt["accepted_revision"],
            }
            size = len(encode(value))
            if len(entries) >= LIMIT or used + size > BYTE_LIMIT:
                complete = False
                break
            entries.append(value)
            used += size
    return {
        "profile": "awm-adm-teaching-changes/1",
        "entries": entries,
        "complete": complete,
        "total_reported_changes": total,
        "publications": publications[:LIMIT],
        "publications_complete": len(publications) <= LIMIT,
        "text": " ".join(sentence(e) for e in entries)
        + (
            " Change details are incomplete; consult the retained publication records."
            if not complete
            else ""
        ),
    }
