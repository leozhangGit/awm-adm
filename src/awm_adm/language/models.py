"""Owner/client inputs and provider proposals have separate authority."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ..contracts import CallLimits, ClosedModel, Identifier, JsonValue, RequestLimits, ShortText

Utterance = Annotated[str, Field(min_length=1, max_length=16_384)]
Alias = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z][A-Za-z0-9 _.-]*$")]


class Vocabulary(ClosedModel):
    aliases: dict[Alias, list[str]] = Field(default_factory=dict, max_length=128)
    parameter_units: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=128)
    parameter_roles: dict[str, dict[str, Literal["value", "entity", "time"]]] = Field(
        default_factory=dict, max_length=128
    )
    value_aliases: dict[str, dict[str, dict[str, JsonValue]]] = Field(default_factory=dict, max_length=128)


class VocabularyInput(ClosedModel):
    expected_revision: Identifier
    expected_generation: int = Field(ge=0)
    vocabulary: Vocabulary


class ConversationInput(ClosedModel):
    idempotency_key: Identifier
    title: str = Field(default="Conversation", min_length=1, max_length=128)


class InterpretationInput(ClosedModel):
    allowance_id: Identifier | None = None
    idempotency_key: Identifier
    expected_revision: Identifier
    conversation_id: Identifier
    utterance: Utterance
    translator: Literal["local", "external"] = "local"
    connection_id: Identifier | None = None
    connection_version: int | None = Field(default=None, ge=1)
    disclose_catalog: bool = False
    context_turn_ids: list[Identifier] = Field(default_factory=list, max_length=6)
    call_limits: CallLimits = Field(default_factory=lambda: CallLimits(max_output_tokens=2048))

    @model_validator(mode="after")
    def authority(self) -> Self:
        if self.translator == "external":
            if not self.connection_id or self.connection_version is None or not self.disclose_catalog:
                raise ValueError("External interpretation needs a connection and explicit catalog disclosure")
        elif (
            self.connection_id
            or self.connection_version is not None
            or self.context_turn_ids
            or self.disclose_catalog
        ):
            raise ValueError("Local interpretation cannot carry remote authority or implicit history")
        if len(set(self.context_turn_ids)) != len(self.context_turn_ids):
            raise ValueError("Duplicate context turns")
        return self


class ExecuteInput(ClosedModel):
    idempotency_key: Identifier
    expected_revision: Identifier
    expected_catalog_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    limits: RequestLimits = Field(default_factory=RequestLimits)


class TeachInput(ClosedModel):
    idempotency_key: Identifier
    expected_revision: Identifier
    text: Utterance


class Proposal(ClosedModel):
    status: Literal["ready", "needs_clarification", "unsupported", "needs_learning"]
    command: Utterance | None
    assumptions: list[ShortText] = Field(max_length=16)
    clarification: ShortText | None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (self.status == "ready") != (self.command is not None):
            raise ValueError("Only a ready proposal carries a command")
        if self.status != "ready" and not self.clarification:
            raise ValueError("Unready proposals explain the missing information")
        return self
