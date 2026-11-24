"""Shared finite scalar carriers; unchanged source predicate semantics."""

from typing import Literal, Self

from pydantic import Field, model_validator

from ..boundary import ClosedModel, Symbol


class Predicate(ClosedModel):
    symbol: Symbol
    kind: Literal["boolean", "integer", "enum"]
    unit: str = Field(min_length=1, max_length=100)
    minimum: int = Field(default=0, ge=-9007199254740991, le=9007199254740991)
    maximum: int = Field(default=100, ge=-9007199254740991, le=9007199254740991)
    values: list[str] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def carrier(self) -> Self:
        if self.minimum > self.maximum or self.maximum - self.minimum > 1000000:
            raise ValueError("Invalid bounded integer carrier")
        if self.kind == "enum" and (not self.values or len(set(self.values)) != len(self.values)):
            raise ValueError("Enum requires unique finite values")
        if any(not v or len(v) > 200 for v in self.values):
            raise ValueError("Invalid enum value")
        if self.kind != "enum" and self.values:
            raise ValueError("Only enums have named values")
        return self
