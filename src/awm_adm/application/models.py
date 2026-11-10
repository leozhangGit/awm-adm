"""Response schemas for the application API; no authority in caller data."""

from pydantic import Field, JsonValue

from ..contracts import ClosedModel, ContextBinding, ErrorEnvelope, Event, RequestRecord, RequestStatus


class Attempt(ClosedModel):
    id: str
    status: str
    started: float
    ended: float | None
    revision: str | None


class RequestView(RequestRecord):
    query: dict[str, JsonValue]
    revision_id: str
    initial_revision_id: str | None
    pinned_context: ContextBinding
    current_context: ContextBinding
    attempts: list[Attempt]
    created_at_ms: int
    updated_at_ms: int


class RequestSummary(ClosedModel):
    adm_id: str
    request_id: str
    status: RequestStatus
    attempt_id: str | None
    result_id: str | None
    pinned_context: ContextBinding


class RequestPage(ClosedModel):
    items: list[RequestSummary]
    next_cursor: int | None


class EventPage(ClosedModel):
    items: list[Event]
    cursor: int = Field(ge=0)
    earliest_cursor: int = Field(ge=0)
    latest_cursor: int = Field(ge=0)


class Operation(ClosedModel):
    operation_id: str
    kind: str
    adm_id: str | None
    status: str
    result: JsonValue
    error: ErrorEnvelope | None
