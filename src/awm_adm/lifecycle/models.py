"""Direct owner controls: source and provider prose cannot supply authority."""

from pydantic import Field

from ..contracts import ClosedModel, Identifier


class DeleteInput(ClosedModel):
    idempotency_key: Identifier
    expected_revision: Identifier | None
    expected_epoch: int | None = Field(ge=0)
    confirm_name: str = Field(min_length=1, max_length=128)
    confirm_delete: bool


class RenameInput(ClosedModel):
    expected_name: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)


class RetryInput(ClosedModel):
    expected_version: int = Field(ge=1)
