"""Cold verification of temporal bindings and cross-profile semantic consistency."""

from ..contracts import SourceRecord
from ..engine.artifacts import digest
from ..engine.data import encode, read_json, thaw
from ..engine.errors import InvalidIR
from ..sources.models import Projection
from .identity import address, descriptor_key, property_key, relation, resolve, scope_key
from .legacy import entry as legacy_entry
from .legacy import scope as legacy_scope
from .legacy import series as legacy_series
from .models import BINDING, Catalog, Claim


def symbol_for(namespace, fact, series):
    return namespace + ".fact_" + address(fact, series).split(":")[1][:40]


def read(checked, budget, legacy):
    from ..sources.compute import cell_symbol, declaration

    result = {s: legacy_entry(s, e) for s, e in legacy.items()}
    for symbol, key in checked["support"].items():
        budget.tick()
        origin = thaw(read_json(checked["blobs"][key]))
        notes = [thaw(read_json(checked["blobs"][k]))["content"] for k in origin["evidence"]]
        entries = [
            n
            for n in notes
            if isinstance(n, dict) and str(n.get("profile", "")).startswith("awm-adm-temporal-binding/")
        ]
        if not entries:
            continue
        if len(entries) != 1 or symbol in legacy:
            raise InvalidIR("Ambiguous temporal support")
        e = entries[0]
        if (
            set(e)
            != {
                "profile",
                "projection",
                "claim",
                "cell",
                "descriptor_digest",
                "address",
                "source_evidence",
                "evidence_group",
                "legacy_bridge",
            }
            or e["profile"] != BINDING
        ):
            raise InvalidIR("Unsupported temporal binding")
        p = Catalog.model_validate(e["projection"]).model_dump()
        f = Claim.model_validate(e["claim"]).model_dump()
        cells, reason = resolve(p, f)
        if reason or f["status"] != "candidate" or e["cell"] not in cells:
            raise InvalidIR("Invalid temporal projection")
        s = next(p for p in p["predicates"] if p["symbol"] == f["predicate"])
        if e["descriptor_digest"] != descriptor_key(s) or e["address"] != address(f, s):
            raise InvalidIR("Temporal semantic binding mismatch")
        expected_symbol = symbol_for(p["namespace"], f, s)
        bridge = e["legacy_bridge"]
        if bridge is not None:
            if set(bridge) != {"projection", "cell"}:
                raise InvalidIR("Invalid legacy address bridge")
            old = Projection.model_validate(bridge["projection"]).model_dump()
            old_pred = next((p for p in old["predicates"] if p["symbol"] == f["predicate"]), None)
            if (
                old_pred is None
                or legacy_series(old_pred) != s
                or old["namespace"] != p["namespace"]
                or bridge["cell"] not in old["cells"]
                or f["entity_id"] not in old["entities"]
                or scope_key(legacy_scope(bridge["cell"])) != scope_key(f["temporal_scope"])
            ):
                raise InvalidIR("Legacy bridge changes the retained meaning")
            expected_symbol = cell_symbol(old, f["entity_id"], f["predicate"], bridge["cell"])
        if expected_symbol != symbol:
            raise InvalidIR("Temporal declaration identity mismatch")
        source_key = e["source_evidence"]
        if source_key not in origin["evidence"]:
            raise InvalidIR("Missing original temporal source")
        source = thaw(read_json(checked["blobs"][source_key]))["content"]
        if source.get("profile") != "awm-adm-source-evidence/1":
            raise InvalidIR("Invalid temporal source profile")
        record = SourceRecord.model_validate(source["record"]).model_dump()
        raw = source["content"].encode()
        span = f["source"]
        if (
            digest(raw) != record["content_digest"]
            or len(raw) != record["byte_count"]
            or any(span[k] != record[k] for k in ("source_id", "item_id", "version_id", "content_digest"))
            or span["end_byte"] > len(raw)
        ):
            raise InvalidIR("Temporal original/span identity mismatch")
        raw[: span["start_byte"]].decode()
        raw[span["start_byte"] : span["end_byte"]].decode()
        raw[span["end_byte"] :].decode()
        if encode(checked["model"].document()["declarations"][symbol]) != encode(declaration(p, f)):
            raise InvalidIR("Temporal metadata differs from executable value")
        result[symbol] = {
            **e,
            "symbol": symbol,
            "series": s,
            "legacy": None,
            "disputed": any(
                isinstance(n, dict) and n.get("profile") == "awm-adm-source-dispute/1" for n in notes
            ),
        }
    validate_consistency(result, budget)
    return result


def validate_consistency(entries, budget):
    rows = list(entries.values())
    if all(e.get("legacy") is not None for e in rows):
        return
    for i, a in enumerate(rows):
        for b in rows[:i]:
            if a.get("legacy") is not None and b.get("legacy") is not None:
                continue
            budget.tick()
            if a["claim"]["predicate"] == b["claim"]["predicate"] and a["series"] != b["series"]:
                raise InvalidIR("Conflicting semantic descriptors for one predicate")
            if property_key(a["claim"], a["series"]) != property_key(b["claim"], b["series"]):
                continue
            r = relation(a["claim"], a["series"], b["claim"], b["series"])
            if r in ("same", "overlap") and a["claim"]["value"] != b["claim"]["value"]:
                raise InvalidIR("Conflicting temporal assertions in accepted support")
