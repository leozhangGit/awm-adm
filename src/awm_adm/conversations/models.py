"""Closed owner inputs and deliberately small provider-facing clarification schema."""

from typing import Literal

from pydantic import Field, field_validator

from ..contracts import ClosedModel, Digest, Epoch, Identifier


class Context(ClosedModel):
    adm_id: Identifier
    revision_id: Identifier
    theory_root: Digest
    support_root: Digest
    policy_epoch: Epoch
    vocabulary_generation: Epoch
    source_policy_generation: Epoch


class ConversationInput(ClosedModel):
    idempotency_key: Identifier
    channel: Literal["ask", "teach"]
    title: str = Field(default="New conversation", min_length=1, max_length=120)


class MessageInput(ClosedModel):
    profile: Literal["awm-adm-v3-messageinput/0.1"] = "awm-adm-v3-messageinput/0.1"
    idempotency_key: Identifier
    channel: Literal["ask", "teach"]
    context: Context
    text: str = Field(min_length=1, max_length=16384)
    attachment_ids: list[Identifier] = Field(default_factory=list, max_length=4)
    reply_to: Identifier | None = None
    disclose_attachments: bool = False

    @field_validator("text")
    @classmethod
    def bounded_text(cls, value):
        if not value.strip() or len(value.encode("utf-8")) > 16384 or "\x00" in value:
            raise ValueError("Message must be nonempty UTF-8 text within 16 KiB")
        return value


class SetupInput(ClosedModel):
    idempotency_key: Identifier
    context: Context
    price_id: Identifier
    purpose: Literal["clarification", "ask", "teach"] = "clarification"
    narrate_results: bool = False
    source_queue: bool = False


class DecisionInput(ClosedModel):
    profile: Literal["awm-adm-v3-decisioninput/0.1"] = "awm-adm-v3-decisioninput/0.1"
    idempotency_key: Identifier
    proposal_id: Identifier
    proposal_digest: Digest
    context: Context
    answer: Literal["accept", "decline"]


class ProviderReply(ClosedModel):
    kind: Literal["clarification", "unavailable"]
    text: str = Field(min_length=1, max_length=2000)


REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["clarification", "unavailable"]},
        "text": {"type": "string"},
    },
    "required": ["kind", "text"],
    "additionalProperties": False,
}


class GapInput(ClosedModel):
    idempotency_key: Identifier
    context: Context


class LinkInput(ClosedModel):
    idempotency_key: Identifier
    turn_id: Identifier
    kind: Literal["request", "result", "episode", "teaching_draft"]
    resource_id: Identifier


class Presentation(ClosedModel):
    """Version 0.2 also binds terminal requests that have no successful Result."""

    profile: Literal["awm-adm-v3-presentation/0.2"] = "awm-adm-v3-presentation/0.2"
    id: Identifier
    context: Context
    subject_kind: Literal["request", "result"]
    subject_id: Identifier
    outcome_digest: Digest
    packet_digest: Digest
    status: Literal["ready", "fallback"]
    text: str = Field(min_length=1, max_length=32768)
    support_ids: list[Identifier] = Field(max_length=32)
    authoritative: Literal[False] = False
