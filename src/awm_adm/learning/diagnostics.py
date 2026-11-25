"""Service-authored capacity diagnostics, without prompts or provider exception text."""

from ..runtime.protocol import RuntimeFault


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
            "code": "input_capacity_exceeded",
            "message": message,
            "required_input_reservation": required,
            "available_input_reservation": available,
            "measurement": "conservative_input_estimate",
            "provider_call_dispatched": False,
        }


def capacity_diagnostic(error):
    # Only this locally constructed exception can supply these public fields.
    return error.diagnostic if isinstance(error, InputCapacityExceeded) else None
