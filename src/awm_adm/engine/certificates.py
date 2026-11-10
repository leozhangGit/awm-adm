"""Finite invariant certificates bound to exact executable ADM definitions.

Certificates are untrusted data. Every verification rebuilds the complete local
transition table; no caller-supplied table or previous checker report is trusted.
"""

from collections import deque

from .artifacts import digest
from .budget import Budget
from .data import MAX_BYTES, encode, read_json, shape, thaw
from .errors import ADMError, Interrupted, InvalidIR, Rejected, ResourceLimit, UnsupportedFeature
from .results import bind_result, claim, selection

PROFILE = "adm-invariant/0.1"
CORRESPONDENCE = "adm-finite-table/0.1"
MAX_STATES = 4096
MAX_EDGES = 65536


def transition_table(model, module, goal, transitions=None, *, budget=None):
    """Reify every state and every legal action, retaining labels and costs.

    This is an exhaustive executable correspondence check, not a formal proof
    of the Python interpreter. State IDs are deterministic local table indices.
    """
    budget = budget if budget is not None else Budget()
    scope = model.planning_scope(module, goal, transitions, budget=budget)
    states, indices, edges, goals = [], {}, [], []
    retained = 0

    def retain(value):
        nonlocal retained
        retained += len(encode(value))
        if retained > MAX_BYTES:
            raise ResourceLimit("Certificate transition table exceeds byte limit", maximum=MAX_BYTES)

    for state in model.values(scope["state_type"], budget=budget):
        budget.tick()
        if len(states) >= MAX_STATES:
            raise ResourceLimit("Certificate state limit reached", maximum=MAX_STATES)
        key = encode(state)
        if key in indices:
            raise InvalidIR("Carrier enumeration produced a duplicate state")
        retain(state)
        indices[key] = len(states)
        states.append(state)
    for i, state in enumerate(states):
        budget.tick()
        if model.goal(goal, state, budget=budget)["value"]:
            goals.append(i)
        for action, successor in model.successors(scope["transitions"], state, budget=budget):
            budget.tick()
            if len(edges) >= MAX_EDGES:
                raise ResourceLimit("Certificate edge limit reached", maximum=MAX_EDGES)
            target = indices.get(encode(successor))
            if target is None:
                raise Rejected("Executable successor is outside the enumerated state carrier")
            edge = {"source": i, "target": target, "action": action}
            retain(edge)
            edges.append(edge)
    table = {
        "correspondence": CORRESPONDENCE,
        "theory_version": model.version,
        "scope": scope,
        "states": states,
        "goals": goals,
        "edges": edges,
    }
    if len(encode(table)) > MAX_BYTES:
        raise ResourceLimit("Certificate transition table exceeds byte limit", maximum=MAX_BYTES)
    return table


def build_certificate(
    model, module, initial_state, goal, *, transitions=None, invariant_states=None, budget=None
):
    """Propose an invariant set, or discover the reachable set by finite search.

    A reachable goal refutes this particular impossibility request. Exhaustion
    raises ResourceLimit; partial searches are never returned as certificates.
    Explicit invariant states are proposals, checked by verify_certificate.
    """
    budget = budget if budget is not None else Budget()
    table = transition_table(model, module, goal, transitions, budget=budget)
    initial = thaw(read_json(initial_state, encoded=False))
    indices = {encode(state): i for i, state in enumerate(table["states"])}
    if encode(initial) not in indices:
        raise InvalidIR("Initial state is outside the certificate carrier")
    if invariant_states is None:
        adjacent = [[] for _ in table["states"]]
        for edge in table["edges"]:
            budget.tick()
            adjacent[edge["source"]].append(edge["target"])
        start = indices[encode(initial)]
        reached, pending = {start}, deque([start])
        goals = set(table["goals"])
        while pending:
            budget.tick()
            state = pending.popleft()
            if state in goals:
                raise Rejected(
                    "A goal is reachable; no unreachability certificate exists in this scope",
                    goal_state=table["states"][state],
                )
            for target in adjacent[state]:
                budget.tick()
                if target not in reached:
                    reached.add(target)
                    pending.append(target)
        invariant_states = [table["states"][i] for i in sorted(reached)]
    certificate = {
        "profile": PROFILE,
        "kind": "unreachable",
        "theory_version": model.version,
        "module": module,
        "goal": goal,
        "transitions": table["scope"]["transitions"],
        "dependencies": table["scope"]["dependencies"],
        "table_digest": digest(encode(table)),
        "initial_state": initial,
        "invariant_states": thaw(read_json(invariant_states, encoded=False)),
    }
    # Apply wire limits even when the caller supplies decoded Python objects.
    return thaw(read_json(encode(certificate)))


