"""Owner-supplied finite behavioral contracts, separate from candidate evidence."""

from collections.abc import Mapping

from . import types as ty
from .artifacts import digest
from .budget import Budget
from .data import encode, name, read_json, shape, thaw
from .diagnostics import bounded
from .errors import ADMError, IllegalAction, InvalidIR, Rejected, ResourceLimit
from .expressions import Interpreter
from .model import declaration_references
from .requests import identifier

PROFILE = "adm-conformance/0.1"
INVARIANT_PROFILE = "adm-conformance/0.2"
SUPPORTED_PROFILES = (PROFILE, INVARIANT_PROFILE)
EMPTY_POLICY = {"profile": PROFILE, "contracts": []}


class ConformanceError(Rejected):
    code = "conformance_failed"


def _invariant_inputs(check, budget):
    """Resolve only owner definitions: learned code cannot weaken this predicate."""
    if declaration_references({"carrier": check["state_type"], "predicate": check["predicate"]}):
        raise InvalidIR("Invariant carrier and predicate must be independent of learned declarations")
    interpreter = Interpreter({}, {})
    carrier = dict(_parameters({"state": check["state_type"]}, budget))["state"]
    interpreter.expect(interpreter.infer(check["predicate"], {"state": carrier}, budget), ty.BOOL)
    initial = check["initial_states"]
    if not isinstance(initial, list) or not initial:
        raise InvalidIR("Invariant needs at least one owner-specified initial state")
    for state in initial:
        interpreter.require_value(carrier, state, budget)
        if interpreter.evaluate(check["predicate"], {"state": state}, budget) is not True:
            raise InvalidIR("Invariant does not contain an owner-specified initial state", state=state)
    return interpreter, carrier


def _invariant_actions(model, check):
    selection = check["selection"]
    return (
        sorted(s for s in model._transitions if s.startswith(check["module"] + "."))
        if selection["kind"] == "module_all"
        else sorted(selection["transitions"])
    )


def _check_invariant(model, check, budget):
    interpreter, carrier = _invariant_inputs(check, budget)
    actions = _invariant_actions(model, check)
    for symbol in actions:
        if symbol not in model._transitions or model._transitions[symbol]["state"] != carrier:
            raise ConformanceError("Invariant action must use the exact owner state carrier", symbol=symbol)
    states = invariant_states = cases = legal = 0
    for state in ty.members(carrier, budget, interpreter.evaluate):
        states += 1
        if interpreter.evaluate(check["predicate"], {"state": state}, budget) is not True:
            continue
        invariant_states += 1
        for symbol in actions:
            for parameters in ty.members(
                model._transitions[symbol]["parameters"], budget, model._interpreter.evaluate
            ):
                cases += 1
                try:
                    successor = model.step(symbol, state, parameters, budget=budget)["value"]
                except IllegalAction:
                    continue
                legal += 1
                if interpreter.evaluate(check["predicate"], {"state": successor}, budget) is not True:
                    raise ConformanceError(
                        "Legal action violates the owner invariant",
                        state=thaw(state),
                        transition=symbol,
                        parameters=thaw(parameters),
                        successor=successor,
                    )
    return {
        "cases": cases,
        "states": states,
        "invariant_states": invariant_states,
        "legal_actions": legal,
        "selection": thaw(check["selection"]),
        "transitions": actions,
        "guarantee": "exhaustive_finite",
    }


def _parameters(spec, budget):
    if not isinstance(spec, Mapping):
        raise InvalidIR("Contract params must be an object")
    # A candidate must not shrink the test domain or make checks vacuous.
    if declaration_references(spec):
        raise InvalidIR("Contract parameter types must be independent of learned declarations")
    interpreter = Interpreter({}, {})
    result = []
    for key, value in sorted(spec.items()):
        carrier = interpreter.type(value, budget)
        ty.check_refinements(carrier, budget, interpreter.evaluate)
        if next(ty.members(carrier, budget, interpreter.evaluate), None) is None:
            raise InvalidIR("Contract parameter carriers must be inhabited", parameter=key)
        result.append((name(key), carrier))
    return tuple(result)


