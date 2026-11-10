"""offline service trials through real bounded children and durable gateway."""

import base64
import json
import time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from awm_adm.engine import Instance
from awm_adm.gateway.service import Gateway
from awm_adm.gateway.store import LABEL, GatewayStore
from awm_adm.runtime.protocol import RuntimeFault, dumps, pack
from awm_adm.runtime.service import Runtime

from .ported.helpers import literal
from .test_application import app_runtime, client, configuration, envelope, execute  # noqa: F401
from .test_construction_core import contract, wire
from .test_instance import capacity_policy, value_query


@pytest.fixture
def rig(app_runtime, tmp_path):  # noqa: F811
    rt = app_runtime
    vault = GatewayStore(tmp_path / "gateway", Fernet.generate_key())

    def exchange(route, body):
        if route == "synchronize":
            return rt.learning.synchronize(**body)
        if route == "authorize":
            return rt.learning.authorize(body["grant_id"], body["lease"])
        if route == "outcome":
            return rt.learning.outcome(body["grant_id"], body["lease"], body["outcome"])
        raise AssertionError(route)

    gateway = Gateway(vault, exchange)
    try:
        yield rt, gateway
    finally:
        vault.close()


def connection(rt, gateway, replies=None):
    c = rt.learning.save_connection(
        {
            "idempotency_key": "connection-" + str(time.time_ns()),
            "name": "Authored recorded fixture",
            "provider": "recorded",
            "model": "fixture",
            "enabled": True,
            "recorded_responses": replies if replies is not None else [wire(literal(10))],
        }
    )
    gateway.synchronize()
    gateway.synchronize()
    return rt.learning.connection(c["id"])


def episode(rt, key, c, **kw):
    body = {
        "idempotency_key": "episode-" + str(time.time_ns()),
        "expected_revision": rt.store.info(key)["revision_id"],
        "connection_id": c["id"],
        "connection_version": c["version"],
        "task": {"description": "The owner says site capacity is ten.", "acquisition_contract": contract()},
        **kw,
    }
    return rt.learning.create(key, body)


def dispatch(rt, gateway):
    job = rt.learning.claim()
    assert job
    return gateway.dispatch(job["grant_id"], job["lease"])


def advance(rt, key, eid, target, count=20):
    for _ in range(count):
        ep = rt.learning.episode(key, eid)
        if ep["status"] == target:
            return ep
        rt.learning.tick()
    raise AssertionError(rt.learning.episode(key, eid))


def approve(rt, key, ep):
    receipt = ep["receipts"][-1]
    rt.learning.review(
        key, receipt["id"], {"expected_revision": rt.store.info(key)["revision_id"], "approve": True}
    )
    return advance(rt, key, ep["id"], "accepted")


def test_recorded_learning_keeps_serving_and_retries_locally_with_immutable_attempts(rig):
    rt, gateway = rig
    c = connection(rt, gateway)
    key = rt.create("empty")["id"]
    request = rt.coordinator.submit(key, envelope("learn-me", value_query()))
    assert execute(rt, key)["status"] == "needs_input"
    original = rt.store.request(key, request["request_id"])
    ep = episode(rt, key, c, request_ids=[request["request_id"]])
    assert rt.store.request(key, request["request_id"])["status"] == "waiting_for_learning"
    advance(rt, key, ep["id"], "acquiring")
    # Local capability serving progresses without invoking a gateway call.
    second = rt.coordinator.submit(key, envelope("while-learning"))
    assert execute(rt, key)["request_id"] == second["request_id"]
    assert rt.query(key, value_query())["result"]["status"] == "needs_input"
    dispatch(rt, gateway)
    held = advance(rt, key, ep["id"], "awaiting_review")
    assert rt.query(key, value_query())["result"]["status"] == "needs_input"
    approve(rt, key, held)
    result = execute(rt, key)
    assert result["result"]["value"]["value"] == 10
    assert result["initial_revision_id"] == original["revision_id"]
    assert result["attempts"][0]["revision"] == original["revision_id"]
    assert result["attempts"][1]["revision"] == result["revision_id"] != original["revision_id"]
    assert rt.learning.usage(episode=ep["id"]) == {
        "calls": 1,
        "input_tokens": 0,
        "output_tokens": 0,
        "unresolved": 0,
    }


