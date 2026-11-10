"""Owner-authored learning inputs. Providers cannot issue these commands."""

from typing import Literal, Self

from pydantic import Field, model_validator

from ..config import EpisodeLimits
from ..contracts import CallLimits, ClosedModel, Identifier, ProviderDiagnostics, Purpose
from ..engine.acquisition import validate_contract


class ConnectionInput(ClosedModel):
    idempotency_key: Identifier
    name: str = Field(min_length=1, max_length=128)
    provider: Literal["recorded", "openai", "anthropic"]
    model: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:/-]+$")
    enabled: bool = False
    purposes: list[Purpose] = Field(
        default_factory=lambda: ["acquisition", "connection_test"], min_length=1, max_length=10
    )
    capabilities: list[Literal["json_schema", "recursive_refs"]] = Field(
        default_factory=lambda: ["json_schema", "recursive_refs"], max_length=2
    )
    credential_mode: Literal["none", "managed", "static"] = "none"
    sealed_credential: str | None = Field(default=None, max_length=1024)
    sealing_key_id: str | None = Field(default=None, max_length=100)
    # Fixture content is explicitly owner-supplied instance data, never engine rules.
    recorded_responses: list[dict] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if len(set(self.purposes)) != len(self.purposes) or len(set(self.capabilities)) != len(
            self.capabilities
        ):
            raise ValueError("Duplicate purposes or capabilities")
        if self.provider == "recorded":
            if self.credential_mode != "none" or self.sealed_credential or self.sealing_key_id:
                raise ValueError("Recorded connections do not accept credentials")
        elif self.credential_mode == "none" or self.recorded_responses:
            raise ValueError("Remote connections require a credential mode and no recorded replies")
        if (self.sealed_credential is None) != (self.sealing_key_id is None):
            raise ValueError("Sealed credentials require their gateway key identity")
        if self.sealed_credential and self.credential_mode != "managed":
            raise ValueError("Only managed connections accept sealed credentials")
        return self


class ConnectionChange(ConnectionInput):
    expected_version: int = Field(ge=1)


class LearningSettings(ClosedModel):
    expected_generation: int = Field(ge=0)
    remote_calls_enabled: bool


class EpisodeInput(ClosedModel):
    allowance_id: Identifier | None = None
    idempotency_key: Identifier
    expected_revision: Identifier
    connection_id: Identifier
    connection_version: int = Field(ge=1)
    task: dict
    construction: bool = True
    publication: Literal["review", "checked_auto"] = "review"
    disclose_model: bool = False
    limits: EpisodeLimits = Field(default_factory=EpisodeLimits)
    call_limits: CallLimits = Field(default_factory=CallLimits)
    request_ids: list[Identifier] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def scoped(self) -> Self:
        if not self.task or "acquisition_contract" not in self.task:
            raise ValueError("Supply a task with an explicit receiver-owned acquisition_contract")
        from ..engine.errors import ADMError

        try:
            validate_contract(self.task["acquisition_contract"])
        except ADMError as error:
            raise ValueError("Invalid acquisition contract") from error
        if len(set(self.request_ids)) != len(self.request_ids):
            raise ValueError("Duplicate request interests")
        for k in ("max_calls", "max_input_tokens", "max_output_tokens", "max_duration_ms"):
            if getattr(self.call_limits, k) > getattr(self.limits, k):
                raise ValueError("Call limit exceeds episode allowance")
        return self


class TestConnection(ClosedModel):
    allowance_id: Identifier | None = None
    idempotency_key: Identifier
    expected_version: int = Field(ge=1)
    limits: CallLimits = Field(default_factory=lambda: CallLimits(max_output_tokens=64))


class Review(ClosedModel):
    expected_revision: Identifier
    approve: bool


class Interest(ClosedModel):
    request_id: Identifier


class Usage(ClosedModel):
    input_tokens: int = Field(ge=0, le=9_007_199_254_740_991)
    output_tokens: int = Field(ge=0, le=9_007_199_254_740_991)


class Outcome(ClosedModel):
    status: Literal["succeeded", "failed", "outcome_unknown"]
    error: str | None = Field(default=None, max_length=100, pattern=r"^[a-z_]+$")
    usage: Usage | None = None
    text: str | None = Field(default=None, max_length=262144)
    response_id: str | None = Field(default=None, max_length=200)
    returned_model: str | None = Field(default=None, max_length=200)
    diagnostics: ProviderDiagnostics | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.status == "outcome_unknown" and self.usage is not None:
            raise ValueError("Unknown outcomes cannot settle usage")
        if self.status == "succeeded" and self.text is None:
            raise ValueError("Successful outcomes require complete output")
        if self.status != "succeeded" and self.text is not None:
            raise ValueError("Failed outcomes cannot carry executable output")
        return self
