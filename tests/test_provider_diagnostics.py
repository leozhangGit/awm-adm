"""Failure propagation and conservative accounting, using simulated providers only."""

# ruff: noqa: F811

import json
from uuid import uuid4

import pytest

from awm_adm.learning.models import Outcome
from awm_adm.providers.transport import acquire, interpret
from awm_adm.runtime.protocol import dumps, loads

from .test_application import app_runtime  # noqa: F401
from .test_language_service import conversation
from .test_language_service import interpret as language_interpret
from .test_learning_service import advance, dispatch, episode, rig  # noqa: F401
from .test_provider_transports import raw, response
from .test_sources import ingest, install, job


@pytest.mark.parametrize(
    "reason", ["max_output_tokens", "content_filter", "steered", None, {"secret": "private"}]
)
def test_incomplete_reason_is_allowlisted_and_partial_output_never_survives(reason):
    result = interpret(
        "openai", raw(response("openai", status="incomplete", incomplete_details={"reason": reason}))
    )
    assert result["error"] == "output_incomplete" and result["text"] is None
    assert result["diagnostics"]["incomplete_reason"] == (reason if isinstance(reason, str) else "unknown")
    assert result["usage"] == {"input_tokens": 11, "output_tokens": 4}
    assert "private" not in json.dumps(result)
    Outcome.model_validate(result)


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("incomplete", [True, False])
def test_remote_zero_usage_is_evidence_not_settlement(provider, incomplete):
    extra = (
        ({"status": "incomplete"} if provider == "openai" else {"stop_reason": "max_tokens"})
        if incomplete
        else {}
    )
    result = interpret(
        provider, raw(response(provider, usage={"input_tokens": 0, "output_tokens": 0}, **extra))
    )
    assert result["usage"] is None
    assert result["diagnostics"]["reported_usage"] == {"input_tokens": 0, "output_tokens": 0}
    assert result["diagnostics"]["usage_assessment"] == "zero_unverified"
    Outcome.model_validate(result)


def test_incomplete_metadata_retains_counts_not_partial_text_or_reasoning():
    result = interpret(
        "openai",
        raw(
            response(
                "openai",
                status="incomplete",
                incomplete_details={"reason": "max_output_tokens"},
                reasoning={"effort": "none", "mode": "standard", "summary": "private-summary"},
                usage={
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "input_tokens_details": {"cached_tokens": 0, "private": "never-retain"},
                    "output_tokens_details": {"reasoning_tokens": 0, "private": "never-retain"},
                },
                output=[
                    {"type": "reasoning", "summary": "private-summary", "content": "private-reasoning"},
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"partial":"é'}],
                    },
                    {"type": "private-type", "content": "private-content"},
                ],
            )
        ),
    )
    diagnostic = result["diagnostics"]
    assert diagnostic["token_details"] == dict(total_tokens=0, cached_input_tokens=0, reasoning_tokens=0)
    assert diagnostic["reasoning_effort"] == "none" and diagnostic["reasoning_mode"] == "standard"
    assert diagnostic["output_summary"] == {
        "item_count": 3,
        "message_items": 1,
        "text_items": 0,
        "reasoning_items": 1,
        "other_items": 1,
        "visible_text_parts": 1,
        "visible_text_bytes": len('{"partial":"é'.encode()),
    }
    assert result["text"] is None and result["usage"] is None
    assert result["error"] == "output_incomplete"
    assert all(s not in json.dumps(result) for s in ("private-", "never-retain", "partial"))
    Outcome.model_validate(result)


@pytest.mark.parametrize("invalid", [True, -1, 2**53, 1.5, "14", {"private": 42}])
def test_malformed_optional_counters_and_settings_do_not_mask_the_failure(invalid):
    result = interpret(
        "openai",
        raw(
            response(
                "openai",
                status="incomplete",
                incomplete_details={"reason": "max_output_tokens"},
                usage={
                    "input_tokens": 11,
                    "output_tokens": 4,
                    "total_tokens": invalid,
                    "input_tokens_details": {"cached_tokens": invalid},
                    "output_tokens_details": {"reasoning_tokens": invalid},
                },
                reasoning={"effort": invalid, "mode": invalid},
            )
        ),
    )
    assert "token_details" not in result["diagnostics"]
    assert result["diagnostics"]["reasoning_effort"] == "unknown"
    assert result["diagnostics"]["reasoning_mode"] == "unknown"
    assert result["error"] == "output_incomplete"
    assert result["usage"] == {"input_tokens": 11, "output_tokens": 4}
    Outcome.model_validate(result)


