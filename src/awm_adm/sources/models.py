"""Source text is data. Only these owner endpoints grant extraction/publication authority."""

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from ..contracts import (
    CallLimits,
    ClosedModel,
    FactValue,
    Identifier,
    Module,
    Symbol,
    TemporalScope,
)


class Predicate(ClosedModel):
    symbol: Symbol
    kind: Literal["boolean", "integer", "enum"]
    unit: str = Field(min_length=1, max_length=100)
    minimum: int = Field(default=0, ge=-9007199254740991, le=9007199254740991)
    maximum: int = Field(default=100, ge=-9007199254740991, le=9007199254740991)
    values: list[str] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def carrier(self) -> Self:
        if self.minimum > self.maximum or self.maximum - self.minimum > 1000000:
            raise ValueError("Invalid bounded integer carrier")
        if self.kind == "enum" and (not self.values or len(set(self.values)) != len(self.values)):
            raise ValueError("Enum requires unique finite values")
        if any(not v or len(v) > 200 for v in self.values):
            raise ValueError("Invalid enum value")
        if self.kind != "enum" and self.values:
            raise ValueError("Only enums have named values")
        return self


class Projection(ClosedModel):
    profile: Literal["awm-adm-projection/1"] = "awm-adm-projection/1"
    namespace: Module
    entities: list[Identifier] = Field(min_length=1, max_length=128)
    predicates: list[Predicate] = Field(min_length=1, max_length=32)
    cells: list[TemporalScope] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def finite_grid(self) -> Self:
        if len(set(self.entities)) != len(self.entities) or len({p.symbol for p in self.predicates}) != len(
            self.predicates
        ):
            raise ValueError("Duplicate entity or predicate")
        kind, granularity = self.cells[0].kind, self.cells[0].granularity
        if kind == "unknown":
            raise ValueError("Owner time carrier must be explicit")
        prior = None
        for cell in self.cells:
            if cell.kind != kind or cell.granularity != granularity:
                raise ValueError("Use one time carrier kind and granularity")
            if kind == "interval" and cell.effective_to is None:
                raise ValueError("Projection coverage must be bounded")
            for bound in (cell.effective_from, cell.effective_to):
                if bound:
                    instant = datetime.fromisoformat(bound.replace("Z", "+00:00"))
                    if granularity in ("day", "year") and (instant.hour or instant.minute or instant.second):
                        raise ValueError("Time boundary is not aligned to granularity")
                    if granularity == "year" and (instant.month != 1 or instant.day != 1):
                        raise ValueError("Year boundary must be January 1")
            if prior and (cell.effective_from < prior or (kind == "point" and cell.effective_from == prior)):
                raise ValueError("Cells must be ordered and disjoint")
            prior = cell.effective_to if kind == "interval" else cell.effective_from
        return self


class SourcePermission(ClosedModel):
    source_id: Identifier
    attribution: str = Field(min_length=1, max_length=1024)
    evidence_group: Identifier
    allow_external: bool = False


class PolicyInput(ClosedModel):
    expected_revision: Identifier
    expected_generation: int = Field(ge=0)
    projection: Projection | None
    sources: list[SourcePermission] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({s.source_id for s in self.sources}) != len(self.sources):
            raise ValueError("Duplicate source permission")
        return self


class SourceInput(ClosedModel):
    source_id: Identifier
    item_id: Identifier
    version_id: Identifier
    media_type: Literal["text/plain", "text/markdown", "application/json", "application/x-ndjson"]
    content: str = Field(min_length=1, max_length=2097152)
    origin: str = Field(min_length=1, max_length=4096)
    supersedes_version: Identifier | None = None

    @model_validator(mode="after")
    def utf8(self) -> Self:
        self.content.encode("utf-8")
        return self


class BatchInput(ClosedModel):
    idempotency_key: Identifier
    items: list[SourceInput] = Field(min_length=1, max_length=1000)


class ExtractedFact(ClosedModel):
    entity_id: Identifier
    predicate: Symbol
    value: FactValue
    unit: str = Field(min_length=1, max_length=100)
    temporal_scope: TemporalScope
    assertion_kind: Literal["assertion", "quotation", "hypothetical", "negation"]


class SpannedFact(ExtractedFact):
    start_byte: int = Field(ge=0)
    end_byte: int = Field(ge=1)


class ExtractionOutput(ClosedModel):
    claims: list[SpannedFact] = Field(max_length=100)


class JobInput(ClosedModel):
    allowance_id: Identifier | None = None
    reprocess_id: Identifier | None = None
    idempotency_key: Identifier
    expected_revision: Identifier
    expected_generation: int = Field(ge=0)
    source_id: Identifier
    item_id: Identifier
    version_id: Identifier
    purpose: Literal["claims", "schema"] = "claims"
    extractor: Literal["local", "external"] = "local"
    connection_id: Identifier | None = None
    connection_version: int | None = Field(default=None, ge=1)
    call_limits: CallLimits = Field(default_factory=CallLimits)

    @model_validator(mode="after")
    def explicit(self) -> Self:
        if (self.extractor == "external") != (
            self.connection_id is not None and self.connection_version is not None
        ):
            raise ValueError("External extraction requires an explicit connection version")
        if self.extractor == "local" and (
            self.connection_id is not None or self.connection_version is not None
        ):
            raise ValueError("Local extraction does not use a connection")
        return self


class ProjectionInput(ClosedModel):
    idempotency_key: Identifier
    expected_revision: Identifier
    expected_generation: int = Field(ge=1)
    claim_ids: list[Identifier] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len(set(self.claim_ids)) != len(self.claim_ids):
            raise ValueError("Duplicate claim selection")
        return self
