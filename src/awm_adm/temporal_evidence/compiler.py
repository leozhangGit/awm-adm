"""Typed evidence to ordinary finite candidates, with checked dependency preservation."""

from ..engine import build_candidate
from ..engine.admission import dependent_closure
from ..engine.artifacts import digest
from ..engine.data import encode, read_json, thaw
from .diagnostics import UnsupportedTemporal
from .identity import address, descriptor_key, relation, resolve
from .models import BINDING, Catalog, Claim
from .reader import symbol_for


def project(task, checked, budget, existing):
    from ..sources.compute import declaration, evidence

    p = Catalog.model_validate(task["policy"]["projection"]).model_dump()
    definitions, artifacts, support, cells = {}, {}, {}, {}
    prospective = []
    retractions = set()
    for row in task["claims"]:
        budget.tick()
        f = Claim.model_validate(row["claim"]).model_dump()
        selected, reason = resolve(p, f)
        if reason or f["status"] != "candidate":
            raise ValueError("Held temporal claim cannot publish")
        s = next(s for s in p["predicates"] if s["symbol"] == f["predicate"])
        source = row["source"]
        record = source["record"]
        raw = source["content"].encode()
        span = f["source"]
        if (
            digest(raw) != record["content_digest"]
            or any(span[k] != record[k] for k in ("source_id", "item_id", "version_id", "content_digest"))
            or not 0 <= span["start_byte"] < span["end_byte"] <= len(raw)
        ):
            raise ValueError("Temporal claim does not bind its original source")
        raw[: span["start_byte"]].decode()
        raw[span["start_byte"] : span["end_byte"]].decode()
        raw[span["end_byte"] :].decode()
        matches = []
        for prior in [*existing.values(), *prospective]:
            budget.tick()
            if prior["claim"]["predicate"] == f["predicate"] and prior["series"] != s:
                raise UnsupportedTemporal("descriptor_revision")
            r = relation(f, s, prior["claim"], prior["series"])
            if r == "same":
                matches.append(prior)
            if r == "overlap" and f["value"] != prior["claim"]["value"]:
                if task["context"]["mode"] != "backward" or prior.get("proposed"):
                    raise UnsupportedTemporal("partial_scope_revision")
                retractions.add(prior["symbol"])
        if len(matches) > 1:
            raise UnsupportedTemporal("ambiguous_identity")
        if matches and matches[0].get("proposed"):
            raise UnsupportedTemporal("duplicate_address")
        symbol = matches[0]["symbol"] if matches else symbol_for(p["namespace"], f, s)
        if symbol in checked["model"].index and symbol not in existing:
            raise ValueError("Temporal symbol collides with an unrelated declaration")
        bridge = None
        if matches:
            prior = matches[0]
            if prior.get("legacy"):
                bridge = {k: prior["legacy"][k] for k in ("projection", "cell")}
            else:
                bridge = prior.get("legacy_bridge")
        snote = evidence({"profile": "awm-adm-source-evidence/1", **source})
        skey = digest(encode(snote))
        artifacts[skey] = snote
        note = evidence(
            {
                "profile": BINDING,
                "projection": p,
                "claim": f,
                "cell": selected[0],
                "descriptor_digest": descriptor_key(s),
                "address": address(f, s),
                "source_evidence": skey,
                "evidence_group": row["evidence_group"],
                "legacy_bridge": bridge,
            }
        )
        nkey = digest(encode(note))
        artifacts[nkey] = note
        definitions[symbol] = declaration(p, f)
        support[symbol] = [skey, nkey]
        cells[symbol] = {"claim": f["claim_id"], "version": row["version_key"]}
        prospective.append({"symbol": symbol, "claim": f, "series": s, "proposed": True})
    if len(set(existing) | set(cells)) > task["max_facts"]:
        raise ValueError("Combined temporal fact limit exceeded")
    before = checked["model"].document()["declarations"]
    roots = {s for s, d in definitions.items() if s in before and encode(before[s]) != encode(d)}
    preserved = dependent_closure(checked["model"], roots | retractions, budget) - definitions.keys()
    if len(preserved) > 32:
        raise ValueError("Temporal replacement dependency bound exceeded")
    for symbol in sorted(preserved):
        budget.tick()
        # Retain the exact body and exact prior evidence; the kernel rechecks its new dependencies.
        definitions[symbol] = before[symbol]
        origin = thaw(read_json(checked["blobs"][checked["support"][symbol]]))
        support[symbol] = list(origin["evidence"])
        for key in origin["evidence"]:
            artifacts[key] = thaw(read_json(checked["blobs"][key]))
    package = build_candidate(
        checked["model"],
        definitions,
        candidate_id=task["candidate_id"],
        evidence=list(artifacts.values()),
        evidence_by_symbol=support,
        retractions=sorted(retractions),
    )
    from ..learning.compute import transport

    return {"package": transport(package), "preview": definitions, "cells": cells, "work": budget.used}