def test_wrong_proposal_fails_independent_owner_checks_then_bounded_repair(rig):
    rt, gateway = rig
    c = connection(rt, gateway, [wire(literal(12)), wire(literal(10))])
    key = rt.create("checked", snapshot=pack(Instance(policy=capacity_policy()).export_snapshot()))["id"]
    ep = episode(rt, key, c, publication="checked_auto")
    advance(rt, key, ep["id"], "acquiring")
    dispatch(rt, gateway)
    rt.learning.tick()
    rt.learning.tick()
    assert rt.query(key, value_query())["result"]["status"] == "needs_input"
    after = advance(rt, key, ep["id"], "acquiring")
    assert after["receipts"][0]["status"] == "rejected"
    assert after["feedback"] and after["body"]["task"] == ep["body"]["task"]
    dispatch(rt, gateway)
    done = advance(rt, key, ep["id"], "accepted")
    assert len(done["history"]) == 2
    assert rt.query(key, value_query())["result"]["value"] == 10


@pytest.mark.parametrize("claimed", [False, True])
def test_cancel_other_episode_preserves_local_retry_after_publication(rig, claimed):
    rt, gateway = rig
    c = connection(rt, gateway)
    key = rt.create("independent local retry")["id"]
    request = rt.coordinator.submit(key, envelope("gap", value_query()))
    assert execute(rt, key)["status"] == "needs_input"
    first = episode(rt, key, c, request_ids=[request["request_id"]])
    second = episode(rt, key, c, request_ids=[request["request_id"]])
    advance(rt, key, first["id"], "acquiring")
    dispatch(rt, gateway)
    approve(rt, key, advance(rt, key, first["id"], "awaiting_review"))
    lease = rt.store.claim_request(key) if claimed else None
    expected = "evaluating" if claimed else "received"
    assert rt.store.request(key, request["request_id"])["status"] == expected
    rt.learning.cancel(key, second["id"])
    assert rt.store.request(key, request["request_id"])["status"] == expected
    if claimed:
        rt.coordinator.perform(key, lease)
        result = rt.store.request(key, request["request_id"])
    else:
        result = execute(rt, key)
    assert result["status"] == "succeeded"
    assert result["result"]["value"]["value"] == 10


@pytest.mark.parametrize("mode,expected,status", [("forward", 12, "accepted"), ("backward", 10, "rejected")])
def test_receipt_order_review_hold_and_conflict_modes(rig, mode, expected, status):
    rt, gateway = rig
    a = connection(rt, gateway)
    b = connection(rt, gateway, [wire(literal(12))])
    key = rt.create("conflicts", mode=mode)["id"]
    first = episode(rt, key, a)
    second = episode(rt, key, b)
    advance(rt, key, first["id"], "acquiring")
    dispatch(rt, gateway)
    first = advance(rt, key, first["id"], "awaiting_review")
    advance(rt, key, second["id"], "acquiring")
    dispatch(rt, gateway)
    second = advance(rt, key, second["id"], "awaiting_review")
    rt.learning.review(
        key,
        second["receipts"][0]["id"],
        {"expected_revision": rt.store.info(key)["revision_id"], "approve": True},
    )
    rt.learning.tick()
    assert rt.query(key, value_query())["result"]["status"] == "needs_input"
    approve(rt, key, first)
    rt.learning.tick()
    second = advance(rt, key, second["id"], "awaiting_review")
    rt.learning.review(
        key,
        second["receipts"][0]["id"],
        {"expected_revision": rt.store.info(key)["revision_id"], "approve": True},
    )
    advance(rt, key, second["id"], status)
    assert rt.query(key, value_query())["result"]["value"] == expected
    assert [r["seq"] for r in second["receipts"]] == [2]


