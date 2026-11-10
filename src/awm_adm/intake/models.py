"""Owner inputs are separate from untrusted attached or pushed material."""

from typing import Literal

from pydantic import Field, model_validator

from ..contracts import ClosedModel, Digest, Identifier
from ..conversations.models import Context
from ..sources.models import SourceInput


class Upload(ClosedModel):
    idempotency_key: Identifier
    name: str = Field(min_length=1, max_length=200)
    media_type: Literal["text/plain", "text/markdown", "application/json", "application/x-ndjson"]
    content: str = Field(min_length=1, max_length=262144)
    source_id: Identifier = "documents"
    item_id: Identifier | None = None
    supersedes_version: Identifier | None = None

    @model_validator(mode="after")
    def bounded(self):
        if len(self.content.encode("utf-8")) > 262144 or "\x00" in self.content:
            raise ValueError("Material must be UTF-8 within 256 KiB without NUL")
        if "/" in self.name or "\\" in self.name or any(ord(c) < 32 for c in self.name):
            raise ValueError("Use a plain file name without paths or control characters")
        return self


class AppendInput(ClosedModel):
    idempotency_key: Identifier
    items: list[SourceInput] = Field(min_length=1, max_length=4)


class AppendCredential(ClosedModel):
    context: Context
    specification_digest: Digest
    expected_version: int = Field(ge=0)
    expires_in: int = Field(default=3600, ge=60, le=86400)
