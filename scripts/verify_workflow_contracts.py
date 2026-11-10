"""Offline workflow contract oracle. Does not implement HTTP, authorization or workers."""

import argparse
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, validators

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts/workflows"
StrictValidator = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine("integer", lambda _, value: type(value) is int),
)


def load(name):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    return json.loads((CONTRACTS / name).read_text(), object_pairs_hook=unique)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(name, value):
    schema = load("resources.schema.json")
    StrictValidator(
        {"$defs": schema["$defs"], "$ref": "#/$defs/" + name}, format_checker=FormatChecker()
    ).validate(value)
    if name in ("MessageInput", "Turn"):
        require(bool(value["text"].strip() or value["attachment_ids"]), "Empty message")
        require(len(value["text"].encode("utf-8")) <= 65536, "Message byte limit")
    elif name == "TaskSpec":
        require(
            value["publication"] != "checked_auto" or value["requirements_digest"] is not None,
            "Automatic admission needs independently installed requirements",
        )
    elif name == "TaskRecord":
        if value["status"] == "succeeded":
            require(not value["unresolved_ids"] and value["stop_reason"] is None, "Incomplete success")
        if value["status"] == "partially_succeeded":
            require(bool(value["accepted_ids"] and value["unresolved_ids"]), "Partial needs both outcomes")
    elif name == "TaskStep":
        require(load("authority.json")["purpose_lanes"][value["purpose"]] == value["lane"], "Wrong lane")
        if value["status"] not in ("prepared", "cancelled"):
            require(value["reservation_id"] is not None, "Unreserved work")
        if value["status"] == "unknown":
            require(value["outcome_digest"] is None, "Unknown cannot invent an outcome")
    elif name == "PriceRecord":
        require(value["valid_until_ms"] > value["valid_from_ms"], "Invalid price interval")
        require(
            value["bound_method"] != "synthetic" or value["provider"] == "recorded", "Synthetic live bound"
        )
        require(value["bound_method"] == "unpriced" or value["bound_evidence"] is not None, "Missing bound")
    elif name == "Allowance":
        amounts = (value["cap_micro_usd"], value["settled_micro_usd"], value["reserved_micro_usd"])
        if value["status"] == "unpriced_legacy":
            require(value["price_id"] is None and all(v is None for v in amounts), "Unknown dollars are null")
            require(bool(value["legacy_grant_ids"]), "Legacy hold needs original grant references")
        else:
            require(all(type(v) is int for v in amounts), "Priced allowance needs exact amounts")
        if value["status"] == "active":
            require(value["price_id"] is not None, "Active unpriced allowance")
            require(
                value["settled_micro_usd"] + value["reserved_micro_usd"] <= value["cap_micro_usd"],
                "Active allowance over cap",
            )
    elif name == "DeletionOperation":
        require((value["status"] == "blocked") == (value["resume_stage"] is not None), "Missing resume stage")
        require(value["content_purged"] == (value["status"] == "deleted"), "False deletion completion")
    return value


def decision_allowed(decision, proposal, *, actor, context, now_ms):
    validate("DecisionInput", decision)
    validate("Proposal", proposal)
    require(actor == "owner", "Only authenticated owner can decide")
    require(decision["proposal_id"] == proposal["id"], "Wrong proposal")
    require(decision["proposal_digest"] == proposal["payload_digest"], "Changed proposal")
    require(decision["context"] == proposal["context"] == context, "Stale or cross-ADM decision")
    require(now_ms < proposal["expires_at_ms"], "Expired decision")
    return decision["answer"] == "accept"


def reserve_micro(price, input_bound, output_cap, *, now_ms):
    validate("PriceRecord", price)
    require(type(input_bound) is int and input_bound >= 0, "Invalid input bound")
    require(type(output_cap) is int and output_cap >= 0, "Invalid output bound")
    require(price["bound_method"] != "unpriced", "Cannot reserve unknown price")
    require(price["valid_from_ms"] <= now_ms < price["valid_until_ms"], "Price not currently valid")
    return sum(
        (tokens * rate + 999_999) // 1_000_000
        for tokens, rate in (
            (input_bound, price["input_micro_per_million"]),
            (output_cap, price["output_micro_per_million"]),
        )
    )


