"""Additive result identity; never part of the legacy certificate table encoding."""

from .artifacts import digest
from .data import encode, thaw

PROFILE = "adm-result/0.1"


def selection(transitions):
    return (
        {"kind": "module_all"}
        if transitions is None
        else {"kind": "explicit", "transitions": sorted(transitions)}
    )


def semantic_query(query):
    """Keep mathematical scope separate from request identity and resource limits."""
    query = thaw(query)
    if query["op"] == "find_plan":
        query["selection"] = selection(query.pop("transitions", None))
        query.setdefault("max_depth", None)
        query["objective"] = "shortest_action_count"
    elif query["op"] == "check_certificate":
        query["certificate_digest"] = digest(encode(query.pop("certificate")))
    return query


def bind_result(version, query, result, claims=()):
    binding = {
        "profile": PROFILE,
        "theory_version": version,
        "query": semantic_query(query),
        "resolved_scope": thaw(result.get("scope")),
    }
    result["binding"] = {**binding, "digest": digest(encode(binding))}
    result["assurance"] = {"claims": list(claims), "empirical_fidelity": "not_established"}
    return result


def claim(name, method):
    return {"claim": name, "status": "established", "method": method}
