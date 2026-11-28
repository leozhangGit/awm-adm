"""Search accepted artifacts without asking users to select an owner epoch."""

from ..engine.data import read_json, thaw
from ..learning.service import fault, fingerprint
from ..runtime.protocol import unpack
from ..teaching.review import carrier


def text(value, *, depth=0):
    if depth > 5:
        return "…"
    if isinstance(value, str):
        return value[:2000]
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (float, int)):
        return str(value)
    if isinstance(value, list):
        return "; ".join(text(v, depth=depth + 1) for v in value[:16])[:3000]
    if isinstance(value, dict):
        return "; ".join(f"{k}: {text(v, depth=depth + 1)}" for k, v in list(value.items())[:16])[:3000]
    return ""


def expression(value, depth=0):
    if depth > 8 or not isinstance(value, dict):
        return "bounded expression"
    op = value.get("op", "expression")
    if op == "literal":
        return text(value.get("value"))
    if op == "var":
        return value["name"]
    if op == "call":
        return (
            value["function"]
            + "("
            + ", ".join(f"{k}={expression(v, depth + 1)}" for k, v in value.get("args", {}).items())
            + ")"
        )
    symbols = {
        "add": " + ",
        "sub": " − ",
        "mul": " × ",
        "eq": " = ",
        "lt": " < ",
        "le": " ≤ ",
        "gt": " > ",
        "ge": " ≥ ",
        "and": " and ",
        "or": " or ",
    }
    args = value.get("args")
    if isinstance(args, list):
        values = [expression(v, depth + 1) for v in args[:16]]
        return "(" + symbols[op].join(values) + ")" if op in symbols else op + "(" + ", ".join(values) + ")"
    return op + ": " + text({k: v for k, v in value.items() if k != "op"})


def describe(declaration):
    kind = declaration["kind"]
    if kind == "type":
        return carrier(declaration["type"])
    if kind in {"function", "assertion"}:
        inputs = (
            "; ".join(f"{k}: {carrier(v)}" for k, v in declaration.get("params", {}).items()) or "No inputs"
        )
        result = carrier(declaration["returns"]) if kind == "function" else "true or false"
        return f"{inputs}. Returns {result}. Rule: {expression(declaration.get('body'))}"
    return kind.capitalize() + ": " + text(declaration)


def _evidence_view(value, artifacts):
    content = value["content"]
    result = {"name": value["origin"], "description": value["scope"], "excerpt": ""}
    if isinstance(content, str):
        result["excerpt"] = content[:2000]
    elif isinstance(content, dict):
        profile = content.get("profile")
        if profile == "awm-adm-teaching-intent/1":
            result["name"] = "Recorded teaching intent"
            result["excerpt"] = "\n".join(i["text"] for i in content["inputs"])[:2000]
            result["teaching_intent"] = content
        elif profile == "awm-adm-source-evidence/1":
            result["name"] = content.get("record", {}).get("origin", "Supplied source")
            result["excerpt"] = text(content.get("content", ""))
        elif profile == "awm-adm-projected-fact/1":
            claim = content["claim"]
            result["name"] = f"{claim['entity_id']} · {claim['predicate']}"
            cell = content["cell"]
            when = (
                f"At {cell['effective_from']}."
                if cell["kind"] == "point"
                else f"From {cell['effective_from']} until {cell['effective_to']} (exclusive)."
            )
            result["description"] = (
                f"Source assertion: {text(claim['value']['value'])} {claim['unit']}. {when}"
            )
            source = artifacts.get(content.get("source_evidence"), {}).get("content", {})
            original = source.get("content") if isinstance(source, dict) else None
            if isinstance(original, str):
                span = claim["source"]
                result["excerpt"] = original.encode()[span["start_byte"] : span["end_byte"]].decode("utf-8")[
                    :2000
                ]
        elif isinstance(content.get("summary"), str):
            result["excerpt"] = content["summary"][:2000]
        elif isinstance(content.get("interfaces"), dict):
            result["excerpt"] = "Finite interfaces: " + ", ".join(content["interfaces"])[:2000]
    return result


