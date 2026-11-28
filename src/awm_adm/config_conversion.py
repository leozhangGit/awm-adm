"""Explicit offline conversion of installation configuration, never retained work."""

from copy import deepcopy

from .config import AppConfig, Quotas
from .contracts import CallLimits
from .llm_limits import CallPolicy


def convert(source, *, call=None):
    raw = deepcopy(source)
    if raw.get("config_profile") != "awm-adm-config/2" or "llm" in raw:
        raise ValueError("Supply an unmixed awm-adm-config/2 configuration")
    learning = raw.setdefault("learning", {})
    old = {}
    defaults = {
        "preparation_timeout_ms": 180000,
        "acquisition_timeout_ms": 180000,
        "extraction_timeout_ms": 180000,
        "extraction_max_output_tokens": 16384,
        "call": {
            "max_calls": 1,
            "max_input_tokens": 128000,
            "max_output_tokens": 8192,
            "max_duration_ms": 60000,
        },
    }
    custom = []
    for name, expected in defaults.items():
        value = learning.pop(name, expected)
        if name == "call":
            value = CallLimits.model_validate(value).model_dump()
        elif type(value) is not int or value <= 0:
            raise ValueError("Legacy execution limits must be positive integers")
        old["learning." + name] = value
        if (expected | value if isinstance(expected, dict) else value) != expected:
            custom.append("learning." + name)
    episode = learning.setdefault("episode", {})
    for name, expected in {
        "max_input_tokens": 384000,
        "max_output_tokens": 24576,
        "max_duration_ms": 720000,
    }.items():
        value = episode.pop(name, expected)
        old["learning.episode." + name] = value
        if value != expected:
            custom.append("learning.episode." + name)
    if "quotas" in learning:
        old["learning.quotas"] = Quotas.model_validate(learning.pop("quotas")).model_dump()
    if custom and call is None:
        raise ValueError("Custom legacy limits require an explicit shared call profile: " + ", ".join(custom))
    policy = CallPolicy.model_validate(call or {})
    raw.update(config_profile="awm-adm-config/3", llm={"call": policy.model_dump()})
    result = AppConfig.model_validate(raw)
    return result, {
        "removed": old,
        "shared_call": policy.model_dump(),
        "custom_fields": custom,
        "aggregate_defaults": "derived from permitted calls; old task limits remain captured",
    }


def toml(value):
    """Emit this closed scalar/table configuration without a new runtime dependency."""
    import json

    lines = []

    def table(data, path):
        if path:
            lines.extend(["", "[" + ".".join(path) + "]"])
        for key, item in data.items():
            if not isinstance(item, dict):
                lines.append(f"{key} = {json.dumps(item, ensure_ascii=False)}")
        for key, item in data.items():
            if isinstance(item, dict):
                table(item, (*path, key))

    table(value, ())
    return "\n".join(lines) + "\n"
