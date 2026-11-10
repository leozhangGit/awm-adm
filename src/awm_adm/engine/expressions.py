"""Typed expression interpreter. No eval, imports, I/O, or host code in the IR."""

from collections.abc import Mapping
from dataclasses import dataclass

from . import types as ty
from .data import encode, name, shape, thaw
from .errors import EvaluationError, InvalidIR, KnowledgeGap, TypeMismatch, UnsupportedFeature


@dataclass(frozen=True)
class Function:
    params: tuple
    returns: ty.Type
    body: Mapping


class Interpreter:
    def __init__(self, types, functions):
        self.types = types
        self.functions = functions

    def type(self, spec, budget):
        budget.tick()

        def resolve(symbol):
            if symbol not in self.types:
                raise KnowledgeGap("Unknown type", symbol=symbol)
            return self.types[symbol]

        t = ty.parse(spec, resolve)
        self.validate_type(t, budget)
        return t

    def validate_type(self, t, budget):
        budget.tick()
        if t.kind == "refined":

            def no_calls(node):
                if isinstance(node, Mapping):
                    if node.get("op") == "call":
                        raise UnsupportedFeature(
                            "Refinement predicates cannot call named functions in finite-v0"
                        )
                    for key, value in node.items():
                        if not (node.get("op") == "literal" and key == "value"):
                            no_calls(value)
                elif isinstance(node, (tuple, list)):
                    for item in node:
                        no_calls(item)

            no_calls(t.parts[1])
            self.validate_type(t.parts[0], budget)
            self.expect(self.infer(t.parts[1], {"value": t.parts[0]}, budget), ty.BOOL)
        elif t.kind in ("record", "sum"):
            for _, child in t.parts:
                self.validate_type(child, budget)
        elif t.kind == "vector":
            self.validate_type(t.parts[0], budget)

    @staticmethod
    def expect(actual, expected):
        if not ty.compatible(actual, expected):
            raise TypeMismatch("Incompatible expression type", actual=actual.kind, expected=expected.kind)

    def infer(self, expr, env, budget):
        budget.tick()
        if not isinstance(expr, Mapping):
            raise InvalidIR("Expression must be an object")
        op = expr.get("op")
        if not isinstance(op, str):
            raise InvalidIR("Expression op must be a string")
        if op == "literal":
            shape(expr, ("op", "value"), ("type",))
            value = expr["value"]
            if "type" in expr:
                t = self.type(expr["type"], budget)
                if not ty.contains(t, value, budget, self.evaluate):
                    raise TypeMismatch("Literal is outside its declared type")
                return t
            if type(value) is bool:
                return ty.BOOL
            if type(value) is int:
                budget.integer(value)
                return ty.Type("int", (value, value))
            raise TypeMismatch("Non-numeric, non-Boolean literals require an explicit type")
        if op == "var":
            shape(expr, ("op", "name"))
            key = name(expr["name"])
            if key not in env:
                raise TypeMismatch("Unbound variable", variable=key)
            return env[key]
        if op == "get":
            shape(expr, ("op", "record", "field"))
            t = ty.base(self.infer(expr["record"], env, budget))
            key = name(expr["field"])
            if t.kind != "record" or key not in dict(t.parts):
                raise TypeMismatch("Unknown record field", field=key)
            return dict(t.parts)[key]
        if op in ("record", "update"):
            shape(expr, ("op", "fields", "record") if op == "update" else ("op", "fields"))
            if not isinstance(expr["fields"], Mapping):
                raise InvalidIR("Record fields must be an object")
            fields = {}
            if op == "update":
                original = ty.base(self.infer(expr["record"], env, budget))
                if original.kind != "record":
                    raise TypeMismatch("update requires a record")
                fields = dict(original.parts)
            for key, value in expr["fields"].items():
                name(key)
                inferred = self.infer(value, env, budget)
                if op == "update":
                    if key not in fields:
                        raise TypeMismatch("Cannot update an absent field", field=key)
                    self.expect(inferred, fields[key])
                fields[key] = inferred
            return ty.Type("record", tuple(sorted(fields.items())))
        if op == "if":
            shape(expr, ("op", "condition", "then", "else"))
            self.expect(self.infer(expr["condition"], env, budget), ty.BOOL)
            return ty.join(self.infer(expr["then"], env, budget), self.infer(expr["else"], env, budget))
        if op == "tag":
            shape(expr, ("op", "type", "tag", "value"))
            t = self.type(expr["type"], budget)
            plain = ty.base(t)
            tag = name(expr["tag"])
            if plain.kind != "sum" or tag not in dict(plain.parts):
                raise TypeMismatch("Unknown sum alternative", tag=tag)
            self.expect(self.infer(expr["value"], env, budget), dict(plain.parts)[tag])
            return t
        if op == "match":
            shape(expr, ("op", "value", "cases"))
            t = ty.base(self.infer(expr["value"], env, budget))
            cases = expr["cases"]
            if t.kind != "sum" or not isinstance(cases, Mapping) or set(cases) != {k for k, _ in t.parts}:
                raise TypeMismatch("match requires exactly one branch for every sum alternative")
            if not t.parts:
                raise UnsupportedFeature("Elimination of an empty sum needs an explicit result type")
            result = None
            for key, child in t.parts:
                case = cases[key]
                shape(case, ("bind", "body"))
                binder = name(case["bind"])
                inferred = self.infer(case["body"], {**env, binder: child}, budget)
                result = inferred if result is None else ty.join(result, inferred)
            return result
        if op == "vector":
            shape(expr, ("op", "type", "items"))
            t = self.type(expr["type"], budget)
            plain = ty.base(t)
            items = expr["items"]
            if plain.kind != "vector" or not isinstance(items, (list, tuple)) or len(items) != plain.parts[1]:
                raise TypeMismatch("Vector length or type mismatch")
            for item in items:
                self.expect(self.infer(item, env, budget), plain.parts[0])
            return t
        if op == "index":
            shape(expr, ("op", "vector", "index"))
            t = ty.base(self.infer(expr["vector"], env, budget))
            index = ty.base(self.infer(expr["index"], env, budget))
            if t.kind != "vector" or index.kind != "int":
                raise TypeMismatch("index requires a vector and integer")
            return t.parts[0]
        if op in ("forall", "exists"):
            shape(expr, ("op", "var", "type", "body"))
            binder = name(expr["var"])
            t = self.type(expr["type"], budget)
            self.expect(self.infer(expr["body"], {**env, binder: t}, budget), ty.BOOL)
            return ty.BOOL
        if op == "call":
            shape(expr, ("op", "function", "args"))
            symbol = name(expr["function"], qualified=True)
            if symbol not in self.functions:
                raise KnowledgeGap("Unknown function", symbol=symbol)
            function = self.functions[symbol]
            if not isinstance(expr["args"], Mapping) or set(expr["args"]) != {k for k, _ in function.params}:
                raise TypeMismatch("Function argument names do not match", symbol=symbol)
            for key, t in function.params:
                self.expect(self.infer(expr["args"][key], env, budget), t)
            return function.returns
        if op in ("not", "and", "or", "eq", "ne", "lt", "le", "gt", "ge", "add", "sub", "mul", "min", "max"):
            shape(expr, ("op", "args"))
            args = expr["args"]
            if not isinstance(args, (list, tuple)):
                raise InvalidIR("Operator arguments must be an array")
            if op not in ("and", "or") and len(args) != (1 if op == "not" else 2):
                raise InvalidIR("Wrong operator arity", op=op)
            ts = [ty.base(self.infer(arg, env, budget)) for arg in args]
            if op in ("not", "and", "or"):
                for t in ts:
                    self.expect(t, ty.BOOL)
                return ty.BOOL
            if op in ("eq", "ne"):
                self.expect(ts[0], ts[1])
                return ty.BOOL
            if any(t.kind != "int" for t in ts):
                raise TypeMismatch("Numeric operator requires integers", op=op)
            if op in ("lt", "le", "gt", "ge"):
                return ty.BOOL
            a, b = ts[0].parts
            c, d = ts[1].parts
            if op == "add":
                bounds = (a + c, b + d)
            elif op == "sub":
                bounds = (a - d, b - c)
            elif op == "mul":
                products = (a * c, a * d, b * c, b * d)
                bounds = (min(products), max(products))
            else:
                f = min if op == "min" else max
                bounds = (f(a, c), f(b, d))
            return ty.Type("int", tuple(budget.integer(v) for v in bounds))
        raise UnsupportedFeature("Unsupported expression operator", op=op)

    def evaluate(self, expr, env, budget):
        """Evaluate previously type-checked syntax under validated bindings."""
        budget.tick()
        op = expr["op"]

        def run(value):
            return self.evaluate(value, env, budget)

        if op == "literal":
            return thaw(expr["value"])
        if op == "var":
            return env[expr["name"]]
        if op == "get":
            return run(expr["record"])[expr["field"]]
        if op in ("record", "update"):
            result = dict(run(expr["record"])) if op == "update" else {}
            result.update({key: run(value) for key, value in expr["fields"].items()})
            return result
        if op == "if":
            return run(expr["then"] if run(expr["condition"]) else expr["else"])
        if op in ("tag", "vector"):
            value = (
                {"tag": expr["tag"], "value": run(expr["value"])}
                if op == "tag"
                else [run(item) for item in expr["items"]]
            )
            self.require_value(self.type(expr["type"], budget), value, budget)
            return value
        if op == "match":
            value = run(expr["value"])
            case = expr["cases"][value["tag"]]
            return self.evaluate(case["body"], {**env, case["bind"]: value["value"]}, budget)
        if op == "index":
            vector, index = run(expr["vector"]), run(expr["index"])
            if not 0 <= index < len(vector):
                raise EvaluationError("Vector index out of bounds", index=index)
            return vector[index]
        if op in ("forall", "exists"):
            t = self.type(expr["type"], budget)
            for value in ty.members(t, budget, self.evaluate):
                verdict = self.evaluate(expr["body"], {**env, expr["var"]: value}, budget)
                if op == "forall" and not verdict:
                    return False
                if op == "exists" and verdict:
                    return True
            return op == "forall"
        if op == "call":
            return self.call(expr["function"], {k: run(v) for k, v in expr["args"].items()}, budget)
        if op == "and":
            return all(run(arg) for arg in expr["args"])
        if op == "or":
            return any(run(arg) for arg in expr["args"])
        if op == "not":
            return not run(expr["args"][0])
        a, b = (run(arg) for arg in expr["args"])
        if op == "eq":
            return encode(a) == encode(b)
        if op == "ne":
            return encode(a) != encode(b)
        if op == "lt":
            return a < b
        if op == "le":
            return a <= b
        if op == "gt":
            return a > b
        if op == "ge":
            return a >= b
        if op == "add":
            return budget.integer(a + b)
        if op == "sub":
            return budget.integer(a - b)
        if op == "mul":
            return budget.integer(a * b)
        if op == "min":
            return min(a, b)
        if op == "max":
            return max(a, b)
        raise UnsupportedFeature("Unsupported expression operator", op=op)

    def require_value(self, t, value, budget):
        if not ty.contains(t, value, budget, self.evaluate):
            raise EvaluationError("Value violates its type, bounds, or refinement", value=thaw(value))

    def call(self, symbol, args, budget):
        budget.tick()
        if symbol not in self.functions:
            raise KnowledgeGap("Unknown function", symbol=symbol)
        function = self.functions[symbol]
        if not isinstance(args, Mapping) or set(args) != {k for k, _ in function.params}:
            raise TypeMismatch("Function argument names do not match", symbol=symbol)
        for key, t in function.params:
            self.require_value(t, args[key], budget)
        result = self.evaluate(function.body, args, budget)
        self.require_value(function.returns, result, budget)
        return result
