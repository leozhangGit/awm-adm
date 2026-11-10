"""Finite carriers and lazy enumeration. Refinements are executable predicates."""

from collections.abc import Mapping
from dataclasses import dataclass

from .data import name, shape
from .errors import InvalidIR, ResourceLimit, TypeMismatch, UnsupportedFeature


@dataclass(frozen=True)
class Type:
    kind: str
    parts: tuple = ()


BOOL = Type("bool")


def integer(value):
    if type(value) is not int:
        raise InvalidIR("Expected an integer")
    return value


def parse(spec, resolve):
    if not isinstance(spec, Mapping):
        raise InvalidIR("A type must be an object")
    if "ref" in spec:
        shape(spec, ("ref",))
        return resolve(name(spec["ref"], qualified=True))
    kind = spec.get("kind")
    if kind == "bool":
        shape(spec, ("kind",))
        return BOOL
    if kind == "int":
        shape(spec, ("kind", "min", "max"))
        low, high = integer(spec["min"]), integer(spec["max"])
        if low > high:
            raise InvalidIR("Integer bounds are reversed")
        return Type(kind, (low, high))
    if kind == "enum":
        shape(spec, ("kind", "values"))
        values = spec["values"]
        if not isinstance(values, (tuple, list)) or any(type(v) is not str for v in values):
            raise InvalidIR("Enum values must be an array of strings")
        if len(values) > 64:
            raise ResourceLimit("Enum exceeds 64 alternatives")
        if len(set(values)) != len(values):
            raise InvalidIR("Duplicate enum value")
        return Type(kind, tuple(values))
    if kind in ("record", "sum"):
        key = "fields" if kind == "record" else "variants"
        shape(spec, ("kind", key))
        if not isinstance(spec[key], Mapping):
            raise InvalidIR("Fields or variants must be an object")
        if len(spec[key]) > 64:
            raise ResourceLimit("Type exceeds 64 components")
        return Type(kind, tuple((name(k), parse(v, resolve)) for k, v in sorted(spec[key].items())))
    if kind == "vector":
        shape(spec, ("kind", "element", "length"))
        length = integer(spec["length"])
        if not 0 <= length <= 32:
            raise ResourceLimit("Vector length must be between 0 and 32")
        return Type(kind, (parse(spec["element"], resolve), length))
    if kind == "refined":
        shape(spec, ("kind", "base", "where"))
        return Type(kind, (parse(spec["base"], resolve), spec["where"]))
    raise UnsupportedFeature("Unsupported type constructor", kind=kind)


def base(t):
    while t.kind == "refined":
        t = t.parts[0]
    return t


def compatible(left, right):
    """Static shape compatibility; finite execution discharges bounds/refinements."""
    left, right = base(left), base(right)
    if left.kind != right.kind:
        return False
    if left.kind == "int":
        return True
    if left.kind in ("record", "sum"):
        return tuple(k for k, _ in left.parts) == tuple(k for k, _ in right.parts) and all(
            compatible(a, b) for (_, a), (_, b) in zip(left.parts, right.parts)
        )
    if left.kind == "vector":
        return left.parts[1] == right.parts[1] and compatible(left.parts[0], right.parts[0])
    return left == right


def join(left, right):
    left, right = base(left), base(right)
    if not compatible(left, right):
        raise TypeMismatch("Expression branches have incompatible types")
    if left.kind == "int":
        return Type("int", (min(left.parts[0], right.parts[0]), max(left.parts[1], right.parts[1])))
    if left.kind in ("record", "sum"):
        return Type(left.kind, tuple((k, join(a, b)) for (k, a), (_, b) in zip(left.parts, right.parts)))
    if left.kind == "vector":
        return Type("vector", (join(left.parts[0], right.parts[0]), left.parts[1]))
    return left


def contains(t, value, budget, evaluate):
    budget.tick()
    if t.kind == "bool":
        return type(value) is bool
    if t.kind == "int":
        return type(value) is int and t.parts[0] <= value <= t.parts[1]
    if t.kind == "enum":
        return type(value) is str and value in t.parts
    if t.kind == "record":
        return (
            isinstance(value, Mapping)
            and set(value) == {k for k, _ in t.parts}
            and all(contains(child, value[k], budget, evaluate) for k, child in t.parts)
        )
    if t.kind == "sum":
        variants = dict(t.parts)
        return (
            isinstance(value, Mapping)
            and set(value) == {"tag", "value"}
            and type(value["tag"]) is str
            and value["tag"] in variants
            and contains(variants[value["tag"]], value["value"], budget, evaluate)
        )
    if t.kind == "vector":
        return (
            isinstance(value, (list, tuple))
            and len(value) == t.parts[1]
            and all(contains(t.parts[0], v, budget, evaluate) for v in value)
        )
    if t.kind == "refined":
        return (
            contains(t.parts[0], value, budget, evaluate)
            and evaluate(t.parts[1], {"value": value}, budget) is True
        )
    raise InvalidIR("Unknown internal type", kind=t.kind)


def assignments(fields, budget, evaluate):
    """Lazy Cartesian product; never materializes an unbounded iterator pool."""
    fields = tuple(fields)

    def descend(index, current):
        budget.tick()
        if index == len(fields):
            yield dict(current)
            return
        key, t = fields[index]
        for value in members(t, budget, evaluate):
            current[key] = value
            yield from descend(index + 1, current)
        current.pop(key, None)

    yield from descend(0, {})


def members(t, budget, evaluate):
    budget.tick()
    if t.kind in ("bool", "enum", "int"):
        values = (
            (False, True)
            if t.kind == "bool"
            else range(t.parts[0], t.parts[1] + 1)
            if t.kind == "int"
            else t.parts
        )
        for value in values:
            budget.tick()
            yield value
    elif t.kind == "record":
        yield from assignments(t.parts, budget, evaluate)
    elif t.kind == "sum":
        for tag, child in t.parts:
            for value in members(child, budget, evaluate):
                yield {"tag": tag, "value": value}
    elif t.kind == "vector":
        for values in assignments(tuple((str(i), t.parts[0]) for i in range(t.parts[1])), budget, evaluate):
            yield [values[str(i)] for i in range(t.parts[1])]
    elif t.kind == "refined":
        for value in members(t.parts[0], budget, evaluate):
            if evaluate(t.parts[1], {"value": value}, budget) is True:
                yield value
    else:
        raise InvalidIR("Unknown internal type", kind=t.kind)


def check_refinements(t, budget, evaluate, seen=None):
    """Establish totality of every refinement predicate, including unused components."""
    seen = {} if seen is None else seen
    if id(t) in seen:
        return
    # Retain objects: IDs can be reused after an inline type is released.
    seen[id(t)] = t
    if t.kind == "refined":
        check_refinements(t.parts[0], budget, evaluate, seen)
        for value in members(t.parts[0], budget, evaluate):
            evaluate(t.parts[1], {"value": value}, budget)
    elif t.kind in ("record", "sum"):
        for _, child in t.parts:
            check_refinements(child, budget, evaluate, seen)
    elif t.kind == "vector":
        check_refinements(t.parts[0], budget, evaluate, seen)