def test_cancel_last_interest_fences_dispatch_and_keeps_request(rig):
    rt, gateway = rig
    c = connection(rt, gateway)
    key = rt.create("cancel")["id"]
    request = rt.coordinator.submit(key, envelope("gap", value_query()))
    execute(rt, key)
    ep = episode(rt, key, c, request_ids=[request["request_id"]])
    advance(rt, key, ep["id"], "acquiring")
    rt.coordinator.cancel(key, request["request_id"])
    assert rt.learning.claim() is None
    advance(rt, key, ep["id"], "stopped")
    assert rt.store.request(key, request["request_id"])["status"] == "cancelled"
    assert rt.learning.usage(episode=ep["id"])["calls"] == 0


def test_cancel_during_dispatch_retains_usage_and_never_publishes(rig):
    rt, gateway = rig
    c = connection(rt, gateway)
    key = rt.create("cancel")["id"]
    ep = episode(rt, key, c)
    advance(rt, key, ep["id"], "acquiring")
    job = rt.learning.claim()
    rt.learning.authorize(job["grant_id"], job["lease"])
    rt.learning.cancel(key, ep["id"])
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {
            "status": "succeeded",
            "text": json.dumps(wire(literal(10))),
            "usage": {"input_tokens": 20, "output_tokens": 10},
        },
    )
    assert not rt.learning.episode(key, ep["id"])["receipts"]
    assert rt.query(key, value_query())["result"]["status"] == "needs_input"
    assert rt.learning.usage(episode=ep["id"])["calls"] == 1


def test_unknown_dispatch_retains_reservation_across_restart_and_period(tmp_path):
    cfg = configuration(tmp_path / "app")
    rt = Runtime(cfg, start_scheduler=False)
    master = Fernet.generate_key()
    vault = GatewayStore(tmp_path / "gateway", master)
    gateway = Gateway(vault, lambda route, body: rt.learning.synchronize(**body))
    c = connection(rt, gateway)
    key = rt.create("uncertain")["id"]
    ep = episode(rt, key, c)
    advance(rt, key, ep["id"], "acquiring")
    job = rt.learning.claim()
    body = rt.learning.authorize(job["grant_id"], job["lease"])
    vault.begin(body["id"], body["provenance"]["request_hash"], body)
    before = rt.learning.usage()
    with rt.store.db() as db:
        db.execute("UPDATE grants SET created=0")
    rt.close()
    vault.close()
    rt = Runtime(cfg, start_scheduler=False)
    vault = GatewayStore(tmp_path / "gateway", master)
    try:
        assert rt.learning.claim() is None
        assert rt.learning.usage() == before
        assert rt.learning.episode(key, ep["id"])["status"] == "stopped"
        assert vault.lookup(body["id"])["status"] == "outcome_unknown"
        assert not vault.begin(body["id"], body["provenance"]["request_hash"], body)
    finally:
        rt.close()
        vault.close()


