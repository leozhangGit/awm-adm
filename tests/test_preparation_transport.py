"""Preparation deadlines and safe failure reasons, without network calls or sleeps."""

import http.client
import json
import socket
import ssl
import subprocess

import pytest
from pydantic import ValidationError

from awm_adm.config import AppConfig
from awm_adm.gateway import call
from awm_adm.learning.models import Outcome
from awm_adm.providers import transport
from awm_adm.runtime.protocol import dumps, loads
from awm_adm.runtime.service import Runtime
from awm_adm.teaching.provider_failure import preparation_failure

from .interaction_support import respond
from .test_application import app_runtime as app_runtime
from .test_direct_ask import recorded, work
from .test_learning_service import rig as rig
from .test_plugin_workflow import connector


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize(
    "error,reason",
    [
        (TimeoutError, "timeout"),
        (socket.gaierror, "dns"),
        (ssl.SSLError, "tls"),
        (ConnectionResetError, "connection"),
        (http.client.RemoteDisconnected, "connection"),
        (http.client.BadStatusLine, "http_protocol"),
        (OSError, "connection"),
        (ValueError, "transport_error"),
    ],
)
def test_transport_reasons_are_safe_and_uncertain(provider, error, reason, monkeypatch):
    clock, calls = [100.0], []
    monkeypatch.setattr(transport.time, "monotonic", lambda: clock[0])

    def failure(*args):
        calls.append(1)
        clock[0] += 12.25
        raise error("Authorization: private-value")

    result = transport.acquire({"provider": provider}, b"{}", "private-value", 180, transport=failure)
    assert result["status"] == "outcome_unknown" and result["usage"] is None and result["text"] is None
    assert result["error"] == ("provider_timeout" if reason == "timeout" else "transport_uncertain")
    assert result["diagnostics"] == {
        "transport_failure": reason,
        "failure_stage": "transport",
        "elapsed_ms": 12250,
        "timeout_ms": 180000,
    }
    assert calls == [1] and "private-value" not in json.dumps(result)
    Outcome.model_validate(result)


@pytest.mark.parametrize("stage", ["request", "response_headers", "response_body", "oversized"])
def test_https_retains_stage_and_observed_status_without_body(stage, monkeypatch):
    class Connection:
        sock = None
        status = 200
        closed = False

        def request(self, *args, **kwargs):
            if stage == "request":
                raise ConnectionRefusedError("private-value")

        def getresponse(self):
            if stage == "response_headers":
                raise TimeoutError("private-value")
            return self

        def read1(self, size):
            if stage == "response_body":
                raise TimeoutError("private-value")
            return b"private-value"

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(transport.http.client, "HTTPSConnection", lambda *a, **kw: connection)
    monkeypatch.setattr(transport, "MAX_RESPONSE", 5)
    result = transport.acquire({"provider": "openai"}, b"{}", "private-value", 180)
    d = result["diagnostics"]
    assert d["failure_stage"] == ("response_body" if stage == "oversized" else stage)
    assert d.get("http_status") == (200 if stage in ("response_body", "oversized") else None)
    if stage == "oversized":
        assert d["transport_failure"] == "response_too_large"
    assert connection.closed and "private-value" not in json.dumps(result)
    Outcome.model_validate(result)