def can_reserve(allowance, amount, lane, price_id, *, now_ms=0):
    validate("Allowance", allowance)
    require(type(amount) is int and amount >= 0, "Invalid reservation")
    return (
        allowance["status"] == "active"
        and now_ms < allowance["expires_at_ms"]
        and allowance["lane"] == lane
        and allowance["price_id"] == price_id
        and allowance["settled_micro_usd"] + allowance["reserved_micro_usd"] + amount
        <= allowance["cap_micro_usd"]
    )


def transition(kind, state, event, guards=None):
    guards = guards or {}
    table = load("lifecycle.json")
    if kind == "deletion" and state == "blocked" and event == "resume":
        stage = guards.get("resume_stage")
        require(stage in table["deletion_resume_stages"], "Invalid deletion recovery")
        return stage
    require(event in table[kind].get(state, {}), "Forbidden lifecycle transition")
    if (kind == "task" and event in ("authorize", "accept", "resume")) or (
        kind == "step" and event == "admit"
    ):
        require(guards.get("authorized") and guards.get("current"), "Missing current authority")
    if kind == "task":
        if event == "resume":
            require(not guards.get("unknown_dispatch"), "Unknown dispatch cannot resume")
        if event == "complete":
            require(guards.get("all_done") and not guards.get("unresolved"), "Premature completion")
        if event == "partial":
            require(guards.get("accepted") and guards.get("unresolved"), "Invalid partial completion")
    if kind == "step":
        if event == "admit":
            require(guards.get("parent_running") and not guards.get("deleted"), "Publication fenced")
        if event == "release_unissued":
            require(guards.get("proved_unissued"), "Cannot refund uncertain call")
        if event == "settle":
            require(guards.get("outcome_identified"), "Late settlement must identify original outcome")
    if kind == "deletion" and event == "finish":
        require(guards.get("inventory_purged"), "Delete inventory incomplete")
    return table[kind][state][event]


def check_presentation(packet, proposed):
    """Check independently supplied structured claims, never certify free prose."""
    require(
        set(proposed) == {"subject_id", "outcome_digest", "value", "claims", "support_ids"}, "Extra fields"
    )
    for key in ("subject_id", "outcome_digest", "value"):
        require(json.dumps(packet[key], sort_keys=True) == json.dumps(proposed[key], sort_keys=True), key)
    require(set(proposed["claims"]) <= set(packet["allowed_claims"]), "Unsupported assurance")
    require(set(proposed["support_ids"]) <= set(packet["support_ids"]), "Invented support")


def verify_contracts():
    schema = load("resources.schema.json")
    Draft202012Validator.check_schema(schema)
    require(
        all(value.get("additionalProperties") is False for value in schema["$defs"].values()), "Open record"
    )
    examples = load("examples.json")
    for name, value in examples.items():
        validate(name, value)
    defaults = load("defaults.json")
    for name, value in defaults.items():
        if isinstance(value, dict) and set(value) == {"default", "hard"}:
            require(0 < value["default"] <= value["hard"], "Invalid bound: " + name)
    require(
        defaults["paid_enabled"] is False and defaults["default_allowance_micro_usd"] is None,
        "Implicit spend",
    )
    require(
        defaults["interaction_reserved_slots"] + defaults["background_provider_slots"]
        <= defaults["provider_slots"],
        "No interactive reserve",
    )
    require(defaults["attachment_bytes"]["hard"] <= defaults["http_body_bytes"], "Oversized attachment")
    require(defaults["completion_reserved_calls"] < defaults["task_calls"]["default"], "No work allowance")
    require(defaults["completion_output_tokens"] <= defaults["call_output_tokens"]["default"], "Summary cap")
    require(defaults["provider_slots_per_adm"] >= 2, "A shared per-ADM slot can starve interaction")
    for scope, lanes in defaults["quota_lanes"].items():
        for dimension, total in defaults["quota_totals"][scope].items():
            require(sum(v[dimension] for v in lanes.values()) == total, "Quota partition mismatch")
            require(all(v[dimension] > 0 for v in lanes.values()), "No protected lane quota")
    for lane, limits in defaults["quota_lanes"]["per_adm"].items():
        for dimension, value in limits.items():
            require(value <= defaults["quota_lanes"]["installation"][lane][dimension], "Non-nested quota")
    for trace in load("traces.json"):
        state = trace["start"]
        for event in trace["events"]:
            state = transition(trace["kind"], state, event, trace["guards"])
        require(state == trace["end"], "Trace outcome mismatch")
    authority = load("authority.json")
    for operations in authority["allow"].values():
        require(set(operations) <= set(authority["operations"]), "Unknown authority")
    require(not authority["allow"]["assistant"] and not authority["allow"]["source"], "Untrusted authority")
    for entry in load("fixtures/manifest.json")["fixtures"]:
        for name, digest in entry["files"].items():
            require(hashlib.sha256((CONTRACTS / name).read_bytes()).hexdigest() == digest, "Fixture drift")
    price = examples["PriceRecord"]
    require(reserve_micro(price, 32000, 8192, now_ms=1) == 96768, "Price arithmetic")
    require(reserve_micro(price, 1000, 200, now_ms=1) == 2800, "Settlement arithmetic")
    return {"schemas": len(schema["$defs"]), "examples": len(examples), "traces": len(load("traces.json"))}


