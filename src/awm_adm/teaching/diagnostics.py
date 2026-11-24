"""Bounded checker diagnostics; never echo provider values or exception text."""

import json

from pydantic import ValidationError

MESSAGES = {
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


def diagnostic(stage, code="invalid_value", error=None):
    result = {"stage": stage, "code": code, "message": MESSAGES[stage], "issues": []}
    if stage == "sources":
        result["message"] = {
            "multiple_projections": "The provider proposed different evidence mappings within one teaching request. One shared mapping is required; no new knowledge was accepted.",
            "shared_projection_required": "The provider selected source material without the required shared evidence mapping. No new knowledge was accepted.",
            "unused_shared_projection": "The provider proposed an evidence mapping without selecting source material. No new knowledge was accepted.",
        }.get(code, result["message"])
    if isinstance(error, ValidationError):
        # Locations may contain attacker-authored map keys. Keep schema fields
        # and indexes only, not input values, validator context or raw messages.
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
        for issue in error.errors(include_url=False, include_input=False, include_context=False)[:8]:
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
                }
            )
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
    cause = error
    while cause is not None:
        if isinstance(cause, json.JSONDecodeError):
            result["position"] = {"line": cause.lineno, "column": cause.colno, "offset": cause.pos}
            break
        cause = cause.__cause__
    return result
