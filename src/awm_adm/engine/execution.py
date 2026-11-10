"""Local query execution over an already checked, pinned model; no learning I/O."""

from .budget import Budget
from .certificates import verify_certificate
from .data import thaw
from .errors import ADMError, Interrupted, KnowledgeGap, ResourceLimit, UnsupportedFeature
from .planning import find_plan
from .requests import validate_request
from .results import bind_result, claim


def normalize_query(query, limits):
    query = thaw(query)
    # The query envelope represents omitted optional selection/depth by null; the core grammar
    # uses absence. Explicit [] must survive this conversion.
    if isinstance(query, dict) and query.get("op") == "find_plan":
        for field in ("transitions", "max_depth"):
            if query.get(field) is None:
                query.pop(field, None)
    return validate_request(
        {
            "protocol": "adm/0.1",
            "kind": "request",
            "profile": "finite-v0",
            "idempotency_key": "local-library-query",
            "query": query,
            "limits": limits,
            "on_gap": "report",
        }
    )["query"]


def execute(model, query, limits, *, budget=None, lean=None, explain=None):
    budget = budget if budget is not None else Budget(limits["max_work"], limits["max_duration_ms"] / 1000)
    query = normalize_query(query, limits)
    status = "succeeded"
    try:
        budget.tick()
        op = query["op"]
        if op == "capabilities":
            result = {
                "value": model.capabilities(budget=budget),
                "work": budget.used,
                "guarantee": "computed",
                "dependencies": model.index,
            }
        elif op in ("evaluate", "check_claim"):
            expression = query["expression"] if op == "evaluate" else query["proposition"]
            result = (
                model.evaluate(expression, budget=budget)
                if op == "evaluate"
                else model.check_claim(expression, budget=budget)
            )
            result.update(
                dependencies=model.expression_dependencies(expression),
                scope={"module": query["module"], "interpretation": "Closed accepted finite definitions."},
            )
        elif op == "find_plan":
            result = find_plan(
                model,
                query["module"],
                query["initial_state"],
                query["goal"],
                transitions=query.get("transitions"),
                max_depth=query.get("max_depth"),
                max_states=limits["max_states"],
                max_search_bytes=limits["max_search_bytes"],
                budget=budget,
            )
            if result["outcome"] == "inconclusive":
                status = "inconclusive"
        elif op == "check_certificate":
            result = verify_certificate(
                model, query["certificate"], backend=query["backend"], lean=lean, budget=budget
            )
            checked = result.pop("status")
            result["certificate_status"] = checked
            status = {
                "verified": "succeeded",
                "rejected": "needs_input",
                "unavailable": "needs_input",
                "inconclusive": "inconclusive",
            }[checked]
        else:
            if explain is None:
                raise UnsupportedFeature("Result history is not configured")
            result = {
                "explanation": explain(query["result_id"]),
                "guarantee": "computed",
                "work": budget.used,
            }
    except Interrupted:
        raise
    except ResourceLimit as error:
        status, result = "inconclusive", {"error": error.as_dict(), "guarantee": None, "work": budget.used}
    except (KnowledgeGap, UnsupportedFeature) as error:
        status, result = "needs_input", {"error": error.as_dict(), "guarantee": None, "work": budget.used}
    except ADMError as error:
        status, result = "needs_input", {"error": error.as_dict(), "guarantee": None, "work": budget.used}
    if "binding" not in result:
        claims = (
            [claim("computed_value", "local_interpreter")]
            if status == "succeeded" and query["op"] in ("evaluate", "check_claim")
            else []
        )
        bind_result(model.version, query, result, claims)
    return {"status": status, **result}