def test_credential_sealing_rotation_ciphertext_binding_and_no_plaintext(rig):
    rt, gateway = rig
    gateway.synchronize()

    def configured(version=None):
        idem = "key-" + str(time.time_ns())
        clear = "authored-secret-not-an-account-key"
        public = serialization.load_der_public_key(base64.b64decode(gateway.store.public["spki"]))
        encrypted = public.encrypt(
            dumps({"credential": clear, "provider": "openai", "idempotency_key": idem}),
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=LABEL),
        )
        data = {
            "idempotency_key": idem,
            "name": "sealed",
            "provider": "openai",
            "model": "configured-model",
            "credential_mode": "managed",
            "sealed_credential": base64.b64encode(encrypted).decode(),
            "sealing_key_id": gateway.store.public["key_id"],
        }
        if version:
            data["expected_version"] = version["version"]
        result = rt.learning.save_connection(data, version["id"] if version else None)
        gateway.synchronize()
        gateway.synchronize()
        assert "sealed_credential" not in result
        return rt.learning.connection(result["id"]), clear

    c, clear = configured()
    assert c["status"] == "ready"
    c2, _ = configured(c)
    assert c2["version"] == 2
    assert gateway.store.connection(c2["id"], 2, c2["configuration_digest"])[1] == clear
    for root in (gateway.store.root, rt.store.root):
        for path in root.iterdir():
            if path.is_file():
                assert clear.encode() not in path.read_bytes()
    with gateway.store.db() as db:
        old = db.execute("SELECT credential FROM connections WHERE version=1").fetchone()[0]
        db.execute("UPDATE connections SET credential=? WHERE version=2", (old,))
    with pytest.raises(ValueError, match="binding"):
        gateway.store.connection(c2["id"], 2, c2["configuration_digest"])


def test_public_authority_validation_budgeted_test_and_metadata(rig):
    rt, gateway = rig
    c = connection(rt, gateway, [{"ok": True}])
    with client(rt) as http:
        response = http.post(
            f"/api/v1/connections/{c['id']}/test", json={"idempotency_key": "test", "expected_version": 1}
        )
        assert response.status_code == 202
        assert rt.learning.usage()["calls"] == 1
        dispatch(rt, gateway)
        result = http.get("/api/v1/dispatches/" + response.json()["id"]).json()
        assert result["status"] == "succeeded" and "text" not in result["outcome"]
        assert (
            http.post(
                f"/api/v1/connections/{c['id']}/test", json={"idempotency_key": "test", "expected_version": 1}
            ).json()["id"]
            == result["id"]
        )
        key = rt.create("owner")["id"]
        token = http.post(
            "/api/v1/auth/tokens", json={"adms": [key], "permissions": ["read", "submit"]}
        ).json()["token"]
        assert (
            http.get("/api/v1/connections", headers={"Authorization": "Bearer " + token}).status_code == 403
        )
        invalid = http.post(
            f"/api/v1/adms/{key}/episodes",
            json={
                "idempotency_key": "bad",
                "expected_revision": rt.store.info(key)["revision_id"],
                "connection_id": c["id"],
                "connection_version": 1,
                "task": {"acquisition_contract": {}},
            },
        )
        assert invalid.status_code == 422


def test_no_auto_publication_without_independent_requirements(rig):
    rt, gateway = rig
    c = connection(rt, gateway)
    key = rt.create("policy-free")["id"]
    ep = episode(rt, key, c, publication="checked_auto")
    stopped = advance(rt, key, ep["id"], "stopped")
    assert stopped["reason"] == "admission_rejected" and rt.learning.usage()["calls"] == 0


def test_mode_switch_is_prospective_and_requires_fresh_review(rig):
    rt, gateway = rig
    c = connection(rt, gateway)
    key = rt.create("switch")["id"]
    first = episode(rt, key, c)
    advance(rt, key, first["id"], "acquiring")
    dispatch(rt, gateway)
    approve(rt, key, advance(rt, key, first["id"], "awaiting_review"))
    c = connection(rt, gateway, [wire(literal(12))])
    second = episode(rt, key, c)
    advance(rt, key, second["id"], "acquiring")
    dispatch(rt, gateway)
    held = advance(rt, key, second["id"], "awaiting_review")
    old = rt.store.info(key)
    rt.learning.review(
        key, held["receipts"][0]["id"], {"expected_revision": old["revision_id"], "approve": True}
    )
    rt.store.change(key, old["policy_epoch"], mode="forward")
    held = advance(rt, key, second["id"], "awaiting_review")
    assert rt.query(key, value_query())["result"]["value"] == 10
    approve(rt, key, held)
    assert rt.query(key, value_query())["result"]["value"] == 12
    historical = rt.learning.episode(key, first["id"])["receipts"][0]["data"]["decision"]
    assert historical["mode"] == "backward" and historical["policy_epoch"] == 0