def validate_policy(source, *, budget=None):
    budget = budget if budget is not None else Budget()
    policy = thaw(read_json(source))
    shape(policy, ("profile", "contracts"))
    if policy["profile"] not in SUPPORTED_PROFILES:
        raise InvalidIR("Unsupported conformance profile")
    contracts = policy["contracts"]
    if not isinstance(contracts, list) or len(contracts) > 32:
        raise InvalidIR("Policy must contain at most 32 contracts")
    ids = set()
    for contract in contracts:
        budget.tick()
        shape(contract, ("contract_id", "origin", "required_symbols", "checks"))
        contract_id = identifier(contract["contract_id"])
        if contract_id in ids:
            raise InvalidIR("Duplicate conformance contract ID")
        ids.add(contract_id)
        if not isinstance(contract["origin"], str) or not contract["origin"].strip():
            raise InvalidIR("Contract needs an explicit local source")
        required = contract["required_symbols"]
        if not isinstance(required, list) or not required:
            raise InvalidIR("Contract needs required_symbols")
        for symbol in required:
            name(symbol, qualified=True)
        if len(set(required)) != len(required):
            raise InvalidIR("Duplicate required symbol")
        checks = contract["checks"]
        if not isinstance(checks, list) or not 1 <= len(checks) <= 256:
            raise InvalidIR("Contract needs between 1 and 256 checks")
        check_ids = set()
        for check in checks:
            budget.tick()
            if not isinstance(check, Mapping):
                raise InvalidIR("Contract check must be an object")
            kind = check.get("kind")
            if not isinstance(kind, str):
                raise InvalidIR("Conformance check kind must be a string")
            fields = {
                "value": ("expression", "expected"),
                "goal": ("goal", "state", "expected"),
                "transition": ("transition", "state", "parameters", "legal", "next"),
                "interface": ("symbol", "expected"),
                "invariant": ("module", "state_type", "predicate", "initial_states", "selection"),
            }.get(kind)
            if fields is None:
                raise InvalidIR("Unsupported conformance check kind")
            if kind == "invariant" and policy["profile"] != INVARIANT_PROFILE:
                raise InvalidIR("Invariant checks require adm-conformance/0.2")
            shape(
                check,
                ("id", "kind", *fields, *(("params",) if kind not in ("interface", "invariant") else ())),
            )
            check_id = identifier(check["id"])
            if check_id in check_ids:
                raise InvalidIR("Duplicate conformance check ID")
            check_ids.add(check_id)
            if kind == "invariant":
                module = name(check["module"])
                selection = check["selection"]
                if not isinstance(selection, Mapping):
                    raise InvalidIR("Invariant needs an action selection")
                if selection.get("kind") == "module_all":
                    shape(selection, ("kind",))
                elif selection.get("kind") == "explicit":
                    shape(selection, ("kind", "transitions"))
                    actions = selection["transitions"]
                    if not isinstance(actions, list):
                        raise InvalidIR("Invariant transitions must be an array")
                    for symbol in actions:
                        name(symbol, qualified=True)
                        if not symbol.startswith(module + ".") or symbol not in required:
                            raise InvalidIR(
                                "Explicit invariant actions must be required symbols in its module"
                            )
                    if len(set(actions)) != len(actions):
                        raise InvalidIR("Duplicate invariant action")
                else:
                    raise InvalidIR("Unsupported invariant action selection")
                _invariant_inputs(check, budget)
                continue
            refs = declaration_references(check)
            for field in ("symbol", "goal", "transition"):
                if field in check:
                    refs.add(name(check[field], qualified=True))
            if refs - set(required):
                raise InvalidIR(
                    "Every check dependency must be a required symbol", symbols=sorted(refs - set(required))
                )
            if kind == "interface":
                expected = check["expected"]
                if not isinstance(expected, Mapping) or "kind" not in expected:
                    raise InvalidIR("Interface check needs declaration metadata")
                if set(expected) & {"body", "legal", "next", "cost"}:
                    raise InvalidIR("Interface checks cannot prescribe executable bodies")
            else:
                _parameters(check["params"], budget)
                for field in fields:
                    if field not in ("goal", "transition") and not isinstance(check[field], Mapping):
                        raise InvalidIR("Conformance expressions must be IR objects", field=field)
    return policy