def evidence_view(value, artifacts):
    # Generic evidence may carry arbitrary user-authored content. Displaying it
    # must not interpret an unfamiliar/malformed profile as executable authority.
    try:
        return _evidence_view(value, artifacts)
    except (KeyError, TypeError, ValueError, AttributeError):
        return {"name": value["origin"], "description": value["scope"], "excerpt": ""}


def search(runtime, key, *, query="", kind=None, after=0, limit=20, revision=None):
    saved = runtime.store.revision(key)
    if revision and revision != saved["revision_id"]:
        fault("stale_context", "The accepted model changed. Search again to see its current knowledge")
    package = unpack(saved["snapshot"])
    manifest = thaw(read_json(package.manifest))
    records = []
    artifacts = {e["digest"]: thaw(read_json(package.files[e["path"]])) for e in manifest["files"]}
    origins = {v["declaration"]: v for v in artifacts.values() if v.get("artifact_kind") == "origin"}
    evidence = {
        eid: evidence_view(v, artifacts)
        for eid, v in artifacts.items()
        if v.get("artifact_kind") == "evidence"
    }
    for entry in manifest["files"]:
        if entry["role"] not in {"declaration", "evidence"}:
            continue
        value = artifacts[entry["digest"]]
        if entry["role"] == "declaration":
            d = value["declaration"]
            row = {
                "id": entry["digest"],
                "name": value["symbol"],
                "kind": d["kind"],
                "category": "declaration",
                "description": describe(d),
                "definition": d,
                "evidence": [
                    {
                        "id": eid,
                        "source": evidence[eid]["name"],
                        "kind": artifacts[eid]["evidence_kind"],
                        "description": evidence[eid]["description"],
                        **(
                            {"teaching_intent": evidence[eid]["teaching_intent"]}
                            if "teaching_intent" in evidence[eid]
                            else {}
                        ),
                    }
                    for eid in origins.get(entry["digest"], {}).get("evidence", [])
                ],
            }
            for eid in origins.get(entry["digest"], {}).get("evidence", []):
                if (
                    isinstance(artifacts[eid].get("content"), dict)
                    and artifacts[eid]["content"].get("profile") == "awm-adm-projected-fact/1"
                ):
                    row.update(label=evidence[eid]["name"], description=evidence[eid]["description"])
                    break
            if any(
                isinstance(artifacts[eid].get("content"), dict)
                and artifacts[eid]["content"].get("profile") == "awm-adm-source-dispute/1"
                for eid in origins.get(entry["digest"], {}).get("evidence", [])
            ):
                row["description"] += (
                    " Current source support is on hold; this declaration cannot establish an answer until checked replacement evidence is accepted."
                )
        else:
            row = {
                "id": entry["digest"],
                "name": evidence[entry["digest"]]["name"],
                "kind": value["evidence_kind"],
                "category": "evidence",
                "description": evidence[entry["digest"]]["description"],
                "excerpt": evidence[entry["digest"]]["excerpt"],
                **(
                    {"teaching_intent": evidence[entry["digest"]]["teaching_intent"]}
                    if "teaching_intent" in evidence[entry["digest"]]
                    else {}
                ),
            }
        if kind and kind not in {row["kind"], row["category"]}:
            continue
        if (
            query.casefold()
            not in (
                row["name"]
                + " "
                + row.get("label", "")
                + " "
                + row["kind"]
                + " "
                + row["description"]
                + " "
                + row.get("excerpt", "")
            ).casefold()
        ):
            continue
        records.append(row)
    records.sort(key=lambda r: (r["category"], r["name"], r["id"]))
    return {
        "revision_id": saved["revision_id"],
        "context": saved["context"],
        "query_digest": fingerprint({"query": query, "kind": kind}),
        "total": len(records),
        "items": records[after : after + limit],
        "next_cursor": after + limit if after + limit < len(records) else None,
    }