def test_cancel_and_policy_change_during_admission_fence_publication(rig, monkeypatch):
    rt, gateway = rig
    c = connection(rt, gateway)
    key = rt.create("race")["id"]
    ep = episode(rt, key, c)
    advance(rt, key, ep["id"], "acquiring")
    dispatch(rt, gateway)
    held = advance(rt, key, ep["id"], "awaiting_review")
    rt.learning.review(
        key,
        held["receipts"][0]["id"],
        {"expected_revision": rt.store.info(key)["revision_id"], "approve": True},
    )
    original = rt.learning.supervisor.run

    def raced(task, **kwargs):
        value = original(task, **kwargs)
        if task["operation"] == "learning_admit":
            rt.learning.cancel(key, ep["id"])
        return value

    monkeypatch.setattr(rt.learning.supervisor, "run", raced)
    rt.learning.tick()
    assert rt.learning.episode(key, ep["id"])["status"] == "cancelled"
    assert rt.query(key, value_query())["result"]["status"] == "needs_input"


def test_gateway_delivers_cached_reply_after_lost_ack_without_redispatch(rig):
    rt, gateway = rig
    c = connection(rt, gateway)
    key = rt.create("ack")["id"]
    ep = episode(rt, key, c)
    advance(rt, key, ep["id"], "acquiring")
    job = rt.learning.claim()
    original = gateway.exchange

    def lost_ack(route, body):
        result = original(route, body)
        if route == "outcome":
            raise TimeoutError("Authored lost acknowledgment")
        return result

    gateway.exchange = lost_ack
    with pytest.raises(TimeoutError):
        gateway.dispatch(job["grant_id"], job["lease"])
    gateway.exchange = original
    result = gateway.dispatch(job["grant_id"], job["lease"])
    assert result["replayed"] is True
    assert len(rt.learning.episode(key, ep["id"])["receipts"]) == 1
    assert rt.learning.usage()["calls"] == 1


def test_rotation_and_remote_disable_revoke_existing_work(rig):
    rt, gateway = rig
    c = connection(rt, gateway)
    key = rt.create("revoke")["id"]
    ep = episode(rt, key, c)
    advance(rt, key, ep["id"], "acquiring")
    rt.learning.configure({"expected_generation": 0, "remote_calls_enabled": False})
    assert rt.learning.claim() is None
    assert advance(rt, key, ep["id"], "stopped")["reason"] == "stale_context"
    assert rt.learning.usage()["calls"] == 0


def test_exhausted_episode_preserves_pending_request_and_no_progress_is_bounded(rig):
    rt, gateway = rig
    c = connection(rt, gateway, [{"malformed": True}] * 3)
    key = rt.create("exhaust")["id"]
    req = rt.coordinator.submit(key, envelope("pending", value_query()))
    execute(rt, key)
    ep = episode(rt, key, c, request_ids=[req["request_id"]])
    for _ in range(3):
        advance(rt, key, ep["id"], "acquiring")
        dispatch(rt, gateway)
        rt.learning.tick()
    stopped = advance(rt, key, ep["id"], "stopped")
    assert stopped["reason"] == "no_progress"
    assert stopped["usage"]["calls"] == 3
    assert rt.store.request(key, req["request_id"])["status"] == "needs_input"
    assert rt.learning.claim() is None


