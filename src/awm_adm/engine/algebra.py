"""Universal constructions in finite sets, checked by their elementwise bijections."""

from .data import encode, name, shape
from .errors import KnowledgeGap, Rejected, TypeMismatch, UnsupportedFeature
from .types import compatible, members

CONTRACTS = {
    "product": ("carrier", "left", "right", "project_left", "project_right"),
    "coproduct": ("carrier", "left", "right", "inject_left", "inject_right"),
    "pullback": (
        "carrier",
        "left",
        "right",
        "base",
        "left_map",
        "right_map",
        "project_left",
        "project_right",
    ),
    "equalizer": ("carrier", "source", "target", "first", "second", "include"),
}

MAP_FIELDS = {
    "project_left",
    "project_right",
    "inject_left",
    "inject_right",
    "left_map",
    "right_map",
    "first",
    "second",
    "include",
}


def check(spec, interpreter, budget):
    construction = spec.get("construction")
    if not isinstance(construction, str) or construction not in CONTRACTS:
        raise UnsupportedFeature("Unsupported algebraic presentation", construction=construction)
    shape(spec, ("kind", "construction", *CONTRACTS[construction]))
    ts = {k: interpreter.type(spec[k], budget) for k in CONTRACTS[construction] if k not in MAP_FIELDS}

    def values(t):
        return members(t, budget, interpreter.evaluate)

    def mapping(field, source, target):
        symbol = name(spec[field], qualified=True)
        if symbol not in interpreter.functions:
            raise KnowledgeGap("Unknown presentation map", symbol=symbol)
        fn = interpreter.functions[symbol]
        if (
            len(fn.params) != 1
            or not compatible(fn.params[0][1], source)
            or not compatible(fn.returns, target)
        ):
            raise TypeMismatch("Presentation map has the wrong signature", symbol=symbol)

        def apply(value):
            result = interpreter.call(symbol, {fn.params[0][0]: value}, budget)
            interpreter.require_value(target, result, budget)
            return result

        return apply

    expected = set()
    actual = set()

    def unique(key):
        budget.tick()
        if key in actual:
            raise Rejected("Presentation fails uniqueness", construction=construction)
        actual.add(key)

    if construction in ("product", "pullback"):
        left, right = ts["left"], ts["right"]
        pl = mapping("project_left", ts["carrier"], left)
        pr = mapping("project_right", ts["carrier"], right)
        if construction == "pullback":
            f = mapping("left_map", left, ts["base"])
            g = mapping("right_map", right, ts["base"])
        for a in values(left):
            for b in values(right):
                budget.tick()
                if construction == "product" or f(a) == g(b):
                    expected.add((encode(a), encode(b)))
        for c in values(ts["carrier"]):
            unique((encode(pl(c)), encode(pr(c))))
    elif construction == "coproduct":
        il = mapping("inject_left", ts["left"], ts["carrier"])
        ir = mapping("inject_right", ts["right"], ts["carrier"])
        for c in values(ts["carrier"]):
            expected.add(encode(c))
        for a in values(ts["left"]):
            unique(encode(il(a)))
        for b in values(ts["right"]):
            unique(encode(ir(b)))
    else:
        f = mapping("first", ts["source"], ts["target"])
        g = mapping("second", ts["source"], ts["target"])
        inclusion = mapping("include", ts["carrier"], ts["source"])
        for a in values(ts["source"]):
            if f(a) == g(a):
                expected.add(encode(a))
        for c in values(ts["carrier"]):
            unique(encode(inclusion(c)))
    if actual != expected:
        raise Rejected(
            "Presentation fails existence or compatibility",
            construction=construction,
            missing=len(expected - actual),
            extra=len(actual - expected),
        )
    return {"construction": construction, "checked_fibers": len(expected), "guarantee": "exhaustive_finite"}
