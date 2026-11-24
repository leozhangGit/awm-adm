"""Bounded preparation assessment, separate from model/source validation."""

from typing import Literal

from pydantic import Field

from ..contracts import ClosedModel, Identifier
from .diagnostics import PreparationError

TEMPORAL_PROFILE = "awm-adm-teaching-reply/6"
LEGACY_PROFILE = "awm-adm-teaching-reply/7"


class Gap(ClosedModel):
    kind: Literal[
        "meaning",
        "entity",
        "unit",
        "representation_bounds",
        "temporal_scope",
        "source_material",
        "revision_target",
        "adoption_intent",
        "other",
    ]
    input_ids: list[Identifier] = Field(min_length=1, max_length=4)
    subject: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=1000)


class Limitation(ClosedModel):
    kind: Literal["unsupported_operation", "unsupported_representation", "unbounded_domain", "resource_limit"]
    input_ids: list[Identifier] = Field(min_length=1, max_length=4)
    requested_capability: str = Field(min_length=1, max_length=300)
    limitation: str = Field(min_length=1, max_length=1000)


class Assessment(ClosedModel):
    profile: str
    message: str = Field(min_length=1, max_length=2000)
    missing_information: list[Gap] = Field(max_length=8)
    unsupported_capabilities: list[Limitation] = Field(max_length=4)
    question: str | None = Field(min_length=1, max_length=2000)


INSTRUCTIONS = """Assess readiness using structured missing_information and unsupported_capabilities;
do not emit a status field. Consider whether supplying missing meaning or evidence
would allow this objective to fit the available representation. If so, report that
information gap, not an unsupported capability. This applies to entities, units,
representation bounds, temporal scope, source material, revision targets, adoption
intent and other missing meaning. Do not invent the missing information.

For missing information: plan null, unsupported_capabilities [], one to eight
missing_information items, and one concise natural-language question asking for
the necessary clarification. Each item identifies its kind, exact input_ids,
subject and missing detail. Group related gaps into one focused question. Do not
ask users to provide internal source mappings, identifiers or repair schema fields.
Use established context when it already resolves a gap; do not ask again routinely.

For an unsupported capability: plan null, missing_information [], question null,
and one to four unsupported_capabilities items. Each names exact input_ids,
requested_capability, the concrete limitation and its kind: unsupported_operation,
unsupported_representation, unbounded_domain or resource_limit. This means the
requested capability itself exceeds the available contract, even with necessary
information supplied. Missing values alone are not representation limitations.
If missing information prevents deciding representability, clarify it first; do
not list contradictory assessments or guess that the capability is impossible.

For ready: a complete plan, both lists empty, question null. The message summarizes
the proposal, needed clarification or concrete limitation; it is never a routing
instruction. The service derives the outcome from these fields. All proposals still
undergo unchanged local model/source checks. No partial plan can publish, and no
assessment authorizes changing settings, expanding scope or retrying a failed call.
"""


def normalize(value, input_ids):
    """Validate the new envelope and route without parsing explanatory prose."""
    gaps, limits = value["missing_information"], value["unsupported_capabilities"]
    plan, question = value["plan"], value["question"]
    if gaps and limits:
        raise PreparationError("assessment", "conflicting_assessments")
    if gaps:
        if plan is not None or question is None or not question.strip():
            raise PreparationError("assessment", "missing_information_requires_question")
        kind, status = "missing_information", "needs_clarification"
    elif limits:
        if plan is not None or question is not None:
            raise PreparationError("assessment", "unsupported_requires_no_plan")
        kind, status = "unsupported_capability", "unsupported"
    else:
        if plan is None or question is not None:
            raise PreparationError("assessment", "ready_requires_plan")
        kind, status = "ready", "ready"
    for item in [*gaps, *limits]:
        ids = item["input_ids"]
        if len(ids) != len(set(ids)) or not set(ids) <= set(input_ids):
            raise PreparationError("assessment", "unknown_assessment_input")
        if any(isinstance(v, str) and not v.strip() for v in item.values()):
            raise PreparationError("assessment", "empty_assessment_detail")
    assessment = {
        "profile": "awm-adm-preparation-assessment/1",
        "kind": kind,
        "missing_information": gaps,
        "unsupported_capabilities": limits,
        "question": question,
        "classification_authority": "provider_proposed",
    }
    return {
        "status": status,
        "message": question if gaps else value["message"],
        "plan_json": None,
        "assessment": assessment,
    }