@pytest.mark.parametrize(
    "output",
    [
        None,
        {},
        [None],
        [{"type": "message", "content": None}],
        [{"type": "message", "content": [{"type": "output_text", "text": "\ud800"}]}],
    ],
)
def test_absent_or_malformed_output_summary_is_unknown_not_zero(output):
    result = interpret("openai", raw(response("openai", status="incomplete", output=output)))
    assert "output_summary" not in result["diagnostics"]
    assert "reasoning_effort" not in result["diagnostics"]
    assert "token_details" not in result["diagnostics"]
    assert result["error"] == "output_incomplete"


def test_explicit_empty_output_is_a_measured_zero_summary():
    result = interpret("openai", raw(response("openai", status="incomplete", output=[])))
    assert set(result["diagnostics"]["output_summary"].values()) == {0}
    Outcome.model_validate(result)


def test_anthropic_metadata_counts_blocks_and_preserves_cache_counters_without_thinking():
    result = interpret(
        "anthropic",
        raw(
            response(
                "anthropic",
                stop_reason="max_tokens",
                usage={
                    "input_tokens": 11,
                    "output_tokens": 4,
                    "cache_creation_input_tokens": 5,
                    "cache_read_input_tokens": 2,
                },
                content=[
                    {"type": "thinking", "thinking": "private-thought"},
                    {"type": "redacted_thinking", "data": "private-data"},
                    {"type": "text", "text": "é"},
                ],
            )
        ),
    )
    assert result["diagnostics"]["token_details"] == {
        "cache_creation_input_tokens": 5,
        "cache_read_input_tokens": 2,
    }
    assert result["diagnostics"]["output_summary"]["reasoning_items"] == 2
    assert result["diagnostics"]["output_summary"]["text_items"] == 1
    assert result["diagnostics"]["output_summary"]["visible_text_bytes"] == 2
    assert "reasoning_effort" not in result["diagnostics"]
    assert "private-" not in json.dumps(result)
    assert result["usage"] == {"input_tokens": 18, "output_tokens": 4}
    assert result["text"] is None and result["error"] == "output_incomplete"
    Outcome.model_validate(result)


@pytest.mark.parametrize(
    "code,expected",
    [
        ("insufficient_quota", "provider_quota_exhausted"),
        ("rate_limit_exceeded", "rate_limited"),
        ("private-secret", "rate_limited"),
    ],
)
def test_http_quota_is_distinct_from_rate_limit_without_error_body_disclosure(code, expected):
    result = acquire(
        {"provider": "openai"},
        b"{}",
        "private-secret",
        1,
        transport=lambda *args: (429, raw({"error": {"code": code, "message": "private-secret"}})),
    )
    assert result["error"] == expected
    assert result["diagnostics"]["http_status"] == 429
    assert result["usage"] is None
    assert "private-secret" not in json.dumps(result)
    Outcome.model_validate(result)


