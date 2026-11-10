"""Admission and local execution of immutable, closed finite theories."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from . import algebra
from . import types as ty
from .artifacts import ArtifactStore, MemoryStore
from .budget import Budget
from .data import encode, freeze, module_name, name, read_json, shape, thaw
from .errors import (
    ADMError,
    IllegalAction,
    InvalidIR,
    KnowledgeGap,
    Rejected,
    ResourceLimit,
    TypeMismatch,
    UnsupportedFeature,
)
from .expressions import Function, Interpreter

PROFILE = "finite-v0"
CHECKER = "adm-finite/0.1"


@dataclass(frozen=True)
class Admission:
    status: str
    model: "Model | None"
    report: dict


def _references(value):
    result = set()
    if isinstance(value, Mapping):
        if set(value) == {"ref"} and isinstance(value["ref"], str):
            result.add(value["ref"])
        if value.get("op") == "call" and isinstance(value.get("function"), str):
            result.add(value["function"])
        for key, child in value.items():
            if not (value.get("op") == "literal" and key == "value"):
                result.update(_references(child))
    elif isinstance(value, (tuple, list)):
        for child in value:
            result.update(_references(child))
    return result


def declaration_references(declaration):
    """All syntactic dependencies, including algebraic presentation maps."""
    result = _references(declaration)
    if isinstance(declaration, Mapping) and declaration.get("kind") == "presentation":
        for field in algebra.MAP_FIELDS & declaration.keys():
            result.add(name(declaration[field], qualified=True))
    return result


def _order(declarations, graph, budget):
    active, visited, ordered = set(), set(), []

    def visit(symbol, depth=0):
        budget.tick()
        if symbol not in declarations:
            raise KnowledgeGap("Unknown dependency", symbol=symbol)
        if symbol in active:
            raise InvalidIR("Recursive definitions or types are not supported", symbol=symbol)
        if depth > 48:
            raise ResourceLimit("Dependency depth exceeds 48")
        if symbol in visited:
            return
        active.add(symbol)
        for dependency in sorted(graph[symbol]):
            visit(dependency, depth + 1)
        active.remove(symbol)
        visited.add(symbol)
        ordered.append(symbol)

    for symbol in sorted(declarations):
        visit(symbol)
    return ordered


class Model:
    """Use admit() or empty(); only fully checked models are returned to callers."""

    def __init__(self, document, interpreter, transitions, goals, graph, index, version, report, store):
        self._document = document
        self._interpreter = interpreter
        self._transitions = freeze(transitions)
        self._goals = freeze(goals)
        self._graph = MappingProxyType({k: frozenset(v) for k, v in graph.items()})
        self._index = MappingProxyType(dict(index))
        self._version = version
        self._report = freeze(report)
        self._store = store

    @property
    def version(self):
        return self._version

    @property
    def index(self):
        return dict(self._index)

    @property
    def report(self):
        return thaw(self._report)

    @classmethod
    def empty(cls):
        return admit({"profile": PROFILE, "declarations": {}}).model

    def document(self):
        return thaw(self._document)

    def artifacts(self):
        """Return immutable bytes for the root and its complete declaration closure."""
        return {key: self._store.get(key) for key in {self.version, *self._index.values()}}

    def validate_value(self, type_spec, value, *, budget=None):
        """Validate portable typed data against this exact theory, without changing state."""
        budget = budget if budget is not None else Budget()
        spec = read_json(type_spec)
        value = read_json(value, encoded=False)
        carrier = self._interpreter.type(spec, budget)
        ty.check_refinements(carrier, budget, self._interpreter.evaluate)
        self._interpreter.require_value(carrier, value, budget)
        return {"type": thaw(spec), "value": thaw(value), "theory_version": self.version}

    def values(self, type_spec, *, budget=None):
        """Enumerate a finite carrier locally, including its refinement predicates."""
        budget = budget if budget is not None else Budget()
        carrier = self._interpreter.type(read_json(type_spec), budget)
        ty.check_refinements(carrier, budget, self._interpreter.evaluate)
        for value in ty.members(carrier, budget, self._interpreter.evaluate):
            yield thaw(value)

    def capabilities(self, *, budget=None):
        budget = budget if budget is not None else Budget()
        declarations = {}
        for symbol, declaration in self._document["declarations"].items():
            budget.tick()
            declarations[symbol] = declaration["kind"]
        return {
            "profile": PROFILE,
            "declarations": declarations,
            "modules": sorted({s.rsplit(".", 1)[0] for s in declarations}),
        }

    def expression_dependencies(self, expression):
        return self.symbol_dependencies(_references(read_json(expression)))

    def symbol_dependencies(self, symbols):
        result = {}
        for symbol in sorted(symbols):
            self._require_symbol(symbol)
            result[symbol] = self._index[symbol]
            result.update(self.dependencies(symbol, transitive=True))
        return dict(sorted(result.items()))

    def dependencies(self, symbol, transitive=False):
        self._require_symbol(symbol)
        found = set(self._graph[symbol])
        if transitive:
            pending = list(found)
            while pending:
                for item in self._graph[pending.pop()]:
                    if item not in found:
                        found.add(item)
                        pending.append(item)
        return {s: self._index[s] for s in sorted(found)}

    def _require_symbol(self, symbol):
        if symbol not in self._index:
            raise KnowledgeGap("Unknown symbol", symbol=symbol)

    def _result(self, value, budget):
        return {
            "value": thaw(value),
            "theory_version": self.version,
            "guarantee": "computed",
            "work": budget.used,
        }

    def evaluate(self, expression, *, budget=None):
        budget = budget if budget is not None else Budget()
        expr = read_json(expression)
        t = self._interpreter.infer(expr, {}, budget)
        result = self._interpreter.evaluate(expr, {}, budget)
        self._interpreter.require_value(t, result, budget)
        return self._result(result, budget)

    def check_claim(self, proposition, *, budget=None):
        budget = budget if budget is not None else Budget()
        expr = read_json(proposition)
        self._interpreter.expect(self._interpreter.infer(expr, {}, budget), ty.BOOL)
        value = self._interpreter.evaluate(expr, {}, budget)
        return {**self._result(value, budget), "verdict": "established" if value else "refuted"}

    def planning_scope(self, module, goal, transitions=None, *, budget=None):
        budget = budget if budget is not None else Budget()
        module_name(module)
        name(goal, qualified=True)
        if not goal.startswith(module + "."):
            raise InvalidIR("Goal must belong to the requested module")
        if goal not in self._goals:
            raise KnowledgeGap("Unknown goal", symbol=goal)
        if transitions is None:
            transitions = sorted(s for s in self._transitions if s.startswith(module + "."))
        elif not isinstance(transitions, (list, tuple)):
            raise InvalidIR("transitions must be an array")
        else:
            for symbol in transitions:
                name(symbol, qualified=True)
            if len(set(transitions)) != len(transitions):
                raise InvalidIR("Duplicate transition in planning scope")
            transitions = sorted(transitions)
        for symbol in transitions:
            budget.tick()
            if not symbol.startswith(module + "."):
                raise InvalidIR("Selected transitions must belong to the requested module", symbol=symbol)
            if symbol not in self._transitions:
                raise KnowledgeGap("Unknown transition", symbol=symbol)
            if self._transitions[symbol]["state"] != self._goals[goal]["state"]:
                raise TypeMismatch(
                    "Planning requires one exact state carrier; select compatible transitions explicitly",
                    symbol=symbol,
                )
        return {
            "module": module,
            "goal": goal,
            "transitions": transitions,
            "state_type": thaw(self._document["declarations"][goal]["state"]),
            "dependencies": self.symbol_dependencies([goal, *transitions]),
        }

    def successors(self, transitions, state, *, budget):
        """Enumerate every legal action through the kernel's checked step operation."""
        for symbol in transitions:
            if symbol not in self._transitions:
                raise KnowledgeGap("Unknown transition", symbol=symbol)
            for parameters in ty.members(
                self._transitions[symbol]["parameters"], budget, self._interpreter.evaluate
            ):
                try:
                    result = self.step(symbol, state, parameters, budget=budget)
                except IllegalAction:
                    continue
                action = {"transition": symbol, "parameters": thaw(parameters)}
                if "cost" in result:
                    action["cost"] = result["cost"]
                yield action, result["value"]

    def call(self, symbol, arguments, *, budget=None):
        budget = budget if budget is not None else Budget()
        args = read_json(arguments, encoded=False)
        return self._result(self._interpreter.call(symbol, args, budget), budget)

    def step(self, symbol, state, parameters, *, budget=None):
        budget = budget if budget is not None else Budget()
        if symbol not in self._transitions:
            raise KnowledgeGap("Unknown transition", symbol=symbol)
        transition = self._transitions[symbol]
        state, parameters = read_json(state, encoded=False), read_json(parameters, encoded=False)
        e = self._interpreter
        e.require_value(transition["state"], state, budget)
        e.require_value(transition["parameters"], parameters, budget)
        env = {"state": state, "action": parameters}
        if not e.evaluate(transition["legal"], env, budget):
            raise IllegalAction("Action is not legal in this state", symbol=symbol)
        successor = e.evaluate(transition["next"], env, budget)
        e.require_value(transition["state"], successor, budget)
        result = self._result(successor, budget)
        if "cost" in transition:
            result["cost"] = e.evaluate(transition["cost"], env, budget)
            result["work"] = budget.used
        return result

    def goal(self, symbol, state, *, budget=None):
        budget = budget if budget is not None else Budget()
        if symbol not in self._goals:
            raise KnowledgeGap("Unknown goal", symbol=symbol)
        goal = self._goals[symbol]
        state = read_json(state, encoded=False)
        self._interpreter.require_value(goal["state"], state, budget)
        return self._result(self._interpreter.evaluate(goal["body"], {"state": state}, budget), budget)