def test_private_partial_construction_survives_only_same_context(rig):
    from .ported.helpers import call
    from .ported.provider_fixtures import wire_declaration

    rt, gateway = rig
    first = wire(call("site.base"))
    second = wire(literal(10))
    second["result"]["definitions"]["site.capacity"] = None
    second["result"]["declarations"] = [
        {
            "symbol": "site.base",
            "body": wire_declaration(
                {
                    "kind": "function",
                    "params": {},
                    "returns": {"kind": "int", "min": 0, "max": 100},
                    "body": literal(10),
                }
            ),
        }
    ]
    c = connection(rt, gateway, [first, second])
    key = rt.create("partial")["id"]
    ep = episode(rt, key, c)
    advance(rt, key, ep["id"], "acquiring")
    dispatch(rt, gateway)
    rt.learning.tick()
    assert rt.learning.episode(key, ep["id"])["receipts"][0]["status"] == "partial"
    assert rt.query(key, value_query())["result"]["status"] == "needs_input"
    advance(rt, key, ep["id"], "acquiring")
    dispatch(rt, gateway)
    approve(rt, key, advance(rt, key, ep["id"], "awaiting_review"))
    assert rt.query(key, value_query())["result"]["value"] == 10


def test_aggregate_reservation_counts_unresolved_even_after_period_and_clock_rollback(rig, monkeypatch):
    rt, gateway = rig
    c = connection(rt, gateway, [{"ok": True}])
    rt.learning.config = rt.config.model_copy(
        update={
            "learning": rt.config.learning.model_copy(
                update={"quotas": rt.config.learning.quotas.model_copy(update={"calls_installation": 1})}
            )
        }
    )
    first = rt.learning.test_connection(c["id"], {"idempotency_key": "quota-a", "expected_version": 1})
    with rt.store.db() as db:
        db.execute("UPDATE grants SET created=0")
    monkeypatch.setattr(time, "time", lambda: 1)
    with pytest.raises(RuntimeFault, match="aggregate"):
        rt.learning.test_connection(c["id"], {"idempotency_key": "quota-b", "expected_version": 1})
    assert rt.learning.grant_view(first["id"])["unresolved"]


def test_missing_established_gateway_database_is_not_recreated(tmp_path):
    master = Fernet.generate_key()
    root = tmp_path / "vault"
    store = GatewayStore(root, master)
    store.close()
    (root / "gateway.db").unlink()
    with pytest.raises(ValueError, match="missing"):
        GatewayStore(root, master)


def test_complete_proposal_one_call_and_explicit_deadline(rig):
    from awm_adm.engine.provider_format import FORMAT

    from .ported.provider_fixtures import wire_declaration

    rt, gateway = rig
    reply = {
        "format": FORMAT,
        "status": "candidate",
        "declarations": [
            {
                "symbol": "site.capacity",
                "body": wire_declaration(
                    {
                        "kind": "function",
                        "params": {},
                        "returns": {"kind": "int", "min": 0, "max": 100},
                        "body": literal(10),
                    }
                ),
            }
        ],
        "retractions": [],
        "summary": "Authored complete proposal",
    }
    c = connection(rt, gateway, [reply])
    key = rt.create("complete")["id"]
    limits = rt.config.learning.episode.model_dump()
    limits.update(max_calls=1, no_progress_attempts=1)
    ep = episode(rt, key, c, construction=False, limits=limits)
    advance(rt, key, ep["id"], "acquiring")
    dispatch(rt, gateway)
    held = advance(rt, key, ep["id"], "awaiting_review")
    assert held["receipts"][0]["data"]["preview"]["declarations"]["site.capacity"]["body"] == literal(10)
    approve(rt, key, held)
    assert rt.query(key, value_query())["result"]["value"] == 10
    ep = episode(rt, key, c)
    with rt.store.db(key) as db:
        value = rt.learning._get(key, ep["id"])
        value["deadline"] = 0
        rt.learning._save(db, value)
    assert advance(rt, key, ep["id"], "stopped")["reason"] == "deadline"
    assert rt.learning.usage(episode=ep["id"])["calls"] == 0


