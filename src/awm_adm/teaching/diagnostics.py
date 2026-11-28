"""Bounded checker diagnostics; never echo provider values or exception text."""

import json

from pydantic import ValidationError

MESSAGES = {
    "reaffirmation": "The proposed reaffirmation does not match reusable accepted declarations.",
    "wire": "The provider returned malformed preparation JSON.",
    "envelope": "The provider response does not match the preparation format.",
    "assessment": "The provider's readiness assessment is inconsistent or invalid. No learning started.",
    "plan_json": "The provider returned malformed JSON inside the teaching plan.",
    "plan": "The proposed teaching plan has invalid or missing fields.",
    "types": "The proposed finite types are invalid, cyclic or outside the supported bounds.",
    "interfaces": "The proposed capability headers do not match the local interface format.",
    "inputs": "The proposal does not preserve the exact supplied teaching inputs.",
    "dependencies": "The proposed capability dependencies are cyclic.",
    "vocabulary": "The proposed vocabulary does not refer to valid model capabilities or parameters.",
    "sources": "The proposed source coverage or permissions are invalid.",
    "materials": "The preparation could not bind the selected supplied material. No knowledge was accepted.",
    "requirements": "The proposed requirements are invalid or would replace installed owner checks.",
}


class PreparationError(ValueError):
    def __init__(self, stage, code="invalid_value"):
        self.diagnostic = diagnostic(stage, code)
        super().__init__(self.diagnostic["message"])


def length_details(issue):
    """Measure JSON values internally; expose only counts and trusted bounds."""
    code, value = issue["type"], issue.get("input")
    if code in {"string_too_long", "string_too_short"} and type(value) is str:
        unit = "characters"
    elif code in {"too_long", "too_short"} and type(value) in (list, dict):
        unit = "items"
    else:
        return {}
    bound = "max_length" if code.endswith("long") else "min_length"
    limit = issue.get("ctx", {}).get(bound)
    if type(limit) is not int or not 0 <= limit <= 2**31 - 1:
        return {}
    return {"actual_length": len(value), bound: limit, "unit": unit}


