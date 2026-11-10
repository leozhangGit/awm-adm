"""Owner-authored feed capabilities. Source content cannot supply these fields."""

from typing import Literal, Self

from pydantic import Field, model_validator

from ..contracts import CallLimits, ClosedModel, Identifier
from ..sources.models import Predicate, Projection


class FeedBudget(ClosedModel):
    max_items: int = Field(default=20, ge=1, le=10000)
    max_calls: int = Field(default=20, ge=0, le=10000)
    max_input_tokens: int = Field(default=640000, ge=0, le=100000000)
    max_output_tokens: int = Field(default=163840, ge=0, le=100000000)
    max_work: int = Field(default=60000000, ge=1, le=1000000000)


class FeedInput(ClosedModel):
    idempotency_key: Identifier
    name: str = Field(min_length=1, max_length=128)
    expected_revision: Identifier
    expected_source_generation: int = Field(ge=1)
    source_ids: list[Identifier] = Field(min_length=1, max_length=100)
    enabled: bool = False
    requirements: list[Predicate] = Field(default_factory=list, max_length=32)
    publication: Literal["review", "checked_auto"] = "review"
    extractor: Literal["local", "external"] = "local"
    connection_id: Identifier | None = None
    connection_version: int | None = Field(default=None, ge=1)
    allow_external: bool = False
    after_sequence: int = Field(default=0, ge=0)
    budget: FeedBudget = Field(default_factory=FeedBudget)
    call_limits: CallLimits = Field(default_factory=CallLimits)
    max_pending: int = Field(default=4, ge=1, le=32)
    max_failures: int = Field(default=3, ge=1, le=20)
    retry_limit: int = Field(default=2, ge=0, le=5)
    backoff_seconds: int = Field(default=2, ge=1, le=300)

    @model_validator(mode="after")
    def explicit(self) -> Self:
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("Duplicate source identity")
        if self.extractor == "external":
            if not self.allow_external or not self.connection_id or self.connection_version is None:
                raise ValueError("External feeds require explicit disclosure and connection version")
        elif self.connection_id is not None or self.connection_version is not None or self.allow_external:
            raise ValueError("Local feeds do not disclose material")
        return self


class FeedControl(ClosedModel):
    expected_generation: int = Field(ge=1)
    expected_revision: Identifier
    enabled: bool


class Reprocess(ClosedModel):
    idempotency_key: Identifier
    expected_generation: int = Field(ge=1)
    source_sequence: int = Field(ge=1)


class CoverageInput(ClosedModel):
    expected_revision: Identifier
    expected_generation: int = Field(ge=1)
    kind: Literal["extend", "window"]
    projection: Projection
    reason: str = Field(min_length=1, max_length=1024)
