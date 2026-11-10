"""Cooperative work/time limits shared by enumeration and interpretation."""

from dataclasses import dataclass, field
from time import monotonic

from .errors import ResourceLimit


@dataclass
class Budget:
    max_work: int = 1_000_000
    max_seconds: float = 10.0
    used: int = field(default=0, init=False)
    _started: float = field(default_factory=monotonic, init=False, repr=False)

    def __post_init__(self):
        if type(self.max_work) is not int or self.max_work < 1:
            raise ValueError("max_work must be a positive integer")
        if not 0 < self.max_seconds < float("inf"):
            raise ValueError("max_seconds must be finite and positive")

    def tick(self, amount=1):
        self.used += amount
        if self.used > self.max_work or monotonic() - self._started > self.max_seconds:
            raise ResourceLimit("Computation budget exhausted", work=self.used)

    @property
    def remaining_seconds(self):
        """Remaining cooperative time, suitable for clamping provider I/O waits."""
        return max(0.0, self.max_seconds - (monotonic() - self._started))

    def integer(self, value):
        self.tick()
        if value.bit_length() > 1024:
            raise ResourceLimit("Intermediate integer exceeds 1024 bits")
        return value
