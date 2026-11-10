"""Breadth-first search over a model's finite legal transition graph."""

import json
from collections import deque
from dataclasses import dataclass

from .budget import Budget
from .data import encode, read_json, thaw
from .errors import InvalidIR, ResourceLimit
from .results import bind_result, claim


@dataclass(frozen=True)
class Node:
    parent: bytes | None
    action: bytes | None
    depth: int


def find_plan(
    model,
    module,
    initial_state,
    goal,
    *,
    transitions=None,
    max_depth=None,
    max_states=10_000,
    max_search_bytes=16_000_000,
    budget=None,
):
    budget = budget if budget is not None else Budget()
    for label, value in (("max_states", max_states), ("max_search_bytes", max_search_bytes)):
        if type(value) is not int or value < 1:
            raise InvalidIR(f"{label} must be a positive integer")
    if max_depth is not None and (type(max_depth) is not int or max_depth < 0):
        raise InvalidIR("max_depth must be a nonnegative integer")
    scope = {
        "module": module,
        "goal": goal,
        "max_depth": max_depth,
        "objective": "shortest_action_count",
        "action_scope": "Only the listed transitions and their finite parameter values are allowed.",
    }
    dependencies = {}
    visited, frontier = {}, deque()
    stats = {"states_discovered": 0, "states_expanded": 0, "retained_search_bytes": 0}

    def result(outcome, guarantee, **details):
        claims = []
        if outcome == "found":
            claims = [
                claim("plan_valid", "deterministic_replay"),
                claim("shortest_action_count", "exhaustive_breadth_first_search"),
            ]
        elif outcome in ("unreachable", "no_plan_within_depth"):
            claims = [claim(outcome, "exhaustive_breadth_first_search")]
        value = {
            "outcome": outcome,
            "theory_version": model.version,
            "guarantee": guarantee,
            "scope": scope,
            "dependencies": dependencies,
            "statistics": dict(stats),
            "work": budget.used,
            **details,
        }
        query = {
            "op": "find_plan",
            "module": module,
            "goal": goal,
            "initial_state": thaw(initial_state),
            "max_depth": max_depth,
        }
        if transitions is not None:
            query["transitions"] = list(transitions)
        return bind_result(model.version, query, value, claims)

    def add(state, parent, action, depth):
        budget.tick()
        key = encode(state)
        if key in visited:
            return
        edge = encode(action) if action is not None else None
        retained = stats["retained_search_bytes"] + len(key) + (len(edge) if edge else 0)
        if len(visited) >= max_states or retained > max_search_bytes:
            raise ResourceLimit(
                "Planner retention limit reached", max_states=max_states, max_search_bytes=max_search_bytes
            )
        visited[key] = Node(parent, edge, depth)
        frontier.append(key)
        stats["states_discovered"] += 1
        stats["retained_search_bytes"] = retained

    try:
        checked_scope = model.planning_scope(module, goal, transitions, budget=budget)
        dependencies = checked_scope.pop("dependencies")
        scope.update(checked_scope)
        initial = thaw(read_json(initial_state, encoded=False))
        # Validate state even when retention limits prevent starting the search.
        model.goal(goal, initial, budget=budget)
        add(initial, None, None, 0)
        bounded_frontier = False
        while frontier:
            budget.tick()
            key = frontier.popleft()
            node, state = visited[key], json.loads(key)
            if model.goal(goal, state, budget=budget)["value"]:
                path = []
                cursor = key
                while visited[cursor].parent is not None:
                    budget.tick()
                    path.append((json.loads(visited[cursor].action), cursor))
                    cursor = visited[cursor].parent
                path.reverse()
                replayed = initial
                steps = []
                for action, expected in path:
                    replayed = model.step(
                        action["transition"], replayed, action["parameters"], budget=budget
                    )["value"]
                    if encode(replayed) != expected:
                        raise RuntimeError("Planner witness failed deterministic replay")
                    steps.append(action)
                if not model.goal(goal, replayed, budget=budget)["value"]:
                    raise RuntimeError("Planner witness does not reach the goal")
                return result(
                    "found",
                    "exhaustive_finite",
                    plan=steps,
                    initial_state=initial,
                    final_state=replayed,
                    steps=len(steps),
                    shortest_action_count=True,
                    witness_replayed=True,
                )
            if max_depth is not None and node.depth >= max_depth:
                bounded_frontier = True
                continue
            stats["states_expanded"] += 1
            for action, successor in model.successors(scope["transitions"], state, budget=budget):
                add(successor, key, action, node.depth + 1)
        outcome = "no_plan_within_depth" if bounded_frontier else "unreachable"
        return result(
            outcome, "exhaustive_finite", initial_state=initial, complete_reachable_graph=not bounded_frontier
        )
    except ResourceLimit as error:
        return result("inconclusive", None, error=error.as_dict())