def _premises(model, certificate, budget):
    shape(
        certificate,
        (
            "profile",
            "kind",
            "theory_version",
            "module",
            "goal",
            "transitions",
            "dependencies",
            "table_digest",
            "initial_state",
            "invariant_states",
        ),
    )
    if certificate["profile"] != PROFILE or certificate["kind"] != "unreachable":
        raise UnsupportedFeature("Unsupported certificate profile or proposition")
    if certificate["theory_version"] != model.version:
        raise Rejected("Certificate refers to a different theory version")
    transitions = certificate["transitions"]
    if not isinstance(transitions, list):
        raise InvalidIR("Certificate transitions must be an explicit array")
    table = transition_table(model, certificate["module"], certificate["goal"], transitions, budget=budget)
    if encode(transitions) != encode(table["scope"]["transitions"]):
        raise InvalidIR("Certificate transitions must be sorted and unique")
    if encode(certificate["dependencies"]) != encode(table["scope"]["dependencies"]):
        raise Rejected("Certificate dependency hashes differ from the executable scope")
    if certificate["table_digest"] != digest(encode(table)):
        raise Rejected("Certificate table differs from the current executable model")
    indices = {encode(state): i for i, state in enumerate(table["states"])}
    initial = indices.get(encode(certificate["initial_state"]))
    if initial is None:
        raise InvalidIR("Initial state is outside the certificate carrier")
    states = certificate["invariant_states"]
    if not isinstance(states, list) or len(states) > MAX_STATES:
        raise InvalidIR("invariant_states must be a bounded array")
    invariant = set()
    for state in states:
        budget.tick()
        i = indices.get(encode(state))
        if i is None:
            raise InvalidIR("Invariant contains an invalid state")
        if i in invariant:
            raise InvalidIR("Invariant contains duplicate states")
        invariant.add(i)
    if initial not in invariant:
        raise Rejected("Invariant does not contain the initial state")
    for goal in table["goals"]:
        budget.tick()
        if goal in invariant:
            raise Rejected("Invariant includes a goal state", state=table["states"][goal])
    for edge in table["edges"]:
        budget.tick()
        if edge["source"] in invariant and edge["target"] not in invariant:
            raise Rejected("Invariant is not preserved by every legal action", edge=edge)
    return table, initial, sorted(invariant)


def verify_certificate(model, source, *, backend="finite", lean=None, budget=None):
    """Verify locally; a rejected/exhausted certificate supplies no guarantee.

    `lean` is a trusted local LeanBackend configuration, never certificate data.
    Finite verification remains available without installing Lean.
    """
    budget = budget if budget is not None else Budget()
    try:
        if backend not in ("finite", "lean"):
            raise UnsupportedFeature("Unknown certificate backend", backend=backend)
        certificate = thaw(read_json(source))
        table, initial, invariant = _premises(model, certificate, budget)
        checker = {"identity": "adm-invariant-finite/0.1", "guarantee": "exhaustive_finite"}
        if backend == "lean":
            if lean is None:
                raise UnsupportedFeature("Lean backend is not configured on this local worker")
            checker = lean.check(table, initial, invariant, budget=budget)
        budget.tick()
        result = {
            "status": "verified",
            "verdict": "unreachable",
            "guarantee": checker["guarantee"],
            "theory_version": model.version,
            "certificate_digest": digest(encode(certificate)),
            "dependencies": certificate["dependencies"],
            "checker": checker,
            "correspondence": {
                "checker": CORRESPONDENCE,
                "guarantee": "exhaustive_finite",
                "table_digest": digest(encode(table)),
                "states": len(table["states"]),
                "legal_actions": len(table["edges"]),
            },
            "scope": {
                "module": certificate["module"],
                "goal": certificate["goal"],
                "selection": selection(certificate["transitions"]),
                "transitions": certificate["transitions"],
                "initial_state": certificate["initial_state"],
                "path_length": "any_nonnegative_integer",
                "action_scope": "Only the listed transitions and all of their finite parameter values.",
                "interpretation": "Exact accepted definitions; empirical fidelity is not established.",
            },
            "work": budget.used,
        }
        return bind_result(
            model.version,
            {"op": "check_certificate", "certificate": certificate, "backend": backend},
            result,
            [
                claim("unreachable", checker["guarantee"]),
                claim("executable_correspondence", "exhaustive_finite"),
            ],
        )
    except Interrupted:
        raise
    except ResourceLimit as error:
        status, failure = "inconclusive", error.as_dict()
    except UnsupportedFeature as error:
        status, failure = "unavailable", error.as_dict()
    except ADMError as error:
        status, failure = "rejected", error.as_dict()
    return {"status": status, "guarantee": None, "error": failure, "work": budget.used}
