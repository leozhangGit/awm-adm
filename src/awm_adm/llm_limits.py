"""Stage-independent call policy and finite aggregate arithmetic.

Stored CallLimits remain complete numeric records. Resolve defaults only when
creating new work, never while loading a retained grant or episode.
"""

from pydantic import Field

from .contracts import CallLimits, ClosedModel
from .learning.diagnostics import LimitExceeded
from .runtime.protocol import RuntimeFault

QUEUE_MS = 60_000
FINISH_MS = 60_000
DELIVERY_MS = 3_000
POLICY = "awm-adm-llm-limits/1"
MAX_TEACH_CALLS = 26
DEFAULT_INPUT = 256_000
DEFAULT_OUTPUT = 32_768
DEFAULT_EXECUTION_MS = 360_000


class CallPolicy(ClosedModel):
    max_input_tokens: int = Field(default=DEFAULT_INPUT, ge=1, le=1_050_000)
    max_output_tokens: int = Field(default=DEFAULT_OUTPUT, ge=1, le=100_000)
    max_duration_ms: int = Field(default=DEFAULT_EXECUTION_MS, ge=1, le=600_000)

    def limits(self):
        return {"max_calls": 1, **self.model_dump()}


class LLMPolicy(ClosedModel):
    call: CallPolicy = Field(default_factory=CallPolicy)


class CallOptions(CallLimits):
    """API defaults document the standard installation; omitted fields resolve there."""

    max_input_tokens: int = Field(default=DEFAULT_INPUT, ge=1, le=1_050_000)
    max_output_tokens: int = Field(default=DEFAULT_OUTPUT, ge=1, le=100_000)
    max_duration_ms: int = Field(default=DEFAULT_EXECUTION_MS, ge=1, le=600_000)


def request_body(model, source, groups=("call_limits",)):
    """Materialize semantic defaults, retaining omission within limit groups."""
    value = model.model_validate(source)
    body = value.model_dump()
    for group in groups:
        body[group] = getattr(value, group).model_dump(exclude_unset=True)
    return body


def resolve_call(policy, overrides=None):
    ceiling = policy.limits() if isinstance(policy, CallPolicy) else dict(policy)
    result = CallLimits.model_validate(ceiling | (overrides or {})).model_dump()
    for name, value in result.items():
        if value > ceiling[name]:
            raise LimitExceeded("call", name, value, ceiling[name])
    return result


def aggregate(call, count):
    if type(count) is not int or not 0 <= count <= 10000:
        raise ValueError("Invalid bounded provider call count")
    return {
        "max_calls": count,
        "max_input_tokens": count * call["max_input_tokens"],
        "max_output_tokens": count * call["max_output_tokens"],
        "max_duration_ms": count * (QUEUE_MS + call["max_duration_ms"]) + FINISH_MS,
    }


def capture(policy, count):
    call = resolve_call(policy)
    return {"profile": POLICY, "call": call, "aggregate": aggregate(call, count)}


def captured_call(owner):
    profile = owner.get("llm_limits")
    if not profile or profile.get("profile") != POLICY:
        raise RuntimeFault(
            "stale_context",
            "Retained work has no captured shared call policy; submit a new request to continue",
        )
    return dict(profile["call"])


def replay_body(submitted, captured, groups=("call_limits",)):
    """Resolve an old same-identity request against its captured, not current, defaults."""
    return submitted | {g: captured[g] | submitted[g] for g in groups}


def teaching_calls(children):
    return 2 + sum(
        0 if child.get("kind") == "reaffirmation" else 6 if child.get("material") else 2 for child in children
    )


def delivery_deadline(grant):
    """Captured result-delivery bound; older leases retain their original expiry."""
    return grant.get("delivery_deadline", grant["expires"])
