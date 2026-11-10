"""Bounded source parsing, finite projection and support checks. No store or network."""

import json

from ..contracts import FactClaim, SourceRecord
from ..engine import Instance, build_candidate, validate_snapshot
from ..engine.artifacts import digest
from ..engine.data import encode, read_json, thaw
from ..engine.errors import InvalidIR
from ..engine.execution import execute
from ..engine.results import bind_result, claim
from ..engine.snapshots import export_instance
from ..learning.compute import package, transport
from ..runtime.protocol import pack, unpack
from .models import ExtractedFact, ExtractionOutput, Projection


def loads(raw):
    return thaw(read_json(raw))


def evidence(content):
    return {
        "artifact_kind": "evidence",
        "evidence_kind": "observation",
        "origin": "awm-adm:sources",
        "scope": "Owner-reviewed supplied assertions; external truth is assumed, not established.",
        "content": content,
    }


def cell_symbol(profile, entity, predicate, cell):
    identity = {"projection": profile, "entity": entity, "predicate": predicate, "cell": cell}
    return profile["namespace"] + ".fact_" + digest(encode(identity)).split(":")[1][:40]


def resolve(profile, fact):
    if fact["assertion_kind"] != "assertion":
        return [], "non_assertion"
    if not profile:
        return [], "needs_schema"
    predicates = {p["symbol"]: p for p in profile["predicates"]}
    if fact["entity_id"] not in profile["entities"] or fact["predicate"] not in predicates:
        return [], "unknown_entity_or_predicate"
    pred = predicates[fact["predicate"]]
    value = fact["value"]
    if value["kind"] != pred["kind"] or fact["unit"] != pred["unit"]:
        return [], "type_or_unit_mismatch"
    if (pred["kind"] == "integer" and not pred["minimum"] <= value["value"] <= pred["maximum"]) or (
        pred["kind"] == "enum" and value["value"] not in pred["values"]
    ):
        return [], "value_outside_carrier"
    scope = fact["temporal_scope"]
    if scope["kind"] == "unknown":
        return [], "unknown_time"
    if (
        scope["kind"] != profile["cells"][0]["kind"]
        or scope["granularity"] != profile["cells"][0]["granularity"]
    ):
        return [], "time_carrier_mismatch"
    cells = []
    for cell in profile["cells"]:
        if scope["kind"] == "point":
            if scope["effective_from"] == cell["effective_from"]:
                cells.append(cell)
        elif scope["effective_from"] < cell["effective_to"] and (
            scope["effective_to"] is None or scope["effective_to"] > cell["effective_from"]
        ):
            if scope["effective_from"] > cell["effective_from"] or (
                scope["effective_to"] is not None and scope["effective_to"] < cell["effective_to"]
            ):
                return [], "partial_time_cell"
            cells.append(cell)
    return (cells, None) if cells else ([], "outside_coverage")


def local_spans(source):
    text, media = source["content"], source["record"]["media_type"]
    if media == "application/json":
        value = loads(text)
        # A single object or an array of objects; no free-form rule language.
        if isinstance(value, dict):
            return [(value, 0, len(text.encode()))]
        if not isinstance(value, list):
            raise ValueError("Expected fact object or array")
        decoder, pos, rows = json.JSONDecoder(), text.index("[") + 1, []
        for _ in value:
            while text[pos].isspace() or text[pos] == ",":
                pos += 1
            item, end = decoder.raw_decode(text, pos)
            rows.append((item, len(text[:pos].encode()), len(text[:end].encode())))
            pos = end
        return rows
    rows, offset = [], 0
    for line in text.splitlines(keepends=True):
        raw = line.encode()
        if media == "application/x-ndjson" and line.strip():
            rows.append((loads(line), offset, offset + len(raw.rstrip(b"\r\n"))))
        elif media in ("text/plain", "text/markdown") and line.startswith("fact "):
            rows.append((loads(line[5:]), offset + 5, offset + len(raw.rstrip(b"\r\n"))))
        offset += len(raw)
    return rows


