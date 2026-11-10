"""Plain review labels derived from checked headers, not provider narrative."""


def carrier(spec):
    if "ref" in spec:
        return spec["ref"].rsplit(".", 1)[-1]
    kind = spec["kind"]
    if kind == "bool":
        return "true or false"
    if kind == "int":
        return f"whole numbers {spec['min']} through {spec['max']}"
    if kind == "enum":
        return ", ".join(spec["values"])
    if kind in {"record", "sum"}:
        fields = spec["fields" if kind == "record" else "variants"]
        return ("record: " if kind == "record" else "alternatives: ") + "; ".join(
            f"{name}: {carrier(t)}" for name, t in fields.items()
        )
    if kind == "vector":
        return f"{spec['length']} entries of {carrier(spec['element'])}"
    return "See the exact carrier in Details"


def headers(plan):
    lines = []
    for child in plan["children"]:
        items = []
        for symbol, h in child["interfaces"].items():
            aliases = [a for a, targets in plan["vocabulary"]["aliases"].items() if symbol in targets]
            label = aliases[0] if aliases else symbol.rsplit(".", 1)[-1]
            if h["kind"] == "type":
                scope = carrier(h["type"])
            elif h["kind"] in {"function", "assertion"}:
                inputs = "; ".join(f"{n}: {carrier(t)}" for n, t in h["params"].items()) or "no inputs"
                output = carrier(h["returns"]) if h["kind"] == "function" else "true or false"
                scope = f"{inputs}; result: {output}"
            else:
                scope = "state: " + carrier(h["state"])
                if "parameters" in h:
                    scope += "; action parameters: " + carrier(h["parameters"])
            items.append(f"{label} — {scope}")
        lines.append(items)
    return lines


def candidate(preview):
    """Bounded plain expressions for a semantic decision; full IR remains in Details."""
    remaining = [128]

    def expression(value, depth=0):
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 8 or not isinstance(value, dict):
            return "(see Details)"
        op = value.get("op", "expression")
        if op == "literal":
            return str(value.get("value"))[:100]
        if op == "var":
            return str(value.get("name", "input"))[:100]
        args = [expression(v, depth + 1) for v in value.get("args", [])[:16]]
        symbols = {
            "add": " + ",
            "sub": " − ",
            "mul": " × ",
            "eq": " = ",
            "lt": " < ",
            "le": " ≤ ",
            "and": " and ",
            "or": " or ",
        }
        if args and op in symbols:
            return "(" + symbols[op].join(args) + ")"
        if args:
            return op + "(" + ", ".join(args) + ")"
        return op + " (see Details for its fields)"

    return [
        {
            "symbol": symbol,
            "behavior": expression(body["body"])
            if "body" in body
            else "A " + body["kind"] + " declaration; review its exact carrier or action in Details.",
        }
        for symbol, body in list(preview["declarations"].items())[:32]
    ]
