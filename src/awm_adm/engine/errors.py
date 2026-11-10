"""Typed failures; missing knowledge and exhausted checks are never false answers."""


class ADMError(Exception):
    code = "adm_error"

    def __init__(self, message, **context):
        super().__init__(message)
        self.context = context

    def as_dict(self):
        from .data import thaw

        return {"code": self.code, "message": str(self), "context": thaw(self.context)}


class InvalidIR(ADMError):
    code = "invalid_ir"


class TypeMismatch(ADMError):
    code = "type_error"


class KnowledgeGap(ADMError):
    code = "knowledge_gap"


class UnsupportedFeature(ADMError):
    code = "unsupported_feature"


class EvaluationError(ADMError):
    code = "evaluation_error"


class Rejected(ADMError):
    code = "admission_rejected"


class ResourceLimit(ADMError):
    code = "resource_exhausted"


class IllegalAction(ADMError):
    code = "illegal_action"


class Conflict(ADMError):
    code = "conflict"


class NotFound(ADMError):
    code = "not_found"


class StorageError(ADMError):
    code = "storage_error"


class Interrupted(ADMError):
    code = "interrupted"