@pytest.mark.parametrize(
    "case", ["timeout", "exit", "oversized", "invalid", "shape", "start", "pipe", "success"]
)
def test_gateway_classifies_process_failures_and_reaps_child(case, monkeypatch):
    clock, seen = [100.0], []
    monkeypatch.setattr(call.time, "monotonic", lambda: clock[0])

    class Process:
        pid = 12345
        returncode = -9 if case == "exit" else 0

        def communicate(self, body, timeout):
            seen.append("communicate")
            assert json.loads(body)["credential"] == "private-value"
            clock[0] += 180 if case == "timeout" else 2
            if case == "timeout":
                raise subprocess.TimeoutExpired("private-value", timeout)
            if case == "pipe":
                raise BrokenPipeError("private-value")
            output = {
                "oversized": b"x" * 1_048_577,
                "invalid": b'{"private-value":',
                "shape": b'{"private-value":true}',
            }.get(
                case,
                dumps(
                    {"status": "succeeded", "text": "{}", "usage": {"input_tokens": 5, "output_tokens": 1}}
                ),
            )
            return output, None

        def wait(self):
            seen.append("wait")

    def start(*args, **kwargs):
        seen.append("start")
        if case == "start":
            raise OSError("private-value")
        return Process()

    monkeypatch.setattr(call.subprocess, "Popen", start)
    monkeypatch.setattr(call.os, "killpg", lambda *args: seen.append("kill"))
    result = call.bounded_acquire({"provider": "openai"}, b"{}", "private-value", 180)
    assert "private-value" not in json.dumps(result)
    assert seen.count("start") == 1
    if case != "start":
        assert seen[-2:] == ["kill", "wait"]
    d = result["diagnostics"]
    assert d["timeout_ms"] == 180000
    assert d["elapsed_ms"] == (180000 if case == "timeout" else 0 if case == "start" else 2000)
    if case == "success":
        assert result["status"] == "succeeded" and result["usage"]["input_tokens"] == 5
    else:
        assert result["status"] == "outcome_unknown" and result["usage"] is None
        assert (
            d["transport_failure"]
            == {
                "timeout": "timeout",
                "exit": "child_exit",
                "oversized": "child_output_too_large",
                "invalid": "child_output_invalid",
                "shape": "child_output_invalid",
                "start": "child_start_failed",
                "pipe": "transport_error",
            }[case]
        )
    if case == "exit":
        assert d["child_exit_code"] == -9  # A signal does not establish its cause (e.g. OOM).
    Outcome.model_validate(result)


@pytest.mark.parametrize("value", [0, 300001, True])
def test_preparation_timeout_is_finite(value):
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"learning": {"preparation_timeout_ms": value}})


def test_preparation_has_three_minutes_while_ask_and_compute_limits_are_unchanged(rig, monkeypatch):
    rt, gw = rig
    key = rt.create("Independent preparation timeout")["id"]
    recorded(rt, gw, {})
    baseline = rt.limits()
    now = rt.learning.now()
    clock = [now]
    monkeypatch.setattr(rt.learning, "now", lambda: clock[0])
    monkeypatch.setattr(rt.conversations, "now", lambda: int(clock[0] * 1000))
    item = rt.interactions.submit(key, "teach", {"text": "Keep the adopted finite rule."})
    assert rt.conversations.teaching.tick()
    current = work(rt, key, item["id"])
    with rt.store.db() as db:
        grant = loads(db.execute("SELECT body FROM grants WHERE id=?", (current["grant_id"],)).fetchone()[0])
    assert grant["limits"]["max_duration_ms"] == 180000
    assert grant["limits"]["max_output_tokens"] == 8192
    assert grant["deadline"] == min(current["deadline_ms"] / 1000, now + 180)
    # A complete response after the old deadline still goes through the normal checker.
    clock[0] += 90
    respond(rt, {"status": "needs_clarification", "message": "Which rule is adopted?", "plan_json": None})
    assert rt.interactions.get(key, item["id"])["status"] == "needs_input"
    assert rt.limits() == baseline
    question = rt.interactions.submit(key, "ask", {"text": "What rules are available?"})
    assert rt.conversations.ask.tick()
    with rt.store.db() as db:
        ask = loads(
            db.execute(
                "SELECT body FROM grants WHERE id=?", (work(rt, key, question["id"])["grant_id"],)
            ).fetchone()[0]
        )
    assert ask["limits"]["max_duration_ms"] == 60000