def test_failed_inbox_copy_preserves_durable_arrival_order(rig, monkeypatch):
    import sqlite3

    rt, gateway = rig
    a = connection(rt, gateway)
    b = connection(rt, gateway, [wire(literal(12))])
    key = rt.create("arrival")["id"]
    first = episode(rt, key, a)
    second = episode(rt, key, b)
    advance(rt, key, first["id"], "acquiring")
    advance(rt, key, second["id"], "acquiring")
    original = rt.learning._receive

    def fail_first(key, ep, grant, outcome):
        if ep["id"] == first["id"]:
            raise sqlite3.OperationalError("Authored inbox failure after durable arrival")
        return original(key, ep, grant, outcome)

    monkeypatch.setattr(rt.learning, "_receive", fail_first)
    with pytest.raises(sqlite3.OperationalError):
        dispatch(rt, gateway)
    # A second reply reaches the receiver before recovery of the first inbox copy.
    dispatch(rt, gateway)
    monkeypatch.setattr(rt.learning, "_receive", original)
    one = advance(rt, key, first["id"], "awaiting_review")
    two = advance(rt, key, second["id"], "awaiting_review")
    assert one["receipts"][0]["seq"] == 1
    assert two["receipts"][0]["seq"] == 2


def test_shared_interest_cancelling_one_keeps_other_request_active(rig):
    rt, gateway = rig
    c = connection(rt, gateway)
    key = rt.create("shared")["id"]
    requests = []
    for name in ("first", "second"):
        item = rt.coordinator.submit(key, envelope(name, value_query()))
        execute(rt, key)
        requests.append(item["request_id"])
    ep = episode(rt, key, c, request_ids=requests)
    advance(rt, key, ep["id"], "acquiring")
    rt.coordinator.cancel(key, requests[0])
    dispatch(rt, gateway)
    approve(rt, key, advance(rt, key, ep["id"], "awaiting_review"))
    assert execute(rt, key)["request_id"] == requests[1]
    assert rt.store.request(key, requests[0])["status"] == "cancelled"


def test_schema_three_migration_preserves_revision_pins_and_requests(tmp_path):
    import sqlite3

    cfg = configuration(tmp_path / "migration")
    rt = Runtime(cfg, start_scheduler=False)
    key = rt.create("existing-M4")["id"]
    req = rt.coordinator.submit(key, envelope())
    execute(rt, key)
    saved = rt.store.request(key, req["request_id"])
    rt.close()
    root = Path(cfg.server.data_dir)
    with sqlite3.connect(root / "registry.db") as db:
        from tests.migration_support import remove_admin

        remove_admin(db)
        for table in ("learning_control", "connections", "grants", "connection_tests", "source_arrivals"):
            db.execute("DROP TABLE " + table)
        from tests.migration_support import remove_conversations

        remove_conversations(db)
        db.execute("PRAGMA user_version=3")
    with sqlite3.connect(root / (key + ".db")) as db:
        for table in (
            "episodes",
            "interests",
            "learning_receipts",
            "language_profiles",
            "conversations",
            "interpretations",
            "language_executions",
            "teaching_drafts",
            "source_profiles",
            "feeds",
            "feed_runs",
            "feed_items",
            "feed_controls",
            "coverage_transitions",
            "source_versions",
            "source_heads",
            "source_batches",
            "source_jobs",
            "source_claims",
            "source_episodes",
            "source_support",
            "source_revalidations",
        ):
            db.execute("DROP TABLE " + table)
        db.execute("ALTER TABLE attempts DROP COLUMN revision")
        db.execute("ALTER TABLE requests DROP COLUMN initial_revision")
        from tests.migration_support import remove_conversations

        remove_conversations(db)
        db.execute("PRAGMA user_version=3")
    rt = Runtime(cfg, start_scheduler=False)
    try:
        restored = rt.store.request(key, req["request_id"])
        assert restored["result"] == saved["result"]
        assert restored["attempts"] == saved["attempts"]
        assert restored["initial_revision_id"] == saved["revision_id"]
    finally:
        rt.close()
