"""Describe local field bounds without expanding the provider's wire grammar."""

OBJECTIVE = (
    "A concise summary of this child's intended capability, facts or correction. "
    "Keep it within the stated character limit; do not copy the full policy or supplied material. "
    "Link every relevant original input through input_ids. Acquisition receives those original "
    "inputs separately with their detailed requirements, exceptions, assumptions and evidence. "
    "A shorter objective must not narrow or replace them."
)

INSTRUCTIONS = (
    "Schema descriptions state local character, item-count and numeric bounds. These limits "
    "still apply even when the shallow provider grammar does not encode them as keywords. "
    "Keep plan.summary, message, question and each child objective within their stated limits. "
    "Each child objective is a concise summary, not a duplicate of the full teaching request. "
    "Preserve the detailed meaning through exact input_ids and the structured plan; acquisition "
    "receives the linked original inputs separately. Do not truncate user material, drop an "
    "exception, invent a narrower domain or split an atomic correction just to fit a text field. "
)


def annotate_bounds(wire, schema, definitions):
    """Append trusted schema bounds after semantic descriptions have been installed."""
    if "$ref" in schema:
        schema = {**definitions[schema["$ref"].rsplit("/", 1)[1]], **schema}
    hints = []
    for low, high, unit in (
        ("minLength", "maxLength", "characters"),
        ("minItems", "maxItems", "items"),
        ("minProperties", "maxProperties", "properties"),
    ):
        if low in schema and high in schema:
            hints.append(f"{schema[low]} to {schema[high]} {unit}")
        elif low in schema:
            hints.append(f"at least {schema[low]} {unit}")
        elif high in schema:
            hints.append(f"at most {schema[high]} {unit}")
    for key, comparison in (
        ("minimum", "value >="),
        ("maximum", "value <="),
        ("exclusiveMinimum", "value >"),
        ("exclusiveMaximum", "value <"),
    ):
        if key in schema:
            hints.append(f"{comparison} {schema[key]}")
    if hints:
        wire["description"] = (
            wire.get("description", "") + " Local limits: " + "; ".join(hints) + "."
        ).strip()
    for name, child in schema.get("properties", {}).items():
        annotate_bounds(wire["properties"][name], child, definitions)
    for source, target in zip(schema.get("anyOf", []), wire.get("anyOf", []), strict=True):
        annotate_bounds(target, source, definitions)
    if "items" in schema:
        annotate_bounds(wire["items"], schema["items"], definitions)
    return wire
