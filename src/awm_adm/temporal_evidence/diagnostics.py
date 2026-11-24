"""Bounded receiver-authored reasons; never echo untrusted source/provider text."""

MESSAGES = {
    "descriptor_revision": "This would change the meaning or unit of an existing property. Its accepted meaning has been preserved.",
    "partial_scope_revision": "This conflicts with part of an accepted time interval. Revising only that part is not supported; the existing interval has been preserved.",
    "ambiguous_identity": "More than one accepted record matches this meaning. No arbitrary record was selected for replacement.",
    "duplicate_address": "The supplied records repeat or disagree about the same temporal fact. Their order does not determine which one is accepted.",
}


class UnsupportedTemporal(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(MESSAGES[reason])

    def as_dict(self):
        return {"code": "unsupported_temporal_revision", "reason": self.reason, "message": str(self)}
