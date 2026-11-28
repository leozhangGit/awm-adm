"""Minimal owner inputs; execution context and provider authority are server-owned."""

from typing import Literal, Self

from pydantic import Field, model_validator

from ..contracts import ClosedModel, Identifier
from ..teaching.intent import KnowledgeIntent


class EnableConnection(ClosedModel):
    idempotency_key: Identifier
    provider: Literal["openai", "anthropic"]
    model: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:/-]+$")
    sealed_credential: str | None = Field(default=None, max_length=1024)
    sealing_key_id: str | None = Field(default=None, max_length=100)
    expected_generation: int | None = Field(default=None, ge=0)
    # Only needed when choosing among multiple configurations retained during migration.
    retained_connection_id: Identifier | None = None

    @model_validator(mode="after")
    def credential_pair(self) -> Self:
        if (self.sealed_credential is None) != (self.sealing_key_id is None):
            raise ValueError("Encrypted credentials require their gateway key identity")
        return self


class DisableConnection(ClosedModel):
    idempotency_key: Identifier


class DirectMessage(ClosedModel):
    idempotency_key: Identifier | None = None
    text: str = Field(default="", max_length=65536)
    attachments: list[Identifier] = Field(default_factory=list, max_length=8)
    reply_to: Identifier | None = None

    @model_validator(mode="after")
    def content(self) -> Self:
        if not self.text.strip() and not self.attachments:
            raise ValueError("Enter a message or select material to teach")
        if len(set(self.attachments)) != len(self.attachments):
            raise ValueError("Select each attachment once")
        return self


class DirectTeach(DirectMessage):
    # Optional caller assertion; never supplied by the provider or inferred as human review.
    knowledge_intent: KnowledgeIntent | None = None