def remote_connection(rt, gateway, tmp_path, output):
    gateway.store.static_dir = tmp_path
    (tmp_path / "openai-key").write_text("authored-test-credential")
    rt.learning.configure(
        {"expected_generation": rt.learning.settings()["generation"], "remote_calls_enabled": True}
    )
    c = rt.learning.save_connection(
        {
            "idempotency_key": str(uuid4()),
            "name": "Simulated diagnostics",
            "provider": "openai",
            "model": "gpt-4o-2024-08-06",
            "enabled": True,
            "credential_mode": "static",
            "purposes": ["acquisition", "interpretation", "extraction"],
        }
    )
    gateway.synchronize()
    gateway.synchronize()
    calls = []

    def transport(*args):
        calls.append(1)
        return 200, raw(output)

    gateway.transport = transport
    # Explicit M2 authority; the transport above remains simulated/no-egress.
    rt.config = rt.config.model_copy(
        update={
            "learning": rt.config.learning.model_copy(
                update={
                    "call": rt.config.learning.call.model_copy(update={"max_input_tokens": 128000}),
                    "episode": rt.config.learning.episode.model_copy(update={"max_input_tokens": 768000}),
                }
            )
        }
    )
    rt.learning.config = rt.config
    service = rt.learning.allowances
    service.configure(
        {
            "expected_generation": 0,
            "enabled": True,
            "total_micro_usd": 4_000_000,
            "interaction_micro_usd": 2_000_000,
            "learning_micro_usd": 2_000_000,
        }
    )
    c = rt.learning.connection(c["id"])
    price = service.save_price(
        {
            "idempotency_key": str(uuid4()),
            "connection_id": c["id"],
            "connection_version": c["version"],
            "configuration_digest": c["configuration_digest"],
            "bound_profile": "openai-4o-context/2026-11-08",
            "input_micro_usd_per_million": 2_500_000,
            "output_micro_usd_per_million": 10_000_000,
            "valid_until_ms": service.now() + 600000,
        }
    )
    c["test_price_id"] = price["id"]
    return c, calls


def remote_budget(rt, c, key, scope="task"):
    service = rt.learning.allowances
    allowance = service.create(
        {
            "idempotency_key": str(uuid4()),
            "price_id": c["test_price_id"],
            "adm_id": key,
            "scope": scope,
            "scope_id": str(uuid4()),
            "cap_micro_usd": 2_000_000,
            "expires_at_ms": service.now() + 300000,
            "max_input_tokens": 768000,
        }
    )
    return {"allowance_id": allowance["id"], "call_limits": rt.config.learning.call.model_dump()}


def test_explicit_source_retry_deduplicates_and_preserves_unknown_reservations(rig, tmp_path):
    rt, gateway = rig
    c, calls = remote_connection(
        rt,
        gateway,
        tmp_path,
        response(
            "openai",
            status="incomplete",
            incomplete_details={"reason": "max_output_tokens"},
            usage={"input_tokens": 0, "output_tokens": 0},
        ),
    )
    key = rt.create("Explicit retry")["id"]
    install(rt, key)
    source = ingest(rt, key, media_type="text/plain", content="A supplied historical assertion.")
    settings = dict(
        extractor="external",
        connection_id=c["id"],
        connection_version=c["version"],
        **remote_budget(rt, c, key),
    )
    original = job(rt, key, source, **settings)
    rt.sources.tick()
    dispatch(rt, gateway)
    rt.sources.tick()
    failed = rt.sources.get(key, "source_jobs", original["id"])
    assert failed["status"] == "failed"
    before = rt.learning.usage()
    assert before["calls"] == before["unresolved"] == 1
    assert job(rt, key, source, **settings)["id"] == original["id"]

    retry = job(rt, key, source, reprocess_id="owner-retry-1", **settings)
    assert retry["id"] != original["id"]
    # A repeated click or a re-entered label after reload recovers the same job.
    assert job(rt, key, source, reprocess_id="owner-retry-1", **settings)["id"] == retry["id"]
    rt.sources.tick()
    dispatch(rt, gateway)
    rt.sources.tick()
    assert job(rt, key, source, reprocess_id="owner-retry-1", **settings)["id"] == retry["id"]
    assert rt.learning.claim() is None
    assert len(calls) == 2
    assert rt.sources.get(key, "source_jobs", original["id"]) == failed
    after = rt.learning.usage()
    assert after["calls"] == after["unresolved"] == 2
    assert after["input_tokens"] == 2 * before["input_tokens"]
    assert after["output_tokens"] == 2 * before["output_tokens"]
    assert rt.sources.overview(key)["claims"] == []


