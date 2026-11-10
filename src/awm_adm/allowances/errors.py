"""Only static application-authored financial guidance is public, never provider text."""

from ..runtime.protocol import RuntimeFault


class AllowanceFault(RuntimeFault):
    pass
