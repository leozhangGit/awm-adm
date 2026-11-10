"""Closed boundary schemas. Shape checks do not confer semantic or publication authority."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Symbol = Annotated[str, Field(max_length=200, pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")]
Module = Annotated[str, Field(max_length=200, pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")]
ShortText = Annotated[str, Field(min_length=1, max_length=4096)]
Epoch = Annotated[int, Field(ge=0, le=9_007_199_254_740_991)]
Positive = Annotated[int, Field(ge=1, le=9_007_199_254_740_991)]
Instant = Annotated[
    str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", json_schema_extra={"format": "date-time"})
]
Purpose = Literal[
    "connection_test",
    "interpretation",
    "extraction",
    "acquisition",
    "ask_interpretation",
    "ask_narration",
    "clarification",
    "task_preparation",
    "repair",
    "task_narration",
]
RequestStatus = Literal[
    "received",
    "evaluating",
    "waiting_for_learning",
    "needs_input",
    "succeeded",
    "inconclusive",
    "failed",
    "cancelled",
]
ErrorCode = Literal[
    "invalid_input",
    "unsupported",
    "not_found",
    "unauthorized",
    "forbidden",
    "remote_calls_disabled",
    "connection_unavailable",
    "purpose_unavailable",
    "allowance_expired",
    "allowance_closed",
    "allowance_exhausted",
    "allowance_unavailable",
    "price_unavailable",
    "spending_disabled",
    "spending_suspended",
    "conflict",
    "quota_exceeded",
    "provider_unavailable",
    "outcome_unknown",
    "resource_exhausted",
    "needs_evidence",
    "needs_specification",
    "cursor_expired",
    "stale_context",
    "not_implemented",
    "internal_error",
]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class RequestLimits(ClosedModel):
    max_work: int = Field(default=1_000_000, ge=1, le=100_000_000)
    max_duration_ms: int = Field(default=10_000, ge=1, le=3_600_000)
    max_states: int = Field(default=10_000, ge=1, le=1_000_000)
    max_search_bytes: int = Field(default=16_000_000, ge=1, le=256_000_000)


class Capabilities(ClosedModel):
    op: Literal["capabilities"]


class Evaluate(ClosedModel):
    op: Literal["evaluate"]
    module: Module
    expression: dict[str, JsonValue] = Field(min_length=1)


class CheckClaim(ClosedModel):
    op: Literal["check_claim"]
    module: Module
    proposition: dict[str, JsonValue] = Field(min_length=1)


class FindPlan(ClosedModel):
    op: Literal["find_plan"]
    module: Module
    initial_state: JsonValue
    goal: Symbol
    max_depth: Annotated[int, Field(ge=0, le=1_000_000)] | None = None
    transitions: (
        Annotated[list[Symbol], Field(max_length=1024, json_schema_extra={"uniqueItems": True})] | None
    ) = None

    @model_validator(mode="after")
    def unique_actions(self) -> Self:
        if self.transitions is not None and len(set(self.transitions)) != len(self.transitions):
            raise ValueError("Duplicate explicit transition")
        return self


class CheckCertificate(ClosedModel):
    op: Literal["check_certificate"]
    certificate: dict[str, JsonValue] = Field(min_length=1)
    backend: Literal["finite", "lean"]


class Explain(ClosedModel):
    op: Literal["explain"]
    result_id: Identifier


class FactLookup(ClosedModel):
    op: Literal["lookup_fact"]
    entity_id: Identifier
    predicate: Symbol
    effective_at: Instant

    @model_validator(mode="after")
    def instant(self) -> Self:
        datetime.fromisoformat(self.effective_at.replace("Z", "+00:00"))
        return self


Query = Annotated[
    Capabilities | Evaluate | CheckClaim | FindPlan | CheckCertificate | Explain | FactLookup,
    Field(discriminator="op"),
]


class Request(ClosedModel):
    request_profile: Literal["awm-adm-request/2"] = "awm-adm-request/2"
    engine_profile: Literal["finite-v0"] = "finite-v0"
    idempotency_key: Identifier
    query: Query
    limits: RequestLimits = Field(default_factory=RequestLimits)
    on_gap: Literal["report", "learn"] = "report"


class ErrorEnvelope(ClosedModel):
    error_profile: Literal["awm-adm-error/2"] = "awm-adm-error/2"
    code: ErrorCode
    message: ShortText
    retry: Literal["never", "after_input", "after_backoff", "reconcile", "resynchronize"]
    resource_id: Identifier | None = None
    # Bounded application-authored diagnostics; no exception/provider body passthrough.
    details: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)


class ContextBinding(ClosedModel):
    adm_id: Identifier
    theory_root: Digest
    policy_epoch: Epoch
    support_root: Digest | None = None
    source_policy_generation: Epoch | None = None


class Selection(ClosedModel):
    kind: Literal["module_all", "explicit", "not_applicable"]
    actions: list[Symbol] | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def explicit_only(self) -> Self:
        if (self.kind == "explicit") != (self.actions is not None):
            raise ValueError("Only explicit selection carries an action list")
        if self.actions is not None and len(set(self.actions)) != len(self.actions):
            raise ValueError("Duplicate selected action")
        return self


class ResultBinding(ClosedModel):
    context: ContextBinding
    request_id: Identifier
    attempt_id: Identifier
    query_digest: Digest
    selection: Selection
    resolved_actions: list[Symbol] = Field(default_factory=list, max_length=1024)

    @model_validator(mode="after")
    def action_scope(self) -> Self:
        if len(set(self.resolved_actions)) != len(self.resolved_actions):
            raise ValueError("Duplicate resolved action")
        if self.selection.kind == "not_applicable" and self.resolved_actions:
            raise ValueError("Non-action result cannot declare an action scope")
        if self.selection.kind == "explicit" and set(self.selection.actions) != set(self.resolved_actions):
            raise ValueError("Resolved actions differ from explicit selection")
        return self


class Result(ClosedModel):
    result_id: Identifier
    binding: ResultBinding
    value: JsonValue
    claims: list[
        Literal["value", "valid_witness", "shortest_action_count", "unreachable", "no_plan_within_bound"]
    ] = Field(max_length=5)
    lean_kernel: Literal["not_requested", "checked", "unavailable", "failed"]
    exhaustive_finite: Literal["not_checked", "checked", "failed"]
    empirical_fidelity: Literal["not_established", "conditional_on_declared_sources"] = "not_established"

    @model_validator(mode="after")
    def separate_claims(self) -> Self:
        if len(set(self.claims)) != len(self.claims):
            raise ValueError("Duplicate result claim")
        if "shortest_action_count" in self.claims and "valid_witness" not in self.claims:
            raise ValueError("Shortestness requires a valid witness")
        if "unreachable" in self.claims:
            if "valid_witness" in self.claims or self.exhaustive_finite != "checked":
                raise ValueError(
                    "Unreachability requires checked correspondence and cannot coexist with a witness"
                )
        if self.lean_kernel == "checked" and self.exhaustive_finite != "checked":
            raise ValueError("A bound Lean result requires checked executable correspondence")
        return self


class RequestRecord(ClosedModel):
    adm_id: Identifier
    request_id: Identifier
    status: RequestStatus
    attempt_id: Identifier | None = None
    result: Result | None = None
    error: ErrorEnvelope | None = None
    learning_job_ids: list[Identifier] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def coherent_outcome(self) -> Self:
        if (self.status == "succeeded") != (self.result is not None):
            raise ValueError("Only a successful request carries a result")
        if self.result:
            binding = self.result.binding
            if (binding.context.adm_id, binding.request_id, binding.attempt_id) != (
                self.adm_id,
                self.request_id,
                self.attempt_id,
            ):
                raise ValueError("Result belongs to a different request/attempt/ADM")
            if self.error:
                raise ValueError("Successful request cannot carry an error")
        if self.status == "waiting_for_learning" and not self.learning_job_ids:
            raise ValueError("Waiting status requires durable learning work identities")
        return self


class Event(ClosedModel):
    event_profile: Literal["awm-adm-event/2"] = "awm-adm-event/2"
    adm_id: Identifier
    event_id: Identifier
    sequence: Positive
    occurred_at_ms: Epoch
    kind: Literal[
        "request.received",
        "request.evaluating",
        "request.waiting_for_learning",
        "request.succeeded",
        "request.inconclusive",
        "request.needs_input",
        "request.failed",
        "request.cancelled",
        "source.policy_changed",
        "source.received",
        "source.superseded",
        "source.disputed",
        "extraction.completed",
        "episode.queued",
        "episode.started",
        "episode.stopped",
        "candidate.received",
        "candidate.awaiting_review",
        "candidate.accepted",
        "candidate.rejected",
        "settings.changed",
        "policy.changed",
        "language.vocabulary_changed",
        "interpretation.changed",
        "interpretation.executed",
        "teaching.drafted",
        "teaching.prepared",
        "teaching.renewed",
        "teaching.execution",
        "teaching.completed",
        "teaching.stopped",
        "feed.changed",
        "conversation.turn",
        "conversation.queued",
        "conversation.completed",
        "conversation.decision",
    ]
    resource_id: Identifier
    request_id: Identifier | None = None
    attempt_id: Identifier | None = None
    context: ContextBinding | None = None
    data: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def same_adm(self) -> Self:
        if self.context and self.context.adm_id != self.adm_id:
            raise ValueError("Cross-ADM event context")
        if self.kind.startswith("request.") and self.request_id != self.resource_id:
            raise ValueError("Request event must identify its request")
        return self


class ProviderConfiguration(ClosedModel):
    connection_id: Identifier
    configuration_digest: Digest
    provider: Literal["recorded", "openai", "anthropic"]
    model: Annotated[str, Field(min_length=1, max_length=200)]


class IntentDraft(ClosedModel):
    intent_profile: Literal["awm-adm-intent/2"] = "awm-adm-intent/2"
    interpretation_id: Identifier
    context: ContextBinding
    catalog_digest: Digest
    utterance: Annotated[str, Field(min_length=1, max_length=16_384)]
    translator: Literal["local", "external"]
    provider_configuration: ProviderConfiguration | None = None
    status: Literal["ready", "needs_clarification", "unsupported", "needs_learning", "failed"]
    query: Query | None = None
    assumptions: list[ShortText] = Field(default_factory=list, max_length=16)
    clarification: ShortText | None = None
    # Review is an owner/app decision, never a provider field in a submitted draft.

    @model_validator(mode="after")
    def interpretation_boundary(self) -> Self:
        if (self.translator == "external") != (self.provider_configuration is not None):
            raise ValueError("External translation requires exact provider configuration")
        if (self.status == "ready") != (self.query is not None):
            raise ValueError("Only a ready interpretation carries an executable query")
        if self.status != "ready" and not self.clarification:
            raise ValueError("Unready interpretation requires an explicit explanation")
        return self


class TemporalScope(ClosedModel):
    kind: Literal["unknown", "point", "interval"]
    granularity: Literal["second", "day", "year"]
    effective_from: Instant | None = None
    effective_to: Instant | None = None

    @model_validator(mode="after")
    def temporal_consistency(self) -> Self:
        for value in (self.effective_from, self.effective_to):
            if value:
                datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        if self.kind == "unknown" and (self.effective_from or self.effective_to):
            raise ValueError("Unknown scope has no implied timestamps")
        if self.kind != "unknown" and self.effective_from is None:
            raise ValueError("Known scope requires a start")
        if self.kind == "point" and self.effective_to is not None:
            raise ValueError("A point has no interval end")
        if self.effective_to and self.effective_from and self.effective_to <= self.effective_from:
            raise ValueError("Temporal intervals are nonempty and half-open")
        return self


class SourceRecord(ClosedModel):
    source_profile: Literal["awm-adm-source/2"] = "awm-adm-source/2"
    source_id: Identifier
    item_id: Identifier
    version_id: Identifier
    media_type: Literal["text/plain", "text/markdown", "application/json", "application/x-ndjson"]
    content_digest: Digest
    byte_count: Annotated[int, Field(ge=1, le=2_097_152)]
    origin: ShortText
    received_at_ms: Epoch
    supersedes_version: Identifier | None = None

    @model_validator(mode="after")
    def not_self_correction(self) -> Self:
        if self.supersedes_version == self.version_id:
            raise ValueError("A source version cannot supersede itself")
        return self


class SourceSpan(ClosedModel):
    source_id: Identifier
    item_id: Identifier
    version_id: Identifier
    content_digest: Digest
    start_byte: Epoch
    end_byte: Positive

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        if self.end_byte <= self.start_byte:
            raise ValueError("Source spans are nonempty")
        return self


class FactValue(ClosedModel):
    kind: Literal["boolean", "integer", "enum"]
    value: bool | int | str

    @model_validator(mode="after")
    def exact_type(self) -> Self:
        expected = {"boolean": bool, "integer": int, "enum": str}[self.kind]
        if type(self.value) is not expected:
            raise ValueError("Fact value does not match its explicit kind")
        if type(self.value) is str and not 1 <= len(self.value) <= 200:
            raise ValueError("Enum label exceeds the fact profile")
        if type(self.value) is int and not -(2**53 - 1) <= self.value <= 2**53 - 1:
            raise ValueError("Integer exceeds interoperable fact range")
        return self


class FactClaim(ClosedModel):
    fact_profile: Literal["awm-adm-facts/0.1"] = "awm-adm-facts/0.1"
    claim_id: Identifier
    entity_id: Identifier
    predicate: Symbol
    value: FactValue
    unit: Annotated[str, Field(min_length=1, max_length=100)]
    temporal_scope: TemporalScope
    source: SourceSpan
    assertion_kind: Literal["assertion", "quotation", "hypothetical", "negation"]
    status: Literal["candidate", "needs_evidence", "disputed"] = "candidate"


class CallLimits(ClosedModel):
    max_calls: int = Field(default=1, ge=1, le=1)
    max_input_tokens: int = Field(default=32_000, ge=1, le=1_050_000)
    max_output_tokens: int = Field(default=8192, ge=1, le=100_000)
    max_duration_ms: int = Field(default=60_000, ge=1, le=600_000)


class WorkerLease(ClosedModel):
    lease_profile: Literal["awm-adm-worker-lease/2"] = "awm-adm-worker-lease/2"
    job_id: Identifier
    attempt_id: Identifier
    worker_id: Identifier
    lease_token: Identifier
    purpose: Purpose
    context: ContextBinding | None = None
    control_scope_id: Identifier | None = None
    input_digest: Digest
    issued_at_ms: Epoch
    expires_at_ms: Positive

    @model_validator(mode="after")
    def positive_lifetime(self) -> Self:
        if self.expires_at_ms <= self.issued_at_ms:
            raise ValueError("Lease expiry must follow issue time")
        if self.purpose == "connection_test":
            if self.context is not None or self.control_scope_id is None:
                raise ValueError("Connection tests use an explicit installation control scope")
        elif self.context is None or self.control_scope_id is not None:
            raise ValueError("Model work requires exactly one ADM context")
        return self


class DispatchGrant(ClosedModel):
    grant_profile: Literal["awm-adm-dispatch-grant/2"] = "awm-adm-dispatch-grant/2"
    grant_id: Identifier
    reservation_id: Identifier
    gateway_id: Identifier
    lease: WorkerLease
    provider_configuration: ProviderConfiguration
    request_digest: Digest
    limits: CallLimits
    # An authenticated internal issuer and durable ledger must authorize this document.


class Usage(ClosedModel):
    input_tokens: Epoch
    output_tokens: Epoch


DiagnosticCount = Annotated[int, Field(strict=True, ge=0, lt=2**53)]


class ProviderTokenDetails(ClosedModel):
    """Optional provider-reported counters, not reconstructed totals or billing."""

    total_tokens: DiagnosticCount | None = None
    cached_input_tokens: DiagnosticCount | None = None
    reasoning_tokens: DiagnosticCount | None = None
    cache_creation_input_tokens: DiagnosticCount | None = None
    cache_read_input_tokens: DiagnosticCount | None = None


class ProviderOutputSummary(ClosedModel):
    """Counts only; no message text, reasoning content, signatures or summaries."""

    item_count: DiagnosticCount
    message_items: DiagnosticCount
    text_items: DiagnosticCount
    reasoning_items: DiagnosticCount
    other_items: DiagnosticCount
    visible_text_parts: DiagnosticCount
    visible_text_bytes: DiagnosticCount


class ProviderDiagnostics(ClosedModel):
    """Allowlisted metadata only; never arbitrary provider messages or reasoning."""

    http_status: int | None = Field(default=None, ge=100, le=599)
    provider_status: (
        Literal["completed", "incomplete", "failed", "cancelled", "queued", "in_progress"] | None
    ) = None
    incomplete_reason: Literal["max_output_tokens", "content_filter", "steered", "unknown"] | None = None
    provider_error_code: (
        Literal[
            "insufficient_quota",
            "rate_limit_exceeded",
            "invalid_api_key",
            "model_not_found",
            "invalid_request_error",
            "authentication_error",
            "permission_error",
            "rate_limit_error",
            "overloaded_error",
            "server_error",
            "unknown",
        ]
        | None
    ) = None
    reported_usage: Usage | None = None
    usage_assessment: Literal["reported", "missing_or_invalid", "zero_unverified"] | None = None
    token_details: ProviderTokenDetails | None = None
    # Response-side settings only. Never infer them from a model name or default.
    reasoning_effort: (
        Literal["none", "minimal", "low", "medium", "high", "xhigh", "max", "unknown"] | None
    ) = None
    reasoning_mode: Literal["standard", "pro", "unknown"] | None = None
    output_summary: ProviderOutputSummary | None = None


class DispatchOutcome(ClosedModel):
    grant_id: Identifier
    status: Literal["not_dispatched", "dispatched", "succeeded", "failed", "outcome_unknown"]
    usage: Usage | None = None
    response_digest: Digest | None = None
    error: ErrorEnvelope | None = None
    diagnostics: ProviderDiagnostics | None = None

    @model_validator(mode="after")
    def known_outcome(self) -> Self:
        if self.status == "succeeded" and self.response_digest is None:
            raise ValueError("Successful dispatch requires recorded output")
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("Successful dispatch cannot carry an error")
        if self.status in ("not_dispatched", "dispatched", "outcome_unknown") and (
            self.usage is not None or self.response_digest is not None
        ):
            raise ValueError("Unknown/uncompleted dispatch cannot claim final output or settled usage")
        return self


SCHEMAS = {
    cls.__name__: cls
    for cls in (
        Request,
        RequestRecord,
        ErrorEnvelope,
        Event,
        IntentDraft,
        SourceRecord,
        FactClaim,
        WorkerLease,
        DispatchGrant,
        DispatchOutcome,
    )
}
