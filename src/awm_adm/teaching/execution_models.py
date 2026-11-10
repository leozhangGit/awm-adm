"""Owner-only execution decisions; provider text cannot authorize these inputs."""

from typing import Literal

from pydantic import Field

from ..contracts import ClosedModel, Digest, Identifier
from ..conversations.models import Context


class TaskCommand(ClosedModel):
    idempotency_key: Identifier
    specification_digest: Digest
    context: Context
    expected_version: int = Field(ge=0)
    action: Literal["start", "pause", "resume", "cancel", "approve", "decline", "finish"]
    review_digest: Digest | None = None
    source_consent: bool = False


class CompletionReply(ClosedModel):
    packet_digest: Digest
    accepted_ids: list[Identifier] = Field(max_length=4)
    unresolved_ids: list[Identifier] = Field(max_length=4)
    explanation: str = Field(min_length=1, max_length=2000)
    authority: Literal["explanation_only"]


COMPLETION_SCHEMA = {
    "type": "object",
    "properties": {
        "packet_digest": {"type": "string"},
        "accepted_ids": {"type": "array", "items": {"type": "string"}},
        "unresolved_ids": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
        "authority": {"type": "string", "enum": ["explanation_only"]},
    },
    "required": ["packet_digest", "accepted_ids", "unresolved_ids", "explanation", "authority"],
    "additionalProperties": False,
}
