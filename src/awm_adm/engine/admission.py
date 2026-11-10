"""Finite candidate reconciliation against one immutable active theory and policy."""

from collections.abc import Mapping

from .data import encode, name, read_json, shape, thaw
from .errors import InvalidIR, Rejected
from .model import admit, declaration_references


def dependent_closure(model, roots, budget):
    reverse = {}
    for symbol in model.index:
        budget.tick()
        for dependency in model.dependencies(symbol):
            reverse.setdefault(dependency, set()).add(symbol)
    found, pending = set(roots), list(roots)
    while pending:
        budget.tick()
        for symbol in reverse.get(pending.pop(), ()):
            if symbol not in found:
                found.add(symbol)
                pending.append(symbol)
    return found


def reconcile(envelope, blobs, base, current, mode, budget):
    declarations, evidence, dependencies = {}, {}, {}
    proposed = {p["symbol"] for p in envelope["proposals"]}
    for entry in envelope["attachments"]:
        budget.tick()
        if entry["role"] == "evidence":
            value = thaw(read_json(blobs[entry["digest"]]))
            shape(value, ("artifact_kind", "evidence_kind", "origin", "scope", "content"), ("checks",))
            if value["artifact_kind"] != "evidence" or value["evidence_kind"] not in (
                "synthetic_fixture",
                "provider_statement",
                "observation",
            ):
                raise InvalidIR("Unsupported evidence kind")
            if any(not isinstance(value[key], str) or not value[key] for key in ("origin", "scope")):
                raise InvalidIR("Evidence origin and scope must be nonempty strings")
            checks = value.get("checks", [])
            if not isinstance(checks, list):
                raise InvalidIR("Evidence checks must be an array")
            for check in checks:
                shape(check, ("expression", "expected"))
            evidence[entry["digest"]] = value
    if not evidence:
        raise Rejected("A candidate needs explicit evidence provenance, including for retractions")
    for proposal in envelope["proposals"]:
        budget.tick()
        value = thaw(read_json(blobs[proposal["artifact"]]))
        shape(value, ("artifact_kind", "profile", "symbol", "dependencies", "evidence", "body"))
        if (
            value["artifact_kind"] != "declaration"
            or value["profile"] != "finite-v0"
            or value["symbol"] != proposal["symbol"]
        ):
            raise InvalidIR("Declaration metadata differs from its proposal")
        if not isinstance(value["body"], Mapping) or not isinstance(value["dependencies"], Mapping):
            raise InvalidIR("Declaration body and dependencies must be objects")
        refs = value["evidence"]
        if (
            not isinstance(refs, list)
            or not refs
            or any(not isinstance(key, str) or key not in evidence for key in refs)
        ):
            raise InvalidIR("Declaration requires attached evidence")
        expected = declaration_references(value["body"]) - proposed
        if set(value["dependencies"]) != expected:
            raise InvalidIR("Declaration must identify every external syntactic dependency exactly")
        for symbol, key in value["dependencies"].items():
            name(symbol, qualified=True)
            if base.index.get(symbol) != key:
                raise Rejected("Dependency does not match the construction base", symbol=symbol)
            if current.index.get(symbol) != key:
                raise Rejected(
                    "Candidate dependency is stale; reconstruct against the active theory", symbol=symbol
                )
        dependencies.update(value["dependencies"])
        declarations[proposal["symbol"]] = value["body"]
    expected_artifacts = {p["artifact"] for p in envelope["proposals"]}
    supplied_artifacts = {e["digest"] for e in envelope["attachments"] if e["role"] == "declaration"}
    if expected_artifacts != supplied_artifacts:
        raise InvalidIR("Unproposed declaration attachment")

    before = current.document()["declarations"]
    base_symbols = {key: symbol for symbol, key in base.index.items()}
    retracted = set()
    for key in envelope["retractions"]:
        budget.tick()
        if key not in base_symbols:
            raise Rejected("Retraction is not a declaration in the construction base", artifact=key)
        symbol = base_symbols[key]
        active = current.index.get(symbol)
        if active is not None and active != key:
            raise Rejected("Retraction refers to a superseded declaration", symbol=symbol)
        if active is not None:
            retracted.add(symbol)
    replacements = {s for s in declarations if s in before and encode(declarations[s]) != encode(before[s])}
    roots = replacements | retracted
    if mode == "backward" and roots:
        raise Rejected(
            "Backward mode retains earlier content; the whole batch is rejected",
            conflicts=sorted(roots),
            mode=mode,
        )
    affected = dependent_closure(current, roots, budget)
    removed = affected - declarations.keys()
    combined = {s: body for s, body in before.items() if s not in affected}
    combined.update(declarations)
    admission = admit({"profile": "finite-v0", "declarations": combined}, budget=budget)
    report = {
        "conflicts": sorted(roots),
        "proposed_retirements": {s: current.index[s] for s in sorted(affected)},
        "proposed_removals": sorted(removed),
        "external_dependencies": dependencies,
        "evidence": sorted(evidence),
        "admission": admission.report,
        "scope": "Checked finite definitions and supplied observation checks; empirical truth is not established.",
    }
    if admission.model is None:
        return admission.status, None, report, set()
    observations = []
    for key, item in sorted(evidence.items()):
        for check in item.get("checks", []):
            actual = admission.model.evaluate(check["expression"], budget=budget)["value"]
            if encode(actual) != encode(check["expected"]):
                raise Rejected(
                    "Candidate disagrees with a supplied observation check",
                    evidence=key,
                    expression=check["expression"],
                    expected=check["expected"],
                    actual=actual,
                )
            observations.append({"evidence": key, "expression": check["expression"], "value": actual})
    report["observation_checks"] = observations
    report["retired"] = report.pop("proposed_retirements")
    report["removed"] = report.pop("proposed_removals")
    report["work"] = budget.used
    after = admission.model.index
    changed = {s for s in current.index.keys() | after.keys() if current.index.get(s) != after.get(s)}
    return "accepted", admission.model, report, changed
