import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from awm_adm.interaction.models import DirectMessage, EnableConnection


def test_authored_intent_corpus_uses_minimal_inputs_and_independent_expected_meanings():
    corpus = json.loads(
        (Path(__file__).resolve().parents[1] / "contracts/interaction-corpus.json").read_text()
    )
    cases = {case["id"]: case for case in corpus["cases"]}
    assert len(cases) == len(corpus["cases"])
    for case in cases.values():
        DirectMessage.model_validate(case["input"])
    assert cases["ambiguous-rule"]["expected"]["publication"] is False
    assert cases["wrong-well-typed-interpretation"]["expected"]["borrowed"] == 2
    assert cases["unknown-year"]["expected"]["value"] is None


def test_direct_input_needs_no_conversation_context_or_financial_setup():
    request = DirectMessage(text="Can I borrow another camera kit?")
    assert request.reply_to is None and request.idempotency_key is None
    assert DirectMessage(attachments=["history-md"]).text == ""
    assert DirectMessage(text="For 2026", reply_to="original-question").reply_to == "original-question"


@pytest.mark.parametrize("field", ["allowance_id", "price_id", "context", "approve", "mode"])
def test_message_cannot_smuggle_configuration_or_approval(field):
    with pytest.raises(ValidationError):
        DirectMessage.model_validate({"text": "Learn this rule", field: "untrusted"})


def test_empty_and_duplicate_material_are_rejected():
    for body in ({"text": "  "}, {"attachments": ["one", "one"]}):
        with pytest.raises(ValidationError):
            DirectMessage.model_validate(body)


def test_connection_has_no_model_price_allowlist_or_purpose_permissions():
    request = EnableConnection(idempotency_key="enable-once", provider="openai", model="configured-model")
    assert request.sealed_credential is None  # Reuse is checked against the selected provider by service.
    for extras in ({"purposes": ["acquisition"]}, {"api_key": "not-a-real-key"}, {"price_id": "price"}):
        with pytest.raises(ValidationError):
            EnableConnection.model_validate({**request.model_dump(), **extras})


def test_encrypted_key_requires_its_identity():
    with pytest.raises(ValidationError):
        EnableConnection(
            idempotency_key="enable-once",
            provider="anthropic",
            model="configured-model",
            sealed_credential="sealed",
        )
