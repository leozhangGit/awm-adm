"""Bundled connector against actual public HTTP handlers and local checked workflows."""

import json

from awm_adm_plugin import client as module
from awm_adm_plugin.connector import Connector
from awm_adm_plugin.journal import Journal

from tests.interaction_support import definition, narration, plan, proposal, reply, respond
from tests.test_application import app_runtime as app_runtime
from tests.test_application import client, execute, tank
from tests.test_direct_ask import recorded, work
from tests.test_direct_teach import has_ready, pump
from tests.test_learning_service import dispatch
from tests.test_learning_service import rig as rig


def connector(rt, project, private):
    # The exported plugin has no dependency on service internals. This test adapter
    # supplies real ASGI HTTP rather than a live listening port.
    class HTTP(module.Client):
        def _request(self, method, path, body=None, revision=None):
            with client(rt) as http:
                response = http.request(
                    method, "/api/v1" + path, json=body, headers={"If-Match": revision} if revision else {}
                )
                data = response.json()
                if response.status_code >= 400:
                    raise module.Problem(data["code"], data["message"])
                return data

    project.mkdir()
    return Connector(HTTP(), Journal(private)), str(project)


def test_connector_ask_checks_real_result_and_reuses_original_request(rig, tmp_path):
    rt, gw = rig
    key = tank(rt)
    recorded(rt, gw, proposal('plan tanks to tanks.four_litres from {"left":0,"right":0}'))
    c, root = connector(rt, tmp_path / "project", tmp_path / "private")
    c.project(root, model_id=key)
    item = c.ask(root, text="How can I get four litres?", operation="one-question")
    uid = item["interaction_id"]
    assert rt.conversations.ask.tick()
    dispatch(rt, gw)
    assert rt.conversations.ask.tick()
    execute(rt, key)
    rt.conversations.ask.tick()
    narration(rt, work(rt, key, uid))
    final = c.work(root, work_id="one-question")
    assert final["checked_outcome"]["status"] == "succeeded"
    assert final["request_binding"]["result_id"] == final["checked_outcome"]["result_id"]
    assert final["outcome_matches_current_model"] is True
    calls = rt.learning.usage()["calls"]
    assert c.ask(root, text="How can I get four litres?", operation="one-question")["interaction_id"] == uid
    assert rt.learning.usage()["calls"] == calls


def test_connector_teach_runs_real_admission_and_retains_checked_references(rig, tmp_path):
    rt, gw = rig
    key = rt.create("Connector teaching")["id"]
    recorded(rt, gw, {})
    c, root = connector(rt, tmp_path / "project", tmp_path / "private")
    c.project(root, model_id=key)
    item = c.teach(
        root, text="Teach doubling whole numbers 0 through 5, with outputs 0 through 10.", operation="learn"
    )
    uid = item["interaction_id"]
    assert rt.conversations.teaching.tick()
    respond(
        rt,
        {
            "status": "ready",
            "message": "The scope is clear.",
            "plan_json": json.dumps(plan([work(rt, key, uid)["turn_id"]])),
        },
    )
    pump(rt, key, uid, lambda _: has_ready(rt))
    reply(rt, definition())
    task = pump(rt, key, uid, lambda t: t["execution"]["phase"] == "narration")
    run = task["execution"]
    reply(
        rt,
        {
            "packet_digest": run["packet_digest"],
            "accepted_ids": run["summary"]["accepted_ids"],
            "unresolved_ids": [],
            "explanation": "The doubling rule is ready.",
            "authority": "explanation_only",
        },
    )
    pump(rt, key, uid, lambda t: t["status"] == "succeeded")
    final = c.work(root, work_id="learn")
    assert final["state"] == "succeeded"
    assert final["admissions"][0]["classification"] == "accepted"
    assert final["admissions"][0]["accepted_revision"] == rt.store.info(key)["revision_id"]
    assert (
        c.work(root)["items"][0]["accepted_references"][0]["accepted_revision"]
        == rt.store.info(key)["revision_id"]
    )
    page = c.work(root, query="double")["knowledge"]
    assert page["items"]


def test_connector_revision_uses_real_receipt_precedence_and_explicit_mode(rig, tmp_path):
    from tests.ported.provider_fixtures import wire_expression

    rt, gw = rig
    key = rt.create("Revision fixture")["id"]
    recorded(rt, gw, {})
    c, root = connector(rt, tmp_path / "project", tmp_path / "private")
    c.project(root, model_id=key)

    def teach(identity, replacement=False):
        item = c.teach(
            root,
            text="Revise the existing math.double rule to n + 1."
            if replacement
            else "Teach doubling whole numbers 0 through 5, with outputs 0 through 10.",
            operation=identity,
        )
        uid = item["interaction_id"]
        assert rt.conversations.teaching.tick()
        preparation_plan = plan([work(rt, key, uid)["turn_id"]])
        if replacement:
            preparation_plan["kind"] = preparation_plan["children"][0]["kind"] = "correction"
            preparation_plan["children"][0]["objective"] = "Replace the existing function with n + 1."
        respond(
            rt,
            {
                "status": "ready",
                "message": "Fixture scope",
                "plan_json": json.dumps(preparation_plan),
            },
        )
        pump(rt, key, uid, lambda _: has_ready(rt))
        proposal = definition()
        if replacement:
            proposal["result"]["definitions"]["math.double"]["body"] = wire_expression(
                {"op": "add", "args": [{"op": "var", "name": "n"}, {"op": "literal", "value": 1}]}
            )
        reply(rt, proposal)
        task = pump(rt, key, uid, lambda t: t["execution"]["phase"] == "narration")
        run = task["execution"]
        reply(
            rt,
            {
                "packet_digest": run["packet_digest"],
                "accepted_ids": run["summary"]["accepted_ids"],
                "unresolved_ids": run["summary"]["unresolved_ids"],
                "explanation": "Fixture outcome",
                "authority": "explanation_only",
            },
        )
        pump(rt, key, uid, lambda t: t["execution"].get("delivered"))
        return c.work(root, work_id=identity)

    original = teach("original")
    assert original["admissions"][0]["classification"] == "accepted"
    revision = rt.store.info(key)["revision_id"]
    rejected = teach("backward-revision", True)
    assert rejected["admissions"][0]["classification"] == "preservation_conflict"
    assert rt.store.info(key)["revision_id"] == revision
    changed = c.set_mode(root, mode="forward", operation="forward", user_requested=True)
    assert changed["model"]["mode"] == "forward"
    accepted = teach("fresh-forward-revision", True)
    assert accepted["admissions"][0]["classification"] == "accepted"
    assert "math.double" in accepted["admissions"][0]["effects"]["replaced"]
    assert c.status(root)["model"]["mode"] == "forward"
    c.set_mode(root, mode="backward", operation="backward", user_requested=True)
    assert c.status(root)["model"]["mode"] == "backward"
