"""Preparation rejects invented authority and unsupported meaning before acquisition."""

import pytest

from .interaction_support import material, plan
from .test_application import app_runtime as app_runtime
from .test_direct_teach import preparation, task
from .test_learning_service import rig as rig


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(authorize=True),
        lambda p: p["children"][0]["interfaces"]["math.double"].update(body={"lit": 3}),
        lambda p: p["children"][0]["interfaces"]["math.double"]["params"].update(n={"ref": "foreign.Type"}),
        lambda p: p["children"][0]["interfaces"]["math.double"]["params"].update(
            n={"kind": "int", "min": 0, "max": 1000000}
        ),
        lambda p: p["children"][0].update(input_ids=["invented"]),
        lambda p: p.update(vocabulary={"aliases": {"bad": ["unknown.symbol"]}}),
    ],
)
def test_invalid_proposal_cannot_reach_review(rig, mutation):
    rt, gw = rig
    key, uid = preparation(rt, gw, mutate=mutation)
    assert task(rt, key, uid)["status"] == "failed"
    assert not rt.store.page(key, "requests")["items"]


@pytest.mark.parametrize(
    "change", ["disclosure", "unbounded", "observation_rule", "unknown_requirements", "body_authority"]
)
def test_material_cannot_authorize_or_widen_scope(rig, change):
    rt, gw = rig

    def bad(p):
        p["kind"] = "facts"
        p["children"][0].update(kind="facts", interfaces={}, material=material())
        m = p["children"][0]["material"]
        if change == "disclosure":
            m["sources"][0]["allow_external"] = True
        elif change == "unbounded":
            m["projection"]["cells"][0]["effective_to"] = None
        elif change == "observation_rule":
            p["children"][0]["interfaces"] = plan(["unused"])["children"][0]["interfaces"]
        elif change == "body_authority":
            m["authorize"] = True
        else:
            p["requirements"] = {
                "profile": "adm-conformance/0.1",
                "contracts": [
                    {
                        "contract_id": "invented",
                        "origin": "provider",
                        "required_symbols": ["missing.symbol"],
                        "checks": [
                            {
                                "id": "header",
                                "kind": "interface",
                                "symbol": "missing.symbol",
                                "expected": {"kind": "function"},
                            }
                        ],
                    }
                ],
            }

    key, uid = preparation(rt, gw, mutate=bad)
    assert task(rt, key, uid)["status"] == "failed"