def test_preparation_respects_configured_shorter_timeout_and_work_deadline(rig, monkeypatch):
    rt, gw = rig
    key = rt.create("Configured bounds")["id"]
    recorded(rt, gw, {})
    config = rt.config.model_dump()
    config["learning"]["preparation_timeout_ms"] = 25000
    monkeypatch.setattr(rt, "config", AppConfig.model_validate(config))
    item = rt.interactions.submit(key, "teach", {"text": "Keep a bounded rule."})
    deadline = work(rt, key, item["id"])["deadline_ms"] / 1000
    monkeypatch.setattr(rt.learning, "now", lambda: deadline - 10)
    monkeypatch.setattr(rt.conversations, "now", lambda: int((deadline - 10) * 1000))
    assert rt.conversations.teaching.tick()
    job = rt.learning.claim()
    value = rt.learning.authorize(job["grant_id"], job["lease"])
    assert value["limits"]["max_duration_ms"] == job["timeout_ms"] == 25000
    assert value["expires"] == value["deadline"] == deadline


@pytest.mark.parametrize(
    "status,error,details,usage",
    [
        (
            "outcome_unknown",
            "provider_timeout",
            {
                "transport_failure": "timeout",
                "failure_stage": "gateway_wait",
                "elapsed_ms": 180010,
                "timeout_ms": 179500,
            },
            None,
        ),
        ("outcome_unknown", "transport_uncertain", {}, None),
        ("failed", "authentication_failed", {"http_status": 401}, None),
        (
            "failed",
            "output_incomplete",
            {"http_status": 200, "incomplete_reason": "max_output_tokens"},
            {"input_tokens": 100, "output_tokens": 8192},
        ),
    ],
)
def test_failure_reaches_teach_history_and_plugin_without_retry_or_acceptance(
    rig, tmp_path, status, error, details, usage
):
    rt, gw = rig
    key = rt.create("Preparation diagnostics")["id"]
    recorded(rt, gw, {})
    before = rt.store.info(key)
    c, root = connector(rt, tmp_path / "project", tmp_path / "private")
    c.project(root, model_id=key)
    first = c.teach(root, text="Retain this adopted observation.", operation="one-call")
    assert rt.conversations.teaching.tick()
    job = rt.learning.claim()
    rt.learning.authorize(job["grant_id"], job["lease"])
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {"status": status, "error": error, "usage": usage, "text": None, "diagnostics": details},
    )
    assert rt.conversations.teaching.tick()
    final = c.work(root, work_id="one-call")
    assert final["state"] == "failed" and final["failure_code"] == error
    d = final["failure_diagnostics"]
    assert d["grant_id"] == job["grant_id"] and d["dispatch_status"] == status
    assert d["configured_timeout_ms"] == 180000
    assert d["usage_unresolved"] == (usage is None) and not d["automatic_retry"]
    assert d["usage"] == usage
    for field, value in details.items():
        assert d["provider_diagnostics"][field] == value
    assert "No learning started" in final["summary"]
    assert final["admissions"] == []
    assert rt.store.info(key) == before
    assert not rt.conversations.teaching.tick()
    assert rt.learning.claim() is None
    assert (
        c.teach(root, text="Retain this adopted observation.", operation="one-call")["interaction_id"]
        == first["interaction_id"]
    )
    assert rt.learning.usage()["calls"] == 1
    view = rt.learning.grant_view(job["grant_id"])
    assert view["unresolved"] == (usage is None)
    history = rt.interactions.chat(key, "teach")["items"]
    assert history[0]["failure_diagnostics"] == d
    with rt.store.db(key) as db:
        for table in ("episodes", "requests", "chat_questions"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    rt.close()
    restored = Runtime(rt.config, start_scheduler=False)
    try:
        retained = restored.interactions.get(key, first["interaction_id"])
        assert retained["failure_diagnostics"] == d and retained["failure_code"] == error
        assert restored.learning.grant_view(job["grant_id"])["unresolved"] == (usage is None)
        assert restored.learning.claim() is None
        assert restored.store.info(key) == before
    finally:
        restored.close()


def test_legacy_uncertainty_is_not_relabelled_as_timeout():
    result = preparation_failure(
        "old",
        {"status": "outcome_unknown", "error": "transport_uncertain", "usage": None},
        {"max_duration_ms": 60000},
    )
    assert result["code"] == "transport_uncertain"
    assert "timed out" not in result["message"]
    assert not result["provider_diagnostics"]
