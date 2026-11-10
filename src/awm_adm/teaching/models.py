"""Closed local preparation proposals and the historical provider envelope."""

from typing import Literal, Self

from pydantic import Field, model_validator

from ..contracts import ClosedModel, Identifier
from ..language.models import Vocabulary
from ..sources.models import Projection, SourcePermission


class Material(ClosedModel):
    projection: Projection
    sources: list[SourcePermission] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def permissions(self) -> Self:
        if len({s.source_id for s in self.sources}) != len(self.sources):
            raise ValueError("Source identities must be unique")
        # Preparation cannot infer disclosure consent from supplied material.
        if any(s.allow_external for s in self.sources):
            raise ValueError("External source disclosure requires a separate owner decision")
        if (
            len(self.projection.entities) * len(self.projection.predicates) * len(self.projection.cells)
            > 4096
        ):
            raise ValueError("Narrow source coverage to at most 4096 finite cells")
        return self


class Child(ClosedModel):
    kind: Literal["capability", "facts", "correction"]
    objective: str = Field(min_length=1, max_length=2000)
    input_ids: list[Identifier] = Field(min_length=1, max_length=4)
    interfaces: dict = Field(default_factory=dict, max_length=32)
    material: Material | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        if not self.interfaces and self.material is None:
            raise ValueError("Each child needs an interface or finite source mapping")
        if self.kind == "capability" and not self.interfaces:
            raise ValueError("A capability needs receiver interfaces")
        if self.kind == "facts" and (self.material is None or self.interfaces):
            raise ValueError("Observations require a source mapping, not executable rules")
        return self


class Plan(ClosedModel):
    profile: Literal["awm-adm-teaching-plan/1"] = "awm-adm-teaching-plan/1"
    kind: Literal["capability", "facts", "correction", "mixed"]
    summary: str = Field(min_length=1, max_length=2000)
    children: list[Child] = Field(min_length=1, max_length=4)
    vocabulary: Vocabulary = Field(default_factory=Vocabulary)
    requirements: dict | None = None

    @model_validator(mode="after")
    def kinds(self) -> Self:
        kinds = {c.kind for c in self.children}
        if (self.kind == "mixed" and len(kinds) < 2) or (self.kind != "mixed" and kinds != {self.kind}):
            raise ValueError("Parent intent must match its typed children")
        return self


class Reply(ClosedModel):
    """Legacy prompt /1 and /2 only; native replies live in provider_format."""

    status: Literal["ready", "needs_clarification", "unsupported"]
    message: str = Field(min_length=1, max_length=2000)
    plan_json: str | None = Field(max_length=65536)

    @model_validator(mode="after")
    def shape(self) -> Self:
        if (self.status == "ready") != (self.plan_json is not None):
            raise ValueError("Only a ready proposal contains a plan")
        return self


REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ready", "needs_clarification", "unsupported"]},
        "message": {"type": "string"},
        "plan_json": {"type": ["string", "null"]},
    },
    "required": ["status", "message", "plan_json"],
    "additionalProperties": False,
}
