"""Audited billable bounds, independent of prompts and local admission.

See docs/PRICED_ALLOWANCES.md for primary sources and supported wire restrictions.
Synthetic rates/bounds are accepted only with the no-egress recorded transport.
"""

from ..runtime.protocol import loads
from .errors import AllowanceFault

INTERACTION = {"interpretation", "ask_interpretation", "ask_narration", "clarification"}
LEARNING = {"task_preparation", "acquisition", "extraction", "repair", "task_narration"}
PURPOSES = INTERACTION | LEARNING | {"connection_test"}
MAX_BILLABLE_INPUT = 1_050_000


def lane(purpose):
    if purpose not in PURPOSES:
        raise AllowanceFault("unsupported", "Unknown spending purpose")
    return "interaction" if purpose in INTERACTION else "learning"


def amount(inputs, outputs, price):
    return (inputs * price["input_micro_usd_per_million"] + 999_999) // 1_000_000 + (
        outputs * price["output_micro_usd_per_million"] + 999_999
    ) // 1_000_000


def profile(price, connection):
    if price["bound_profile"] == "recorded-test/1" and connection["provider"] == "recorded":
        return {"input_bound": 32000, "synthetic": True, "billing": "input_and_output_tokens"}
    if (
        price["bound_profile"] == "openai-4o-context/2026-11-08"
        and connection["provider"] == "openai"
        and connection["model"] == "gpt-4o-2024-08-06"
        and price["input_micro_usd_per_million"] >= 2_500_000
        and price["output_micro_usd_per_million"] >= 10_000_000
    ):
        return {"input_bound": 128000, "synthetic": False, "billing": "input_and_output_tokens"}
    if (
        price["bound_profile"] == "openai-5.6-luna-context/2026-11-09"
        and connection["provider"] == "openai"
        and connection["model"] == "gpt-5.6-luna"
        and price["input_micro_usd_per_million"] >= 500_000
        and price["output_micro_usd_per_million"] >= 1_800_000
    ):
        # Full context, long-context rates, and the default 30m cache-write
        # multiplier. Closed wire excludes 12h retention and extra charges.
        return {"input_bound": MAX_BILLABLE_INPUT, "synthetic": False, "billing": "input_and_output_tokens"}
    raise AllowanceFault(
        "unsupported",
        "No verified price/count bound for this exact configuration; install a supported audited price profile",
    )


def check_wire(raw, connection, bound, output_limit):
    body = loads(raw)
    expected = {
        "model",
        "instructions",
        "input",
        "text",
        "store",
        "stream",
        "max_output_tokens",
        "service_tier",
    }
    if (
        set(body) != expected
        or body["model"] != connection["model"]
        or body["service_tier"] != "default"
        or body["store"] is not False
        or body["stream"] is not False
        or body["max_output_tokens"] != output_limit
        or not isinstance(body["instructions"], str)
        or not isinstance(body["input"], list)
        or len(body["input"]) != 1
        or set(body["input"][0]) != {"role", "content"}
        or body["input"][0]["role"] != "user"
        or not isinstance(body["input"][0]["content"], str)
        or set(body["text"]) != {"format"}
        or body["text"]["format"].get("type") != "json_schema"
    ):
        raise AllowanceFault(
            "unsupported",
            "Priced dispatch supports only bounded text Responses wires without tools, media, sessions or other charges",
        )
    if not bound["synthetic"] and len(raw) > 2_097_152:
        raise AllowanceFault("resource_exhausted", "Priced wire exceeds transport bound")
