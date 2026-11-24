"""Closed, bounded temporal evidence contracts; no storage or provider authority."""

from typing import Literal, Self

from pydantic import Field, model_validator

from ..contracts import ClosedModel, FactValue, Identifier, Module, SourceSpan, Symbol
from ..sources.carriers import Predicate
from .types import Anchor, EvidenceQuery, Scope  # noqa: F401

CATALOG = "awm-adm-temporal-catalog/1"
CLAIM = "awm-adm-temporal-claim/1"
BINDING = "awm-adm-temporal-binding/1"
KINDS = ("instant", "occurrence", "validity", "period_value")


class Qualifier(ClosedModel):
    name: Identifier
    value: str = Field(min_length=1, max_length=200)


class Series(Predicate):
    meaning: str = Field(min_length=1, max_length=1000)
    statement_level: Literal["direct", "reported"] = "direct"
    actor: str | None = Field(default=None, min_length=1, max_length=200)
    modality: str | None = Field(default=None, min_length=1, max_length=100)
    qualifiers: list[Qualifier] = Field(default_factory=list, max_length=16)
    scope_kinds: list[Literal["instant", "occurrence", "validity", "period_value"]] = Field(
        min_length=1, max_length=4
    )
    metric: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def semantics(self) -> Self:
        if len(set(self.scope_kinds)) != len(self.scope_kinds):
            raise ValueError("Duplicate temporal meaning")
        if (self.statement_level == "reported") != (self.actor is not None and self.modality is not None):
            raise ValueError("Reported statements require an actor and explicit modality")
        if self.statement_level == "direct" and (self.actor is not None or self.modality is not None):
            raise ValueError("Direct assertions cannot use report qualifiers to evade conflict")
        if ("period_value" in self.scope_kinds) != (self.metric is not None):
            raise ValueError("Period values require explicit metric semantics")
        if len({q.name for q in self.qualifiers}) != len(self.qualifiers):
            raise ValueError("Duplicate semantic qualifier")
        self.qualifiers.sort(key=lambda q: q.name)
        self.scope_kinds.sort()
        return self


class Catalog(ClosedModel):
    profile: Literal["awm-adm-temporal-catalog/1"] = CATALOG
    namespace: Module
    entities: list[Identifier] = Field(min_length=1, max_length=128)
    predicates: list[Series] = Field(min_length=1, max_length=32)
    cells: list[Scope] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def finite(self) -> Self:
        from .identity import scope_key

        if len(set(self.entities)) != len(self.entities) or len({p.symbol for p in self.predicates}) != len(
            self.predicates
        ):
            raise ValueError("Duplicate entity or semantic predicate")
        keys = [scope_key(c.model_dump()) for c in self.cells]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate normalized temporal scope")
        if len(self.entities) * len(self.predicates) * len(self.cells) > 4096:
            raise ValueError("Combined temporal catalog exceeds 4096 finite addresses")
        return self


class Extracted(ClosedModel):
    entity_id: Identifier
    predicate: Symbol
    value: FactValue
    unit: str = Field(min_length=1, max_length=100)
    temporal_scope: Scope
    assertion_kind: Literal["assertion", "quotation", "hypothetical", "negation"]
    observed_time: Anchor = Field(default_factory=Anchor)
    reported_time: Anchor = Field(default_factory=Anchor)
    occurrence_id: Identifier | None = None

    @model_validator(mode="after")
    def no_legacy_authoring(self) -> Self:
        if self.temporal_scope.precision == "legacy":
            raise ValueError("Legacy precision is a reader view, not a newly authored observation")
        return self


class Spanned(Extracted):
    start_byte: int = Field(ge=0)
    end_byte: int = Field(ge=1)


class Extraction(ClosedModel):
    claims: list[Spanned] = Field(max_length=100)


class Claim(Extracted):
    fact_profile: Literal["awm-adm-temporal-claim/1"] = CLAIM
    claim_id: Identifier
    source: SourceSpan
    status: Literal["candidate", "needs_evidence", "disputed"] = "candidate"