def diagnostic(stage, code="invalid_value", error=None):
    result = {"stage": stage, "code": code, "message": MESSAGES[stage], "issues": []}
    if stage == "reaffirmation":
        result["message"] = {
            "unknown_reuse_symbol": "Reaffirmation must select existing accepted declarations; an unknown symbol cannot be reused.",
            "overlapping_reuse": "A declaration cannot be reaffirmed twice or also changed by another child in the same teaching plan.",
            "unsupported_reuse_kind": "This declaration kind cannot be reaffirmed through teaching preparation.",
        }.get(code, result["message"])
    if stage == "sources":
        result["message"] = {
            "multiple_projections": "The provider proposed different evidence mappings within one teaching request. One shared mapping is required; no new knowledge was accepted.",
            "shared_projection_required": "The provider selected source material without the required shared evidence mapping. No new knowledge was accepted.",
            "unused_shared_projection": "The provider proposed an evidence mapping without selecting source material. No new knowledge was accepted.",
        }.get(code, result["message"])
    if isinstance(error, ValidationError):
        # Locations may contain attacker-authored map keys. Keep schema fields
        # and indexes only. Values/context are inspected for numeric length
        # diagnostics but never copied into the returned packet or message.
        fields = {
            "profile",
            "status",
            "message",
            "plan",
            "missing_information",
            "unsupported_capabilities",
            "question",
            "subject",
            "detail",
            "requested_capability",
            "limitation",
            "kind",
            "summary",
            "children",
            "objective",
            "input_ids",
            "interfaces",
            "reuse_symbols",
            "material",
            "material_ids",
            "projection",
            "source_projection",
            "evidence_scope",
            "precision",
            "timezone_basis",
            "statement_level",
            "actor",
            "modality",
            "qualifiers",
            "scope_kinds",
            "metric",
            "meaning",
            "reported_time",
            "observed_time",
            "occurrence_id",
            "sources",
            "namespace",
            "entities",
            "predicates",
            "cells",
            "symbol",
            "unit",
            "minimum",
            "maximum",
            "values",
            "effective_from",
            "effective_to",
            "granularity",
            "source_id",
            "attribution",
            "evidence_group",
            "allow_external",
            "types",
            "id",
            "members",
            "name",
            "type_id",
            "element_id",
            "length",
            "params",
            "returns_id",
            "state_id",
            "parameters_id",
            "aliases",
            "alias",
            "targets",
            "parameters",
            "parameter",
            "role",
            "value_aliases",
            "value_json",
            "requirements_json",
            "vocabulary",
            "requirements",
            "plan_json",
        }
        for issue in error.errors(include_url=False, include_input=True, include_context=True)[:8]:
            if stage == "sources" and "evidence_scope" in issue["loc"]:
                result["message"] = (
                    "The proposed temporal evidence catalog has invalid fields. No knowledge was accepted."
                )
            result["issues"].append(
                {
                    "path": [
                        v if isinstance(v, int) or v in fields else "<field>" for v in issue["loc"][:12]
                    ],
                    "code": issue["type"][:64],
                    **length_details(issue),
                }
            )
            if issue["type"] == "value_error":
                # Only exact service-authored validation messages map to fixed safe hints.
                reason = str(issue.get("ctx", {}).get("error", ""))
                rules = {
                    "Each child needs an interface or finite source mapping": (
                        "empty_teaching_child",
                        "A teaching child must specify executable interfaces, source material, or explicit checked reaffirmation of accepted declarations.",
                    ),
                    "A capability needs receiver interfaces": (
                        "capability_interfaces_required",
                        "A capability child needs executable interfaces; unchanged accepted rules use reaffirmation.",
                    ),
                    "Observations require a source mapping, not executable rules": (
                        "facts_mapping_required",
                        "A facts child needs a source mapping and no executable interfaces.",
                    ),
                    "Reaffirmation needs existing symbols and no interfaces or source mapping": (
                        "reaffirmation_shape",
                        "Reaffirmation requires reuse_symbols with existing declarations, empty interfaces and no source mapping.",
                    ),
                    "Reaffirmation symbols must be unique": (
                        "duplicate_reuse_symbol",
                        "Select each accepted declaration only once.",
                    ),
                    "Only reaffirmation can select reuse symbols": (
                        "unexpected_reuse_symbols",
                        "Only a reaffirmation child can select reuse_symbols.",
                    ),
                    "Parent intent must match its typed children": (
                        "plan_kind_mismatch",
                        "The plan kind must match its children; different child kinds require mixed.",
                    ),
                }
                if reason in rules:
                    rule, hint = rules[reason]
                    result["issues"][-1].update(rule=rule, hint=hint)
                    result["message"] = hint
            path = result["issues"][-1]["path"]
            # Fixed contract hints only: never interpolate provider values or
            # validator messages. Keep retained non-temporal diagnostics stable.
            if "evidence_scope" in path:
                if "predicates" in path and path[-1] == "symbol":
                    result["issues"][-1].update(
                        rule="qualified_predicate_symbol",
                        hint="Use a complete dot-qualified predicate symbol; the namespace does not add a prefix.",
                    )
                elif "cells" in path:
                    result["issues"][-1].update(
                        rule="temporal_scope_contract",
                        hint=(
                            "Use canonical UTC bounds and an IANA timezone. An exact instant has "
                            "second precision and no end; other kinds require a supported end after "
                            "the start. Preserve uncertain time as a window; do not invent bounds."
                        ),
                    )
        for issue in result["issues"]:
            if "actual_length" in issue:
                bound = "max_length" if "max_length" in issue else "min_length"
                comparison = "maximum" if bound == "max_length" else "minimum"
                result["message"] += (
                    f" A generated field has {issue['actual_length']} {issue['unit']}; "
                    f"the {comparison} is {issue[bound]}."
                )
                break
    cause = error
    while cause is not None:
        if isinstance(cause, json.JSONDecodeError):
            result["position"] = {"line": cause.lineno, "column": cause.colno, "offset": cause.pos}
            break
        cause = cause.__cause__
    return result