def extract(task, budget):
    source, profile = task["source"], task.get("projection")
    raw = source["content"].encode()
    if task["purpose"] == "schema":
        proposal = Projection.model_validate(loads(task.get("provider_text", source["content"]))).model_dump()
        return {"status": "proposed_schema", "proposal": proposal, "claims": [], "work": budget.used}
    if "provider_text" in task:
        output = ExtractionOutput.model_validate(loads(task["provider_text"]))
        rows = [
            (c.model_dump(exclude={"start_byte", "end_byte"}), c.start_byte, c.end_byte)
            for c in output.claims
        ]
    else:
        rows = local_spans(source)
    if len(rows) > task["max_claims"]:
        raise ValueError("Claim bound exceeded; no partial extraction")
    claims = []
    for index, (value, start, end) in enumerate(rows):
        budget.tick()
        fact = ExtractedFact.model_validate(value).model_dump()
        if not 0 <= start < end <= len(raw):
            raise ValueError("Invalid source span")
        raw[:start].decode()
        raw[start:end].decode()
        raw[end:].decode()
        cells, reason = resolve(profile, fact)
        record = source["record"]
        span = {k: record[k] for k in ("source_id", "item_id", "version_id", "content_digest")}
        span.update(start_byte=start, end_byte=end)
        uid = task["job_id"] + ":" + str(index)
        item = FactClaim(
            claim_id=uid, source=span, status="candidate" if not reason else "needs_evidence", **fact
        ).model_dump()
        claims.append(
            {
                "claim": item,
                "cells": cells,
                "reason": reason,
                "excerpt": raw[start:end].decode(),
                "statement_digest": digest(encode(fact)),
                "evidence_group": task.get("evidence_group"),
            }
        )
    return {"status": "extracted" if claims else "needs_specification", "claims": claims, "work": budget.used}


def projected(checked, budget):
    result, source_cache = {}, {}
    for symbol, origin_key in checked["support"].items():
        budget.tick()
        origin = read_json(checked["blobs"][origin_key])
        notes = [thaw(read_json(checked["blobs"][key]))["content"] for key in origin["evidence"]]
        entries = [n for n in notes if isinstance(n, dict) and n.get("profile") == "awm-adm-projected-fact/1"]
        if not entries:
            continue
        if len(entries) != 1:
            raise InvalidIR("Ambiguous projected support")
        entry = entries[0]
        profile = Projection.model_validate(entry["projection"]).model_dump()
        fact = FactClaim.model_validate(entry["claim"]).model_dump()
        source_key = entry["source_evidence"]
        if source_key not in origin["evidence"]:
            raise InvalidIR("Projected fact does not retain its original source")
        if source_key not in source_cache:
            source = thaw(read_json(checked["blobs"][source_key]))["content"]
            if source.get("profile") != "awm-adm-source-evidence/1":
                raise InvalidIR("Unsupported source evidence profile")
            record = SourceRecord.model_validate(source["record"]).model_dump()
            raw = source["content"].encode("utf-8")
            if digest(raw) != record["content_digest"] or len(raw) != record["byte_count"]:
                raise InvalidIR("Source bytes do not match their immutable identity")
            source_cache[source_key] = record, raw
        record, raw = source_cache[source_key]
        span = fact["source"]
        if any(
            span[k] != record[k] for k in ("source_id", "item_id", "version_id", "content_digest")
        ) or span["end_byte"] > len(raw):
            raise InvalidIR("Claim span does not match retained source")
        raw[: span["start_byte"]].decode("utf-8")
        raw[span["start_byte"] : span["end_byte"]].decode("utf-8")
        cells, reason = resolve(profile, fact)
        if (
            reason
            or entry["cell"] not in cells
            or cell_symbol(profile, fact["entity_id"], fact["predicate"], entry["cell"]) != symbol
        ):
            raise InvalidIR("Invalid fact projection metadata")
        expected = declaration(profile, fact)
        if encode(checked["model"].document()["declarations"][symbol]) != encode(expected):
            raise InvalidIR("Projection metadata differs from executable declaration")
        result[symbol] = {
            **entry,
            "disputed": any(
                isinstance(n, dict) and n.get("profile") == "awm-adm-source-dispute/1" for n in notes
            ),
        }
    return result


def declaration(profile, fact):
    pred = next(p for p in profile["predicates"] if p["symbol"] == fact["predicate"])
    carrier = (
        {"kind": "bool"}
        if pred["kind"] == "boolean"
        else (
            {"kind": "int", "min": pred["minimum"], "max": pred["maximum"]}
            if pred["kind"] == "integer"
            else {"kind": "enum", "values": pred["values"]}
        )
    )
    return {
        "kind": "function",
        "params": {},
        "returns": carrier,
        "body": {"op": "literal", "value": fact["value"]["value"], "type": carrier},
    }


