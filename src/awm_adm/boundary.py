"""Shared closed boundary primitives, independent of feature contracts."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

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


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)