@pytest.mark.parametrize("purpose", ["acquisition", "interpretation", "extraction"])
def test_failure_survives_gateway_api_and_restart_without_dispatching_again(
    rig, tmp_path, monkeypatch, purpose
):
    rt, gateway = rig
    c, calls = remote_connection(
        rt,
        gateway,
        tmp_path,
        response(
            "openai",
            status="incomplete",
            incomplete_details={"reason": "max_output_tokens"},
            usage={"input_tokens": 0, "output_tokens": 0, "output_tokens_details": {"reasoning_tokens": 0}},
            reasoning={"effort": "none", "mode": "standard"},
        ),
    )
    key = rt.create("Failure diagnostics")["id"]
    budget = remote_budget(rt, c, key, "interaction" if purpose == "interpretation" else "task")
    if purpose == "extraction":
        install(rt, key)
        source = ingest(rt, key, media_type="text/plain", content="Owner authored capacity record.")
        item = job(
            rt,
            key,
            source,
            extractor="external",
            connection_id=c["id"],
            connection_version=c["version"],
            **budget,
        )
        tick = rt.sources.tick

        def get():
            return rt.sources.detail(key, "jobs", item["id"])
    elif purpose == "interpretation":
        item = language_interpret(
            rt,
            key,
            conversation(rt, key),
            translator="external",
            connection_id=c["id"],
            connection_version=c["version"],
            disclose_catalog=True,
            **budget,
        )
        tick = rt.language.tick

        def get():
            return rt.language.get(key, item["id"])
    else:
        item = episode(rt, key, c, limits=rt.config.learning.episode.model_dump(), **budget)
        advance(rt, key, item["id"], "acquiring")
        tick = rt.learning.tick

        def get():
            return rt.learning.episode(key, item["id"])

    tick()
    dispatch(rt, gateway)
    tick()
    state = get()
    assert state["status"] in ("failed", "stopped")
    assert state.get("error", state.get("reason")) == "output_incomplete"
    view = state["provider_failure"]
    assert view["unresolved"] and view["output_tokens"] > 0 and view["input_tokens"] > 0
    assert view["outcome"]["diagnostics"]["incomplete_reason"] == "max_output_tokens"
    assert view["outcome"]["diagnostics"]["reasoning_effort"] == "none"
    assert view["outcome"]["diagnostics"]["token_details"]["reasoning_tokens"] == 0
    assert view["outcome"]["diagnostics"]["output_summary"]["visible_text_bytes"] == 11
    rt.learning.recover()
    assert rt.learning.grant_view(view["id"])["outcome"]["diagnostics"] == view["outcome"]["diagnostics"]
    assert view["outcome"]["usage"] is None
    assert rt.learning.usage()["unresolved"] == 1
    if purpose == "extraction":
        assert rt.sources.history(key)["jobs"][0]["provider_failure"] == view
        assert not rt.sources.history(key)["claims"]
    for _ in range(3):
        tick()
        gateway.synchronize()
    assert len(calls) == 1
    # Simulate the old installed adapter's immutable 0/0 outcome and settled ledger.
    with rt.store.db() as db:
        row = db.execute("SELECT * FROM grants WHERE id=?", (view["id"],)).fetchone()
        old = loads(row["outcome"])
        old.pop("diagnostics")
        old["usage"] = {"input_tokens": 0, "output_tokens": 0}
        original = dumps(old)
        db.execute(
            "UPDATE grants SET outcome=?,input_tokens=0,output_tokens=0,unresolved=0 WHERE id=?",
            (original, view["id"]),
        )
    rt.learning.recover()
    rt.learning.recover()
    recovered = rt.learning.grant_view(view["id"])
    assert recovered["status"] == "failed" and recovered["unresolved"]
    assert recovered["input_tokens"] == view["input_tokens"]
    assert recovered["output_tokens"] == view["output_tokens"]
    assert recovered["outcome"]["diagnostics"]["incomplete_reason"] == "unknown"
    with rt.store.db() as db:
        assert db.execute("SELECT outcome FROM grants WHERE id=?", (view["id"],)).fetchone()[0] == original
    assert len(calls) == 1
    assert "authored-test-credential" not in json.dumps(get())
    later = rt.learning.now() + rt.config.learning.quotas.period_seconds + 1
    monkeypatch.setattr(rt.learning, "now", lambda: later)
    assert rt.learning.usage()["unresolved"] == 1
    assert rt.learning.usage()["input_tokens"] == view["input_tokens"]
