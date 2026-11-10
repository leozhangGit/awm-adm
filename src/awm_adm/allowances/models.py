"""Owner-only inputs. No floating point money, implicit funding or price selection."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ..contracts import ClosedModel, Digest, Identifier
from .pricing import MAX_BILLABLE_INPUT

Money = Annotated[int, Field(ge=0, le=1_000_000_000)]


class SpendingInput(ClosedModel):
    expected_generation: int = Field(ge=0)
    enabled: bool = False
    resume_lanes: list[Literal["interaction", "learning"]] = Field(default_factory=list, max_length=2)
    total_micro_usd: Money
    interaction_micro_usd: Money
    learning_micro_usd: Money
    legacy_hold_micro_usd: Money | None = None

    @model_validator(mode="after")
    def nested(self) -> Self:
        if (
            self.interaction_micro_usd + self.learning_micro_usd + (self.legacy_hold_micro_usd or 0)
            > self.total_micro_usd
        ):
            raise ValueError("Lane limits and legacy hold exceed installation cap")
        return self


class PriceInput(ClosedModel):
    idempotency_key: Identifier
    connection_id: Identifier
    connection_version: int = Field(ge=1)
    configuration_digest: Digest
    bound_profile: Literal[
        "recorded-test/1", "openai-4o-context/2026-11-08", "openai-5.6-luna-context/2026-11-09"
    ]
    input_micro_usd_per_million: int = Field(ge=1, le=1_000_000_000)
    output_micro_usd_per_million: int = Field(ge=1, le=1_000_000_000)
    valid_until_ms: int = Field(ge=1)


class AllowanceInput(ClosedModel):
    idempotency_key: Identifier
    price_id: Identifier
    adm_id: Identifier | None = None
    scope: Literal["interaction", "task", "source", "control"]
    scope_id: Identifier
    cap_micro_usd: int = Field(ge=1, le=1_000_000_000)
    expires_at_ms: int = Field(ge=1)
    max_calls: int = Field(default=6, ge=1, le=20)
    max_input_tokens: int = Field(default=192_000, ge=1, le=20 * MAX_BILLABLE_INPUT)
    max_output_tokens: int = Field(default=49_152, ge=1, le=327_680)
    max_children: int = Field(default=8, ge=1, le=32)
    max_work: int = Field(default=12_000_000, ge=1, le=100_000_000)

    @model_validator(mode="after")
    def scope_binding(self) -> Self:
        if (self.scope == "control") != (self.adm_id is None):
            raise ValueError("Only connection control has installation scope")
        return self


class CloseInput(ClosedModel):
    expected_state: Literal["active", "suspended"] = "active"


class ChildInput(ClosedModel):
    operation_id: Identifier
    kind: Literal["preparation", "episode", "extraction", "repair", "narration", "local_check"]
    max_work: int = Field(ge=0, le=10_000_000)
    max_duration_ms: int = Field(default=5000, ge=1, le=30_000)
    payload_digest: Digest