def admit(source, *, budget=None, store: ArtifactStore | None = None):
    """Return accepted/rejected/inconclusive. No inactive candidate is executable."""
    budget = budget if budget is not None else Budget()
    store = store if store is not None else MemoryStore()
    current = None
    try:
        document = read_json(source)
        shape(document, ("profile", "declarations"))
        if document["profile"] != PROFILE:
            raise UnsupportedFeature("Unsupported execution profile", profile=document["profile"])
        declarations = document["declarations"]
        if not isinstance(declarations, Mapping):
            raise InvalidIR("declarations must be an object")
        graph = {}
        for symbol, declaration in declarations.items():
            current = name(symbol, qualified=True)
            if not isinstance(declaration, Mapping):
                raise InvalidIR("Declaration must be an object")
            graph[symbol] = declaration_references(declaration)
        ordered = _order(declarations, graph, budget)
        types, functions, transitions, goals = {}, {}, {}, {}
        e = Interpreter(types, functions)

        def resolve(symbol):
            if symbol not in types:
                raise KnowledgeGap("Expected a previously defined type", symbol=symbol)
            return types[symbol]

        for symbol in ordered:
            current = symbol
            spec = declarations[symbol]
            if spec.get("kind") == "type":
                shape(spec, ("kind", "type"))
                t = ty.parse(spec["type"], resolve)
                e.validate_type(t, budget)
                types[symbol] = t

        def params(spec):
            if not isinstance(spec, Mapping):
                raise InvalidIR("params must be an object")
            return tuple((name(k), e.type(v, budget)) for k, v in sorted(spec.items()))

        assertions = {}
        for symbol in ordered:
            current = symbol
            spec = declarations[symbol]
            kind = spec.get("kind")
            if kind == "function":
                shape(spec, ("kind", "params", "returns", "body"))
                functions[symbol] = Function(
                    params(spec["params"]), e.type(spec["returns"], budget), spec["body"]
                )
            elif kind == "assertion":
                shape(spec, ("kind", "params", "body"))
                assertions[symbol] = Function(params(spec["params"]), ty.BOOL, spec["body"])
            elif kind == "transition":
                shape(spec, ("kind", "state", "parameters", "legal", "next"), ("cost",))
                transitions[symbol] = {
                    **spec,
                    "state": e.type(spec["state"], budget),
                    "parameters": e.type(spec["parameters"], budget),
                }
            elif kind == "goal":
                shape(spec, ("kind", "state", "body"))
                goals[symbol] = {**spec, "state": e.type(spec["state"], budget)}
            elif kind not in ("type", "presentation"):
                raise UnsupportedFeature("Unsupported declaration kind", kind=kind)

        # Check all syntax before executing any candidate function body.
        for symbol, function in {**functions, **assertions}.items():
            current = symbol
            e.expect(e.infer(function.body, dict(function.params), budget), function.returns)
        for symbol, transition in transitions.items():
            current = symbol
            env = {"state": transition["state"], "action": transition["parameters"]}
            e.expect(e.infer(transition["legal"], env, budget), ty.BOOL)
            e.expect(e.infer(transition["next"], env, budget), transition["state"])
            if "cost" in transition and ty.base(e.infer(transition["cost"], env, budget)).kind != "int":
                raise InvalidIR("Transition cost must be an integer")
        for symbol, goal in goals.items():
            current = symbol
            e.expect(e.infer(goal["body"], {"state": goal["state"]}, budget), ty.BOOL)

        # A refinement must be a total predicate, even if no operation uses it.
        seen_types = {}

        def check_refinements(t):
            ty.check_refinements(t, budget, e.evaluate, seen_types)

        # Find inline types too; literal payloads are values, not IR syntax.
        def check_embedded_types(node):
            if isinstance(node, Mapping):
                kind = node.get("kind")
                if isinstance(kind, str) and kind in {
                    "bool",
                    "int",
                    "enum",
                    "record",
                    "sum",
                    "vector",
                    "refined",
                }:
                    check_refinements(e.type(node, budget))
                for key, child in node.items():
                    if not (node.get("op") == "literal" and key == "value"):
                        check_embedded_types(child)
            elif isinstance(node, (tuple, list)):
                for child in node:
                    check_embedded_types(child)

        for symbol in ordered:
            current = symbol
            check_embedded_types(declarations[symbol])

        checks = {
            "function_inputs": 0,
            "assertion_inputs": 0,
            "transition_inputs": 0,
            "legal_transitions": 0,
            "goal_states": 0,
        }
        presentations = {}
        for symbol in ordered:
            current = symbol
            if symbol in functions:
                function = functions[symbol]
                for args in ty.assignments(function.params, budget, e.evaluate):
                    e.call(symbol, args, budget)
                    checks["function_inputs"] += 1
            elif symbol in assertions:
                assertion = assertions[symbol]
                for args in ty.assignments(assertion.params, budget, e.evaluate):
                    if e.evaluate(assertion.body, args, budget) is not True:
                        raise Rejected("Assertion has a counterexample", symbol=symbol, inputs=thaw(args))
                    checks["assertion_inputs"] += 1
            elif symbol in transitions:
                transition = transitions[symbol]
                inhabited = False
                for state in ty.members(transition["state"], budget, e.evaluate):
                    inhabited = True
                    for action in ty.members(transition["parameters"], budget, e.evaluate):
                        env = {"state": state, "action": action}
                        checks["transition_inputs"] += 1
                        if e.evaluate(transition["legal"], env, budget):
                            successor = e.evaluate(transition["next"], env, budget)
                            e.require_value(transition["state"], successor, budget)
                            if "cost" in transition:
                                e.evaluate(transition["cost"], env, budget)
                            checks["legal_transitions"] += 1
                if not inhabited:
                    raise Rejected("Transition state type is empty", symbol=symbol)
            elif symbol in goals:
                goal = goals[symbol]
                inhabited = False
                for state in ty.members(goal["state"], budget, e.evaluate):
                    inhabited = True
                    e.evaluate(goal["body"], {"state": state}, budget)
                    checks["goal_states"] += 1
                if not inhabited:
                    raise Rejected("Goal state type is empty", symbol=symbol)
            elif declarations[symbol]["kind"] == "presentation":
                presentations[symbol] = algebra.check(declarations[symbol], e, budget)

        report = {
            "checker": CHECKER,
            "guarantee": "exhaustive_finite",
            "checks": checks,
            "presentations": presentations,
            "work": budget.used,
            "scope": "Closed finite definitions; empirical fidelity is not established.",
        }
        index = {}
        for symbol in ordered:
            budget.tick()
            artifact = {
                "profile": PROFILE,
                "symbol": symbol,
                "declaration": declarations[symbol],
                "dependencies": {s: index[s] for s in sorted(graph[symbol])},
            }
            index[symbol] = store.put(encode(artifact))
        # Work usage is diagnostic, not part of the content-addressed theory identity.
        root = {"profile": PROFILE, "declarations": index, "checker": CHECKER}
        version = store.put(encode(root))
        report["work"] = budget.used
        e.types = MappingProxyType(types)
        e.functions = MappingProxyType(functions)
        model = Model(document, e, transitions, goals, graph, index, version, report, store)
        return Admission("accepted", model, report)
    except ResourceLimit as error:
        return Admission(
            "inconclusive", None, {"error": error.as_dict(), "symbol": current, "work": budget.used}
        )
    except RecursionError:
        error = ResourceLimit("Interpreter recursion limit reached")
        return Admission(
            "inconclusive", None, {"error": error.as_dict(), "symbol": current, "work": budget.used}
        )
    except ADMError as error:
        return Admission("rejected", None, {"error": error.as_dict(), "symbol": current, "work": budget.used})
