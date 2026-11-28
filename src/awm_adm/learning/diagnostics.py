"""Service-authored capacity diagnostics, without prompts or provider exception text."""

from ..runtime.protocol import RuntimeFault


class LimitExceeded(RuntimeFault):
    def __init__(self, scope, name, required, available):
        message = (
            f"The {scope} {name} limit cannot accommodate this call "
            f"(required {required:,}; available {available:,}). This call was not sent."
        )
        super().__init__("invalid_limits", message)
        self.diagnostic = {
            "stage": "provider_reservation",
            "code": "aggregate_exhausted" if scope == "aggregate" else "call_limit_exceeded",
            "scope": scope,
            "limit": name,
            "required": required,
            "available": max(0, available),
            "message": message,
            "provider_call_dispatched": False,
        }


class InputCapacityExceeded(RuntimeFault):
    def __init__(self, required, available):
        message = (
            f"The prepared provider request needs an input reservation of {required:,}, "
            f"above the configured limit of {available:,}. This call was not sent. "
            "These figures are conservative size estimates, not measured token usage."
        )
        super().__init__("invalid_limits", message)
        self.diagnostic = {
            "stage": "provider_reservation",
            "scope": "call",
            "code": "input_capacity_exceeded",
            "message": message,
            "required_input_reservation": required,
            "available_input_reservation": available,
            "measurement": "conservative_input_estimate",
            "provider_call_dispatched": False,
        }


def capacity_diagnostic(error):
    # Only this locally constructed exception can supply these public fields.
    from ..temporal_evidence.capacity import CatalogCapacity

    return (
        error.diagnostic
        if isinstance(error, (InputCapacityExceeded, LimitExceeded, CatalogCapacity))
        else None
    )
