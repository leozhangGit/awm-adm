import json
from pathlib import Path

from awm_adm.contracts import IntentDraft

ROOT = Path(__file__).resolve().parents[1]


def test_language_acceptance_spec_has_valid_ready_and_unready_contracts():
    corpus = json.loads((ROOT / "contracts/language-corpus.json").read_text())
    cases = corpus["cases"]
    assert len({case["id"] for case in cases}) == len(cases)
    context = {"adm_id": "fixture-adm", "theory_root": "sha256:" + "0" * 64, "policy_epoch": 0}
    for case in cases:
        draft = IntentDraft(
            interpretation_id=case["id"],
            context=context,
            catalog_digest="sha256:" + "0" * 64,
            utterance=case["utterance"],
            translator="local",
            status=case["expected_status"],
            query=case["expected_query"],
            clarification=case["reason"],
        )
        assert (draft.query is not None) == (case["expected_status"] == "ready")
    # Ground-truth conformance only. No parser/accuracy claim is made here.
    expected = {case["id"]: case["expected_query"] for case in cases}
    assert expected["plan-all"]["transitions"] is None
    assert expected["plan-empty"]["transitions"] == []