def compute(task, budget):
    if task["operation"] == "source_extract":
        return extract(task, budget)
    checked = validate_snapshot(unpack(task["snapshot"]), budget=budget)
    if task["operation"] == "source_requirements":
        if not checked["conformance"].get("contracts"):
            raise ValueError("Checked automatic feeds require installed independent behavioral requirements")
        return {"work": budget.used}
    if task["operation"] == "source_coverage":
        old = Projection.model_validate(task["old_projection"]).model_dump()
        new = Projection.model_validate(task["projection"]).model_dump()
        if old["namespace"] != new["namespace"]:
            raise ValueError("Coverage cannot rename a projection namespace")
        if not set(old["entities"]) <= set(new["entities"]):
            raise ValueError("Coverage cannot remove entity carriers")
        if any(p not in new["predicates"] for p in old["predicates"]):
            raise ValueError("Coverage cannot remove or change predicate carriers")
        if (old["cells"][0]["kind"], old["cells"][0]["granularity"]) != (
            new["cells"][0]["kind"],
            new["cells"][0]["granularity"],
        ):
            raise ValueError("Coverage cannot change time interpretation")
        if task["kind"] == "extend" and any(c not in new["cells"] for c in old["cells"]):
            raise ValueError("Extension must retain every existing cell")
        for entry in projected(checked, budget).values():
            budget.tick()
            cell = entry["cell"]
            if entry["projection"]["namespace"] != new["namespace"]:
                raise ValueError("Imported projection namespace requires a separate ADM")
            for candidate in new["cells"]:
                if cell["kind"] != candidate["kind"] or cell["granularity"] != candidate["granularity"]:
                    raise ValueError("Cannot reinterpret a retained time cell")
                if (
                    cell != candidate
                    and cell["kind"] == "interval"
                    and cell["effective_from"] < candidate["effective_to"]
                    and candidate["effective_from"] < cell["effective_to"]
                ):
                    raise ValueError("Cannot split or merge a retained fact cell")
        # Reuse support-only revision machinery; no declaration or historical result is removed.
        task = {
            **task,
            "operation": "source_dispute",
            "coverage": new,
            "all_sources": False,
            "superseded": [],
            "reason": "outside_selected_coverage",
        }
    if task["operation"] == "source_project":
        profile = Projection.model_validate(task["policy"]["projection"]).model_dump()
        existing = projected(checked, budget)
        declarations, artifacts, support, cells = {}, {}, {}, {}
        for row in task["claims"]:
            budget.tick()
            fact = FactClaim.model_validate(row["claim"]).model_dump()
            selected, reason = resolve(profile, fact)
            if reason or fact["status"] != "candidate":
                raise ValueError("Held claim cannot be projected")
            source = row["source"]
            record = source["record"]
            raw = source["content"].encode()
            if digest(raw) != record["content_digest"] or any(
                fact["source"][k] != record[k]
                for k in ("source_id", "item_id", "version_id", "content_digest")
            ):
                raise ValueError("Claim/source mismatch")
            source_note = evidence({"profile": "awm-adm-source-evidence/1", **source})
            skey = digest(encode(source_note))
            artifacts[skey] = source_note
            for cell in selected:
                matches = [
                    (name, prior)
                    for name, prior in existing.items()
                    if prior["claim"]["entity_id"] == fact["entity_id"]
                    and prior["claim"]["predicate"] == fact["predicate"]
                    and prior["cell"] == cell
                ]
                if len(matches) > 1:
                    raise ValueError("Ambiguous retained fact identity")
                identity_profile = matches[0][1]["projection"] if matches else profile
                if identity_profile["namespace"] != profile["namespace"]:
                    raise ValueError("Cannot reuse a fact from another projection namespace")
                symbol = (
                    matches[0][0]
                    if matches
                    else cell_symbol(profile, fact["entity_id"], fact["predicate"], cell)
                )
                body = declaration(profile, fact)
                if symbol in declarations:
                    raise ValueError("One selected claim per cell; review conflicts separately")
                if symbol in checked["model"].index and symbol not in existing:
                    raise ValueError("Projection symbol collides with an unrelated declaration")
                note = evidence(
                    {
                        "profile": "awm-adm-projected-fact/1",
                        "projection": identity_profile,
                        "claim": fact,
                        "cell": cell,
                        "source_policy": task["policy"],
                        "evidence_group": row["evidence_group"],
                        "source_evidence": skey,
                    }
                )
                nkey = digest(encode(note))
                artifacts[nkey] = note
                declarations[symbol], support[symbol] = body, [skey, nkey]
                cells[symbol] = {"claim": fact["claim_id"], "version": row["version_key"]}
        if len(set(existing) | set(cells)) > task["max_facts"]:
            raise ValueError("Projection fact bound exceeded")
        candidate = build_candidate(
            checked["model"],
            declarations,
            candidate_id=task["candidate_id"],
            evidence=list(artifacts.values()),
            evidence_by_symbol=support,
        )
        return {"package": transport(candidate), "preview": declarations, "cells": cells, "work": budget.used}
    if task["operation"] == "source_admit":
        current = validate_snapshot(unpack(task["current_snapshot"]), budget=budget)
        context = task["context"]
        instance = Instance(
            current["model"].document(), mode=context["mode"], policy=current["conformance"], budget=budget
        )
        instance._instance_id, instance._epoch = context["instance_id"], context["policy_epoch"]
        instance._sequence = task["receipt_sequence"] - 1
        instance._blobs, instance._support = dict(current["blobs"]), dict(current["support"])
        instance._lineage = thaw(current["lineage"])
        instance._models[checked["model"].version] = checked["model"]
        instance.receive(package(task["package"]), review_required=False)
        decision = instance.decide_next(budget=budget)
        result = {"status": decision["status"], "decision": thaw(decision["decision"]), "work": budget.used}
        if decision["status"] == "accepted":
            result.update(
                snapshot=pack(instance.export_snapshot(budget=budget)),
                context=instance.info(),
                symbols=list(instance._model.index),
            )
        return result
    if task["operation"] == "source_dispute":
        support, blobs = dict(checked["support"]), dict(checked["blobs"])
        affected = []
        for symbol, entry in projected(checked, budget).items():
            identity = entry["claim"]["source"]
            if task.get("coverage") and entry["cell"] in task["coverage"]["cells"]:
                continue
            if (
                not task.get("coverage")
                and not task.get("all_sources")
                and [identity["source_id"], identity["item_id"], identity["version_id"]]
                not in task["superseded"]
            ):
                continue
            budget.tick()
            affected.append(symbol)
            origin = thaw(read_json(blobs[support[symbol]]))
            note = evidence(
                {
                    "profile": "awm-adm-source-dispute/1",
                    "reason": task["reason"],
                    "previous_origin": support[symbol],
                }
            )
            nkey = digest(encode(note))
            blobs[nkey] = encode(note)
            origin["evidence"] = list(origin["evidence"]) + [nkey]
            okey = digest(encode(origin))
            blobs[okey] = encode(origin)
            support[symbol] = okey
        context = {
            **task["context"],
            "support_root": digest(encode(support)),
            "policy_epoch": task["context"]["policy_epoch"] + 1,
        }
        pinned = {
            "instance_id": context["instance_id"],
            "model": checked["model"],
            "policy": encode(checked["conformance"]),
            "blobs": blobs,
            "support": support,
            "lineage": checked["lineage"],
        }
        return {
            "snapshot": pack(export_instance(pinned, state=checked["state"], budget=budget)),
            "context": context,
            "affected": affected,
            "work": budget.used,
        }
    raise ValueError("Unknown source operation")


