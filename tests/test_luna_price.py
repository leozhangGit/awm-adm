"""Audited Luna bounds, new consent and simulated transport; no live key or HTTP."""

from uuid import uuid4

import pytest

from awm_adm.allowances.pricing import PURPOSES, amount, check_wire, profile
from awm_adm.config import AppConfig
from awm_adm.providers.wire import make_wire, specification
from awm_adm.runtime.protocol import RuntimeFault, dumps, loads

from .test_application import app_runtime as app_runtime
from .test_application import execute
from .test_ask import proposal
from .test_conversations import conversation, decision, message
from .test_learning_service import dispatch
from .test_learning_service import rig as rig
from .test_provider_transports import raw, response

PROFILE = "openai-5.6-luna-context/2026-11-09"
RATES = {
    "bound_profile": PROFILE,
    "input_micro_usd_per_million": 500_000,
    "output_micro_usd_per_million": 1_800_000,
}


def setup_luna(rt, gateway, tmp_path, *, large=True):
    if large:
        cfg = rt.config.model_dump()
        cfg["learning"]["call"]["max_input_tokens"] = 1_050_000
        cfg["learning"]["episode"]["max_input_tokens"] = 3_150_000
        cfg["learning"]["quotas"].update(
            input_tokens_per_adm=15_750_000, input_tokens_installation=15_750_000
        )
        rt.config = AppConfig.model_validate(cfg)
        rt.learning.config = rt.config
    gateway.store.static_dir = tmp_path
    (tmp_path / "openai-key").write_text("authored-test-credential")
    calls = []

    def transport(*args):
        calls.append(args)
        reply = response("openai", model="gpt-5.6-luna")
        reply["output"][0]["content"][0]["text"] = dumps(proposal("capabilities")).decode()
        return 200, raw(reply)

    gateway.transport = transport
    rt.learning.configure(
        {"expected_generation": rt.learning.settings()["generation"], "remote_calls_enabled": True}
    )
    conn = rt.learning.save_connection(
        {
            "idempotency_key": str(uuid4()),
            "name": "Simulated Luna",
            "provider": "openai",
            "model": "gpt-5.6-luna",
            "enabled": True,
            "credential_mode": "static",
            "purposes": sorted(PURPOSES),
        }
    )
    gateway.synchronize()
    gateway.synchronize()
    conn = rt.learning.connection(conn["id"])
    f = rt.learning.allowances
    f.configure(
        {
            "expected_generation": 0,
            "enabled": True,
            "total_micro_usd": 7_000_000,
            "interaction_micro_usd": 3_500_000,
            "learning_micro_usd": 3_500_000,
        }
    )
    options = f.price_options(conn["id"])
    assert options["items"][0]["bound_profile"] == PROFILE
    price = f.save_price(
        {
            "idempotency_key": str(uuid4()),
            "connection_id": conn["id"],
            "connection_version": conn["version"],
            "configuration_digest": conn["configuration_digest"],
            **RATES,
            "valid_until_ms": f.now() + 3600000,
        }
    )
    return conn, price, calls


def fund_chat(rt, key, price, purpose="ask", *, narrate=False):
    s = rt.conversations
    cid = conversation(rt, key, "teach" if purpose == "teach" else "ask")
    s.setup(
        key,
        cid,
        {
            "idempotency_key": str(uuid4()),
            "context": s.context(key),
            "price_id": price["id"],
            "purpose": purpose,
            "narrate_results": narrate,
        },
    )
    q = s.get(key, cid)["questions"][0]
    s.message(key, cid, message(rt, key, cid, "$3.50", reply_to=q["id"]))
    p = s.get(key, cid)["proposals"][0]
    assert p["payload"]["call_input_bound"] == 1_050_000
    assert p["payload"]["max_input_tokens"] == 6_300_000
    assert s.decide(key, p["id"], decision(p), "owner")["status"] == "accepted"
    return cid


@pytest.mark.parametrize(
    "changes", [{"input_micro_usd_per_million": 499_999}, {"output_micro_usd_per_million": 1_799_999}]
)
def test_luna_long_context_and_cache_write_rates_cannot_be_understated(changes):
    with pytest.raises(RuntimeFault, match="No verified"):
        profile({**RATES, **changes}, {"provider": "openai", "model": "gpt-5.6-luna"})


def test_luna_profile_covers_full_context_and_excludes_extra_billing():
    c = {"provider": "openai", "model": "gpt-5.6-luna", "capabilities": ["json_schema"]}
    bound = profile(RATES, c)
    assert bound["input_bound"] == 1_050_000 and not bound["synthetic"]
    assert amount(1_050_000, 8192, RATES) == 539746
    wire, _ = make_wire(c, specification(connection_test=True), 8192)
    check_wire(wire, c, bound, 8192)
    for key, value in (("prompt_cache_options", {"ttl": "12h"}), ("tools", []), ("service_tier", "priority")):
        with pytest.raises(RuntimeFault, match="without tools"):
            check_wire(dumps({**loads(wire), key: value}), c, bound, 8192)
    with pytest.raises(RuntimeFault, match="No verified"):
        profile(RATES, {**c, "model": "unreviewed-alias"})


@pytest.mark.parametrize("prior_consent,large", [(False, True), (True, True), (False, False)])
def test_ask_uses_only_reviewed_bound_and_keeps_operator_limits(rig, tmp_path, prior_consent, large):
    rt, gw = rig
    _, price, calls = setup_luna(rt, gw, tmp_path, large=large)
    key = rt.create("Luna scope")["id"]
    cid = fund_chat(rt, key, price)
    if prior_consent:
        with rt.store.db(key) as db, rt.store.transaction(db):
            conv = loads(db.execute("SELECT body FROM chat_conversations WHERE id=?", (cid,)).fetchone()[0])
            conv["preferences"].pop("call_input_bound")
            db.execute("UPDATE chat_conversations SET body=? WHERE id=?", (dumps(conv), cid))
    rt.conversations.message(key, cid, message(rt, key, cid, "What can this model do?"))
    rt.conversations.tick()
    work = rt.conversations.details(key, cid)["work"][-1]
    if prior_consent or not large:
        assert work["status"] == "failed" and not calls
        assert rt.learning.usage()["calls"] == 0
        return
    assert work["status"] == "awaiting_provider"
    assert rt.learning.allowances.view(work["preferences"]["allowance_id"])["reserved_micro_usd"] == 532373
    dispatch(rt, gw)
    rt.conversations.tick()
    done = execute(rt, key)
    assert done["status"] == "succeeded"
    rt.conversations.tick()
    assert len(calls) == 1 and rt.learning.usage()["calls"] == 1
    assert rt.learning.allowances.view(work["preferences"]["allowance_id"])["settled_micro_usd"] == amount(
        11, 4, RATES
    )
