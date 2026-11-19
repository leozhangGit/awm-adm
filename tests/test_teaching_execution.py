"""Automatic execution retains cancellation, publication and narration boundaries."""

import pytest

from .interaction_support import command, definition, reply
from .test_application import app_runtime as app_runtime
from .test_direct_teach import has_ready, preparation, pump, task
from .test_learning_service import rig as rig


def acquisition(rt, gw):
    key, uid = preparation(rt, gw)
    pump(rt, key, uid, lambda _: has_ready(rt))
    return key, uid


def test_pause_retains_ready_grant_and_resume_does_not_reacquire(rig):
    rt, gw = rig
    key, uid = acquisition(rt, gw)
    before = rt.learning.usage()
    command(rt, key, uid, "pause")
    assert rt.learning.claim() is None
    assert rt.learning.usage() == before
    command(rt, key, uid, "resume")
    reply(rt, definition())
    completed = pump(rt, key, uid, lambda t: t["execution"]["steps"][0]["status"] == "accepted")
    assert completed["execution"]["steps"][0]["revision_id"] == rt.store.info(key)["revision_id"]
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants WHERE episode IS NOT NULL").fetchone()[0] == 1


@pytest.mark.parametrize("change", ["cancel", "pause", "policy"])
def test_parent_change_during_admission_cannot_publish(rig, monkeypatch, change):
    rt, gw = rig
    key, uid = acquisition(rt, gw)
    before = rt.store.info(key)
    compute = rt.learning._compute
    raced_once = []

    def raced(*args, **kwargs):
        result = compute(*args, **kwargs)
        if args[2] == "learning_admit" and not raced_once:
            raced_once.append(True)
            if change == "policy":
                rt.store.change(key, rt.store.info(key)["policy_epoch"])
            else:
                command(rt, key, uid, change)
        return result

    monkeypatch.setattr(rt.learning, "_compute", raced)
    reply(rt, definition())
    for _ in range(12):
        rt.learning.tick()
        rt.conversations.tick()
    assert raced_once
    after = rt.store.info(key)
    assert after["theory_version"] == before["theory_version"]
    assert after["support_root"] == before["support_root"]
    assert task(rt, key, uid)["execution"]["steps"][0]["status"] != "accepted"


def test_invalid_candidate_stops_after_bounded_attempts_without_partial_publication(rig):
    rt, gw = rig
    key, uid = acquisition(rt, gw)
    before = rt.store.info(key)
    for attempt in range(2):
        bad = definition()
        bad["result"]["definitions"]["math.double"]["body"] = {"op": "literal", "value": 9999}
        reply(rt, bad)
        if attempt == 0:
            pump(rt, key, uid, lambda _: has_ready(rt))
        else:
            pump(rt, key, uid, lambda t: t["execution"]["steps"][0]["status"] == "unresolved")
    assert rt.store.info(key) == before
    with rt.store.db() as db:
        assert db.execute("SELECT count(*) FROM grants WHERE episode IS NOT NULL").fetchone()[0] == 2


def test_false_completion_summary_does_not_hide_accepted_knowledge(rig):
    rt, gw = rig
    key, uid = acquisition(rt, gw)
    reply(rt, definition())
    ready = pump(rt, key, uid, lambda t: bool(t["execution"].get("narration_grant_id")))
    run = ready["execution"]
    reply(
        rt,
        {
            "packet_digest": run["packet_digest"],
            "accepted_ids": [],
            "unresolved_ids": [],
            "explanation": "Everything failed",
            "authority": "explanation_only",
        },
    )
    done = pump(rt, key, uid, lambda t: bool(t["execution"].get("delivered")))
    assert done["status"] == "succeeded"
    assert done["execution"]["summary"]["accepted"]
    assert done["execution"]["narration_failure"] == "invalid_or_failed_narration"
    assert not rt.interactions.get(key, uid)["explanation"]


def test_stop_preparation_prevents_late_response_from_starting_learning(rig):

    from .test_direct_ask import recorded

    rt, gw = rig
    key = rt.create("Stopped preparation")["id"]
    recorded(rt, gw, {})
    item = rt.interactions.submit(key, "teach", {"text": "Teach doubling"})
    rt.conversations.teaching.tick()
    job = rt.learning.claim()
    rt.learning.authorize(job["grant_id"], job["lease"])
    stopped = rt.interactions.cancel(key, item["id"], "owner")
    assert stopped["status"] == "cancelled"
    assert rt.interactions.cancel(key, item["id"], "owner") == stopped
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {"status": "succeeded", "text": "{}", "usage": {"input_tokens": 10, "output_tokens": 10}},
    )
    assert not rt.conversations.teaching.tick()
    assert not rt.learning.episodes(key)