def query(checked, query, limits, budget):
    """Return None for ordinary supported queries, or a bound local fact result/hold."""
    model, entries = checked["model"], projected(checked, budget)
    reason, selected = None, None
    if query["op"] == "lookup_fact":
        matches = []
        for symbol, entry in entries.items():
            fact, cell = entry["claim"], entry["cell"]
            at = query["effective_at"]
            if (
                fact["entity_id"] == query["entity_id"]
                and fact["predicate"] == query["predicate"]
                and (
                    cell["effective_from"] == at
                    if cell["kind"] == "point"
                    else cell["effective_from"] <= at < cell["effective_to"]
                )
            ):
                matches.append((symbol, entry))
        if len(matches) != 1:
            reason = "unknown_or_ambiguous_scope"
        else:
            selected = matches[0]
            if selected[1]["disputed"]:
                reason = "disputed_source_support"
            else:
                symbol, entry = selected
                value = execute(
                    model,
                    {
                        "op": "evaluate",
                        "module": symbol.rsplit(".", 1)[0],
                        "expression": {"op": "call", "function": symbol, "args": {}},
                    },
                    limits,
                    budget=budget,
                )
                value.update(
                    fact={
                        "claim": entry["claim"],
                        "cell": entry["cell"],
                        "symbol": symbol,
                        "evidence_group": entry["evidence_group"],
                        "support_status": "active",
                    }
                )
                bind_result(
                    model.version,
                    query,
                    value,
                    [claim("computed_value", "local_interpreter")] if value["status"] == "succeeded" else [],
                )
                value["assurance"]["empirical_fidelity"] = "conditional_on_declared_sources"
                return value
    elif entries and query["op"] not in ("capabilities", "explain"):
        if query["op"] in ("evaluate", "check_claim"):
            roots = model.expression_dependencies(query.get("expression", query.get("proposition")))
        else:
            # Planning/certificate dependencies include all selected actions and goals.
            scope = query.get("certificate", query)
            roots = {scope.get("goal")} | set(scope.get("transitions") or model.index)
        required = set()
        for symbol in roots:
            budget.tick()
            if symbol in model.index:
                required.add(symbol)
                required.update(model.dependencies(symbol, transitive=True))
        if any(entries[s]["disputed"] for s in required & entries.keys()):
            reason = "disputed_source_support"
    if reason:
        value = {
            "status": "needs_input",
            "error": {"code": "needs_evidence", "message": reason},
            "unknown": True,
            "work": budget.used,
            "guarantee": None,
        }
        return bind_result(model.version, query, value, [])
    return None