def verify_engine_fixtures():
    from awm_adm.engine import Instance, build_candidate
    from awm_adm.engine.errors import Rejected

    results = {}
    for name in ("equipment", "access"):
        model = load(f"fixtures/{name}/model.json")
        policy = load(f"fixtures/{name}/owner-requirements.json")
        expected = load(f"fixtures/{name}/expected.json")
        instance = Instance(policy=policy)
        require(instance.query(expected["ask"]["expected_query"])["status"] == "needs_input", "Empty answer")
        evidence = [
            {
                "artifact_kind": "evidence",
                "evidence_kind": "synthetic_fixture",
                "origin": "Authored contract model",
                "scope": "Offline fixture only",
                "content": {"basis": "Authored definitions; no provider acquisition"},
            }
        ]
        candidate = build_candidate(
            instance.model, model["declarations"], candidate_id=name, evidence=evidence
        )
        instance.receive(candidate, review_required=False)
        require(instance.decide_next()["status"] == "accepted", "Valid fixture rejected")
        for case in expected["cases"]:
            value = instance.query(case["query"])
            require(value["status"] == "succeeded" and value["value"] is case["expected"], "Oracle mismatch")
        clone = Instance.restore(instance.export_snapshot())
        require(clone.instance_id != instance.instance_id, "Snapshot identity reused")
        result = clone.query(expected["ask"]["expected_query"])
        require(result["value"] is expected["ask"]["expected_value"], "Snapshot outcome mismatch")
        wrong = json.loads(json.dumps(model))
        wrong["declarations"][expected["symbol"]]["body"] = {"op": "literal", "value": True}
        rejected = False
        try:
            Instance(wrong, policy=policy)
        except Rejected:
            rejected = True
        require(rejected, "Independent policy failed to reject incorrect definition")
        results[name] = {
            "truth_cases": len(expected["cases"]),
            "empty_gap": True,
            "local_admission": True,
            "snapshot_recheck": True,
            "incorrect_definition_rejected": True,
        }
    return results


def verify_source_oracles():
    from awm_adm.sources.models import ExtractionOutput, PolicyInput

    expected = load("fixtures/equipment/expected-extraction.json")
    ExtractionOutput.model_validate(expected)
    policy = load("fixtures/equipment/source-policy.json")
    PolicyInput.model_validate({"expected_revision": "fixture-revision", "expected_generation": 0, **policy})
    raw = (CONTRACTS / "fixtures/equipment/supplied.md").read_bytes()
    for claim, year, value in zip(expected["claims"], (2025, 2026), (2, 1), strict=True):
        passage = raw[claim["start_byte"] : claim["end_byte"]].decode("utf-8")
        require(str(year) in passage and str(value) in passage, "Expected source span mismatch")
        require(claim["value"] == {"kind": "integer", "value": value}, "Wrong historical value")
        require(claim["temporal_scope"]["effective_from"] == f"{year}-01-01T00:00:00Z", "Wrong time")
    require(
        load("fixtures/access/expected.json")["source_expectation"]["kind"] == "capability_task",
        "Rule material is not an automatically projected historical fact",
    )
    return {"authored_claims_validated": 2, "span_checks": 2, "extraction_performed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {
        "status": "passed",
        "scope": "Offline contract oracle and finite engine",
        "contracts": verify_contracts(),
        "engine": verify_engine_fixtures(),
        "sources": verify_source_oracles(),
        "v3_runtime_exercised": False,
        "provider_calls": 0,
    }
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