def _check(model, check, budget):
    """Exhaust every owner-defined input assignment; stop at the first failure."""
    if check["kind"] == "invariant":
        return _check_invariant(model, check, budget)
    if check["kind"] == "interface":
        source = model.document()["declarations"][check["symbol"]]
        actual = {k: v for k, v in source.items() if k not in ("body", "legal", "next", "cost")}
        if encode(actual) != encode(check["expected"]):
            raise ConformanceError(
                "Declaration interface differs from its local contract",
                expected=check["expected"],
                actual=actual,
            )
        return 1
    params = _parameters(check["params"], budget)
    interpreter = model._interpreter
    expressions = {
        key: check[key]
        for key in ("expression", "expected", "state", "parameters", "legal", "next")
        if key in check
    }
    inferred = {key: interpreter.infer(expr, dict(params), budget) for key, expr in expressions.items()}
    if check["kind"] == "transition":
        interpreter.expect(inferred["legal"], ty.BOOL)
    elif check["kind"] == "goal":
        interpreter.expect(inferred["expected"], ty.BOOL)
    cases = 0
    for bindings in ty.assignments(params, budget, interpreter.evaluate):
        budget.tick()

        def evaluate(key):
            value = interpreter.evaluate(expressions[key], bindings, budget)
            interpreter.require_value(inferred[key], value, budget)
            return thaw(value)

        try:
            if check["kind"] == "value":
                expected, actual = evaluate("expected"), evaluate("expression")
            elif check["kind"] == "goal":
                expected = evaluate("expected")
                actual = model.goal(check["goal"], evaluate("state"), budget=budget)["value"]
            else:
                state, parameters = evaluate("state"), evaluate("parameters")
                expected = {"legal": evaluate("legal")}
                if expected["legal"]:
                    expected["next"] = evaluate("next")
                try:
                    actual = {
                        "legal": True,
                        "next": model.step(check["transition"], state, parameters, budget=budget)["value"],
                    }
                except IllegalAction:
                    actual = {"legal": False}
            if encode(actual) != encode(expected):
                raise ConformanceError(
                    "Candidate disagrees with its local behavioral contract",
                    bindings=bindings,
                    expected=expected,
                    actual=actual,
                )
        except ResourceLimit:
            raise
        except ConformanceError:
            raise
        except ADMError as error:
            raise ConformanceError(
                "Contract case could not be evaluated", bindings=bindings, cause=error.as_dict()
            ) from error
        cases += 1
    return cases


def verify_policy(source, model, *, previous=None, budget=None):
    budget = budget if budget is not None else Budget()
    policy = validate_policy(source, budget=budget)
    results = []
    for contract in policy["contracts"]:
        required = set(contract["required_symbols"])
        present = set(model.index) | (set(previous.index) if previous is not None else set())
        result = {"contract_id": contract["contract_id"], "digest": digest(encode(contract))}
        action_present = any(
            check["kind"] == "invariant"
            and (
                _invariant_actions(model, check)
                or (previous is not None and _invariant_actions(previous, check))
            )
            for check in contract["checks"]
            if check.get("selection", {}).get("kind") == "module_all"
        )
        if not required & present and not action_present:
            results.append({**result, "status": "dormant"})
            continue
        missing = required - model.index.keys()
        if missing:
            raise ConformanceError(
                "Candidate omits symbols required by a local contract",
                contract_id=contract["contract_id"],
                missing_symbols=sorted(missing),
            )
        checks = []
        dependencies = set(required)
        for check in contract["checks"]:
            try:
                cases = _check(model, check, budget)
            except ResourceLimit:
                raise
            except ADMError as error:
                raise ConformanceError(
                    "Local conformance check failed",
                    contract_id=contract["contract_id"],
                    check_id=check["id"],
                    check=bounded(thaw(check), 4096),
                    cause=error.as_dict(),
                ) from error
            if isinstance(cases, dict):
                dependencies.update(cases["transitions"])
                checks.append({"id": check["id"], **cases})
            else:
                checks.append({"id": check["id"], "cases": cases})
        results.append(
            {
                **result,
                "status": "passed",
                "checks": checks,
                "dependencies": model.symbol_dependencies(dependencies),
            }
        )
    return {
        "profile": policy["profile"],
        "policy_digest": digest(encode(policy)),
        "theory_version": model.version,
        "status": "checked" if results else "not_configured",
        "contracts": results,
        "scope": "Exhaustive over the owner-supplied finite checks only; not a proof of empirical truth.",
    }
