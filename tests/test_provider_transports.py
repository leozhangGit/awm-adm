"""Simulated official wire formats; no provider account or live-call claim."""

import copy
import json

import pytest

from awm_adm.providers.transport import acquire, interpret
from awm_adm.providers.wire import make_wire, specification
from awm_adm.runtime.protocol import RuntimeFault

from .test_construction_core import contract


def response(provider, **kw):
    if provider == "openai":
        value = {
            "id": "response-1",
            "model": "configured-model",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": '{"ok":true}'}],
                }
            ],
        }
    else:
        value = {
            "id": "message-1",
            "model": "configured-model",
            "type": "message",
            "role": "assistant",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": '{"ok":true}'}],
        }
    return {**value, "usage": {"input_tokens": 11, "output_tokens": 4}, **kw}


def raw(value):
    return json.dumps(value).encode()


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_adapter_success_refusal_incomplete_invalid_usage_and_credential_redaction(provider):
    value = response(provider)
    result = interpret(provider, raw(value))
    assert result["status"] == "succeeded" and result["usage"] == {"input_tokens": 11, "output_tokens": 4}
    incomplete = response(
        provider, **({"status": "incomplete"} if provider == "openai" else {"stop_reason": "max_tokens"})
    )
    assert interpret(provider, raw(incomplete))["error"] == "output_incomplete"
    refusal = response(provider)
    if provider == "openai":
        refusal["output"][0]["content"] = [{"type": "refusal", "refusal": "no"}]
    else:
        refusal["stop_reason"] = "refusal"
    assert interpret(provider, raw(refusal))["error"] == "refusal"
    bad = response(provider, usage={"input_tokens": True, "output_tokens": 4})
    assert interpret(provider, raw(bad))["usage"] is None
    assert interpret(provider, b'{"id":1,"id":2}')["status"] == "failed"
    assert interpret(provider, b'{"partial":')["text"] is None
    secret = "secret-test-key"
    for level in (0, 1, 2):
        reflected = response(provider)
        encoded = secret if level == 0 else "".join("\\u%04x" % ord(c) for c in secret)
        text = json.dumps({"key": secret}) if level == 0 else '{"key":"' + encoded + '"}'
        parts = reflected["output"][0]["content"] if provider == "openai" else reflected["content"]
        parts[0]["text"] = text
        payload = raw(reflected)
        if level == 2:
            payload = payload.replace(b"secret-test-key", encoded.encode())
        result = interpret(provider, payload, credential=secret)
        assert result["status"] == "failed" and secret not in json.dumps(result)


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize(
    "status,code",
    [
        (429, "rate_limited"),
        (401, "authentication_failed"),
        (400, "unsupported_or_invalid_request"),
        (500, "provider_error"),
        (302, "provider_error"),
    ],
)
def test_http_errors_are_single_dispatch_no_body_echo_or_retry(provider, status, code):
    calls = []

    def fake(*args):
        calls.append(args)
        return status, b"credential-bearing-error"

    result = acquire({"provider": provider}, b"{}", "secret", 1, transport=fake)
    assert result["error"] == code and result["usage"] is None and len(calls) == 1
    assert "credential" not in json.dumps(result)


def test_transport_exception_never_echoed_or_retried():
    count = []

    def fake(*args):
        count.append(1)
        raise TimeoutError("Authorization: secret")

    result = acquire({"provider": "openai"}, b"{}", "secret", 1, transport=fake)
    assert result["status"] == "outcome_unknown" and len(count) == 1 and "secret" not in json.dumps(result)


def test_model_neutral_guidance_and_authored_schema_order_across_transports():
    spec = specification({"task": {"acquisition_contract": contract()}, "feedback": []})
    schema_before = json.dumps(spec["schema"], separators=(",", ":"))
    wires = []
    for provider in ("openai", "anthropic"):
        for model in ("configured-a", "configured-b"):
            body, estimate = make_wire(
                {"provider": provider, "model": model, "capabilities": ["json_schema", "recursive_refs"]},
                spec,
                100,
            )
            value = json.loads(body)
            schema = (
                value["text"]["format"]["schema"]
                if provider == "openai"
                else value["output_config"]["format"]["schema"]
            )
            assert json.dumps(schema, separators=(",", ":")) == schema_before
            assert value.get("instructions", value.get("system")) == spec["instructions"]
            assert estimate == len(body) + 4096
            wires.append(value)
    a, b = copy.deepcopy(wires[:2])
    a.pop("model")
    b.pop("model")
    assert a == b
    with pytest.raises(RuntimeFault, match="capabilities"):
        make_wire({"provider": "openai", "model": "configured", "capabilities": ["json_schema"]}, spec, 100)


def test_gateway_child_timeout_bounds_whole_call_without_exposing_key(monkeypatch):
    import subprocess

    from awm_adm.gateway import call

    observed = {}

    class Process:
        pid = 12345
        returncode = None

        def communicate(self, body, timeout):
            observed["body"] = json.loads(body)
            observed["timeout"] = timeout
            raise subprocess.TimeoutExpired("provider-child", timeout)

        def wait(self):
            observed["waited"] = True

    def start(argv, **kw):
        observed["argv"] = argv
        observed["environment"] = kw["env"]
        return Process()

    monkeypatch.setattr(call.subprocess, "Popen", start)
    monkeypatch.setattr(call.os, "killpg", lambda pid, sig: observed.update(killed=pid))
    result = call.bounded_acquire({"provider": "openai"}, b"{}", "authored-key", 0.2)
    assert result["status"] == "outcome_unknown"
    assert observed["killed"] == 12345 and observed["waited"]
    assert 0 < observed["timeout"] <= 0.2
    assert "authored-key" not in json.dumps({k: v for k, v in observed.items() if k != "body"})
    assert observed["body"]["credential"] == "authored-key"
