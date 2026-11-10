"""Separate provider-reported usage from usage safe to settle locally."""


def response_metadata(provider, response):
    """Summarize optional metadata before incomplete output is discarded."""
    diagnostics, counters = {}, {}
    usage = response.get("usage")
    if isinstance(usage, dict):
        paths = (
            {
                "total_tokens": ("total_tokens",),
                "cached_input_tokens": ("input_tokens_details", "cached_tokens"),
                "reasoning_tokens": ("output_tokens_details", "reasoning_tokens"),
            }
            if provider == "openai"
            else {
                "cache_creation_input_tokens": ("cache_creation_input_tokens",),
                "cache_read_input_tokens": ("cache_read_input_tokens",),
            }
        )
        for name, path in paths.items():
            value = usage
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            if type(value) is int and 0 <= value < 2**53:
                counters[name] = value
    if counters:
        diagnostics["token_details"] = counters
    reasoning = response.get("reasoning") if provider == "openai" else None
    if isinstance(reasoning, dict):
        for key, allowed in (
            ("effort", ("none", "minimal", "low", "medium", "high", "xhigh", "max")),
            ("mode", ("standard", "pro")),
        ):
            value = reasoning.get(key)
            if value is not None:
                diagnostics["reasoning_" + key] = value if value in allowed else "unknown"
    summary = output_summary(provider, response)
    if summary is not None:
        diagnostics["output_summary"] = summary
    return diagnostics


def output_summary(provider, response):
    items = response.get("output" if provider == "openai" else "content")
    if not isinstance(items, list):
        return None  # Missing output is unknown, not a measured empty array.
    summary = dict.fromkeys(
        (
            "item_count",
            "message_items",
            "text_items",
            "reasoning_items",
            "other_items",
            "visible_text_parts",
            "visible_text_bytes",
        ),
        0,
    )
    summary["item_count"] = len(items)
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            return None
        kind = item["type"]
        texts = []
        if provider == "openai" and kind == "message":
            summary["message_items"] += 1
            content = item.get("content")
            if not isinstance(content, list):
                return None
            for part in content:
                if not isinstance(part, dict) or not isinstance(part.get("type"), str):
                    return None
                if part["type"] == "output_text":
                    texts.append(part.get("text"))
        elif provider == "anthropic" and kind == "text":
            summary["text_items"] += 1
            texts.append(item.get("text"))
        elif (provider == "openai" and kind == "reasoning") or (
            provider == "anthropic" and kind in ("thinking", "redacted_thinking")
        ):
            summary["reasoning_items"] += 1
        else:
            summary["other_items"] += 1
        for text in texts:
            if not isinstance(text, str):
                return None
            try:
                length = len(text.encode("utf-8"))
            except UnicodeEncodeError:
                return None
            summary["visible_text_parts"] += 1
            summary["visible_text_bytes"] += length
    return summary


def account_outcome(outcome, provider):
    """Also derives conservative views of pre-diagnostics retained outcomes.

    The caller owns the configuration; a provider cannot select the recorded
    exemption. Original historical outcomes are not rewritten by read views.
    """
    result = dict(outcome)
    diagnostics = dict(result.get("diagnostics") or {})
    known = result.get("usage")
    if known is not None:
        diagnostics["reported_usage"] = known
        if provider != "recorded" and known == {"input_tokens": 0, "output_tokens": 0}:
            diagnostics["usage_assessment"] = "zero_unverified"
            result["usage"] = None
        else:
            diagnostics["usage_assessment"] = "reported"
    elif diagnostics.get("usage_assessment") != "zero_unverified":
        diagnostics["usage_assessment"] = "missing_or_invalid"
    if result.get("error") == "output_incomplete":
        diagnostics.setdefault("incomplete_reason", "unknown")
        if diagnostics["incomplete_reason"] is None:
            diagnostics["incomplete_reason"] = "unknown"
    result["diagnostics"] = diagnostics
    return result
