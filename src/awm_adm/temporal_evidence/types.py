"""Temporal scopes and local queries; independent of source/provider contracts."""

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from ..boundary import ClosedModel, Identifier, Instant, Symbol
from ..temporal import timezone_name


class Scope(ClosedModel):
    kind: Literal["instant", "occurrence", "validity", "period_value"]
    effective_from: Instant
    effective_to: Instant | None = None
    precision: Literal["second", "minute", "hour", "day", "month", "year", "window", "legacy"]
    timezone_basis: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def bounds(self) -> Self:
        for t in (self.effective_from, self.effective_to):
            if t:
                datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ")
        if self.timezone_basis != "legacy_unrecorded":
            timezone_name(self.timezone_basis)
        elif self.precision != "legacy":
            raise ValueError("Unrecorded zone is only a legacy compatibility view")
        if self.kind == "instant":
            if self.effective_to is not None or self.precision not in ("second", "legacy"):
                raise ValueError("An exact instant has second precision and no end")
        elif self.effective_to is None or self.effective_to <= self.effective_from:
            raise ValueError("Temporal windows must be bounded nonempty half-open intervals")
        return self


class Anchor(ClosedModel):
    kind: Literal["exact", "window", "unknown"] = "unknown"
    effective_from: Instant | None = None
    effective_to: Instant | None = None
    precision: Literal["second", "minute", "hour", "day", "month", "year", "window"] | None = None
    timezone_basis: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.kind == "unknown":
            if any(v is not None for k, v in self.model_dump().items() if k != "kind"):
                raise ValueError("Unknown time has no implied clock or precision")
        else:
            Scope.model_validate(
                {**self.model_dump(), "kind": "instant" if self.kind == "exact" else "occurrence"}
            )
        return self


class EvidenceQuery(ClosedModel):
    op: Literal["query_evidence"]
    intent: Literal["value_at", "value_throughout", "value_for_period", "observations_in", "reports_about"]
    entity_id: Identifier
    predicate: Symbol
    scope: Scope
    reported_time: Anchor | None = None
    relation: Literal["contained", "possibly_overlapping"] = "contained"
    limit: int = Field(default=100, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def intent_scope(self) -> Self:
        kind = {
            "value_at": "instant",
            "value_throughout": "validity",
            "value_for_period": "period_value",
        }.get(self.intent)
        if kind and (self.scope.kind != kind or self.cursor is not None or self.relation != "contained"):
            raise ValueError("Scalar intent requires its exact scope kind and no collection cursor")
        if not kind and self.scope.kind == "instant":
            raise ValueError("Collection search requires a bounded window")
        return self


class Selector(ClosedModel):
    entity_id: Identifier
    predicate: Symbol


class RecallQuery(ClosedModel):
    op: Literal["recall_evidence"]
    selectors: list[Selector] = Field(min_length=1, max_length=32)
    limit: int = Field(default=100, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def unique(self) -> Self:
        pairs = [(s.entity_id, s.predicate) for s in self.selectors]
        if len(set(pairs)) != len(pairs):
            raise ValueError("Duplicate recall selector")
        return self
