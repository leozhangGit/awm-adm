"""Bounded checker diagnostics; never echo provider values or exception text."""

import json

from pydantic import ValidationError

MESSAGES = {
    "wire": "The provider returned malformed preparation JSON.",
    "envelope": "The provider response does not match the preparation format.",
    "plan_json": "The provider returned malformed JSON inside the teaching plan.",
    "plan": "The proposed teaching plan has invalid or missing fields.",
    "types": "The proposed finite types are invalid, cyclic or outside the supported bounds.",
    "interfaces": "The proposed capability headers do not match the local interface format.",
    "inputs": "The proposal does not preserve the exact supplied teaching inputs.",
    "dependencies": "The proposed capability dependencies are cyclic.",
    "vocabulary": "The proposed vocabulary does not refer to valid model capabilities or parameters.",
    "sources": "The proposed source coverage or permissions are invalid.",
    "requirements": "The proposed requirements are invalid or would replace installed owner checks.",
}


class PreparationError(ValueError):
    def __init__(self, stage, code="invalid_value"):
        self.diagnostic = diagnostic(stage, code)
        super().__init__(self.diagnostic["message"])


def diagnostic(stage, code="invalid_value", error=None):
    result = {"stage": stage, "code": code, "message": MESSAGES[stage], "issues": []}
    if isinstance(error, ValidationError):
        # Locations may contain attacker-authored map keys. Keep schema fields
        # and indexes only, not input values, validator context or raw messages.
        fields = {
            "profile",
            "status",
            "message",
            "plan",
            "kind",
            "summary",
            "children",
            "objective",
            "input_ids",
            "interfaces",
            "material",
            "projection",
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
            result["issues"].append(
                {
                    "path": [
                        v if isinstance(v, int) or v in fields else "<field>" for v in issue["loc"][:12]
                    ],
                    "code": issue["type"][:64],
                }
            )
    cause = error
    while cause is not None:
        if isinstance(cause, json.JSONDecodeError):
            result["position"] = {"line": cause.lineno, "column": cause.colno, "offset": cause.pos}
            break
        cause = cause.__cause__
    return result
