"""Offline finite-engine example: local planning, certificates, receipt policy and cloning."""

import json
from pathlib import Path

from awm_adm.engine import Budget, Instance, build_candidate, build_certificate
from awm_adm.engine.lean_backend import LeanBackend


def main():
    root = Path(__file__).resolve().parents[1]
    model = (root / "tests/fixtures/v1/models/tanks.json").read_bytes()
    instance = Instance(model, mode="forward")
    query = {
        "op": "find_plan",
        "module": "tanks",
        "initial_state": {"left": 0, "right": 0},
        "goal": "tanks.four_litres",
    }
    result = instance.query(query)
    assert result["steps"] == 6 and result["witness_replayed"]
    clone = Instance.restore(instance.export_snapshot())
    assert clone.instance_id != instance.instance_id
    assert clone.query(query)["steps"] == 6
    certificate = build_certificate(
        instance.model,
        "tanks",
        query["initial_state"],
        query["goal"],
        transitions=["tanks.empty_left", "tanks.empty_right", "tanks.fill_left", "tanks.fill_right"],
    )
    finite = instance.query({"op": "check_certificate", "certificate": certificate, "backend": "finite"})
    assert finite["certificate_status"] == "verified"
    lean = LeanBackend.from_env()
    formal = {"status": "not_run", "reason": "AWM_ADM_LEAN is not configured"}
    if lean:
        formal = instance.query(
            {"op": "check_certificate", "certificate": certificate, "backend": "lean"},
            lean=lean,
            limits={"max_duration_ms": 30_000},
        )
        assert formal["certificate_status"] == "verified", formal
        formal = {
            "status": "verified",
            "proof": formal["checker"]["guarantee"],
            "correspondence": formal["correspondence"]["guarantee"],
        }
    empty = Instance(mode="forward")
    base = empty.model
    source = {
        "artifact_kind": "evidence",
        "evidence_kind": "synthetic_fixture",
        "origin": "finite-engine example",
        "scope": "Authored fixture; no live acquisition",
        "content": {"kind": "example"},
    }
    for capacity in (10, 12):
        package = build_candidate(
            base,
            {
                "example.capacity": {
                    "kind": "function",
                    "params": {},
                    "returns": {"kind": "int", "min": 0, "max": 100},
                    "body": {"op": "literal", "value": capacity},
                }
            },
            candidate_id=f"capacity-{capacity}",
            evidence=[source],
        )
        empty.receive(package)
    assert empty.decide_next()["status"] == "awaiting_review"
    for capacity in (10, 12):
        empty.review(f"capacity-{capacity}", approve=True, expected_context=empty.context())
        assert empty.decide_next(budget=Budget())["status"] == "accepted"
    assert empty.model.call("example.capacity", {})["value"] == 12
    print(
        json.dumps(
            {
                "status": "passed",
                "plan_steps": result["steps"],
                "clone_independent": True,
                "finite_certificate": finite["certificate_status"],
                "formal": formal,
                "receipt_sequences": [empty.candidate(f"capacity-{n}")["receipt_sequence"] for n in (10, 12)],
                "forward_capacity": 12,
                "provider_calls": 0,
                "durable_service": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
