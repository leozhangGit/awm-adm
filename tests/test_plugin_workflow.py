"""Bundled connector against actual public HTTP handlers and local checked workflows."""

import json

import pytest
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


def test_capacity_failure_then_explicit_retry_preserves_receipt_and_creates_once(app_runtime, tmp_path):
    from tests.test_lifecycle import delete_input, finish

    rt = app_runtime
    rt.store.limits = rt.store.limits.model_copy(update={"max_adms": 1})
    existing = rt.create("Existing model")["id"]
    c, root = connector(rt, tmp_path / "project", tmp_path / "private")
    first = c.project(root)
    assert first["state"] == "creating"
    assert rt.coordinator.run_operation()
    status = c.status(root)
    assert status["state"] == "creation_failed"
    assert status["creation_pending"] is False
    assert status["retry_new_creation"] is True
    operation = status["creation"]["operation_id"]
    assert status["creation"]["error"]["details"]["reason"] == "model_limit_reached"
    finish(rt, rt.lifecycle.request(existing, delete_input(rt, existing))["operation_id"])
    # Freeing capacity alone never resets the old operation or creates new work.
    assert c.project(root)["state"] == "creation_failed"
    fresh = c.project(root, retry_creation=operation)
    assert fresh["operation_id"] != operation
    assert rt.coordinator.run_operation()
    bound = c.project(root, retry_creation=operation)
    assert bound["state"] == "ready"
    assert bound["model"]["mode"] == "backward"
    assert c.project(root, retry_creation=operation)["model"]["id"] == bound["model"]["id"]
    assert len(rt.store.list()) == 1
    assert rt.coordinator.operation_info(operation)["status"] == "failed"
    assert rt.learning.usage()["calls"] == 0


@pytest.mark.parametrize(
    "evidence",
    [
        "Source: https://example.org/instrument/report, section 2. "
        "The publisher explicitly labels this reading in µm. "
        "This is a sourced report, not an independent measurement.",
        "Source: https://example.org/instrument/manual, revision C, section 4. "
        "The declared scale is 2 µm per tick. Inference: the reported 7 ticks "
        "correspond to 14 µm (7 × 2), assuming the report's instrument uses revision C. "
        "That revision is identified in the supplied report. Preserve the raw reading "
        "and this derived value separately; the manual does not report the measurement.",
    ],
    ids=["sourced-fact", "labeled-derivation"],
)
def test_connector_researched_clarification_preserves_originals_and_provenance(rig, tmp_path, evidence):
    """Recorded boundary check, not an evaluation of autonomous research quality."""
    rt, gw = rig
    key = rt.create("Research continuation")["id"]
    recorded(rt, gw, {})
    c, root = connector(rt, tmp_path / "project", tmp_path / "private")
    c.project(root, model_id=key)
    before = rt.store.info(key)
    original = "Retain the instrument's reported reading of 7, from report revision C."
    first = c.teach(root, text=original, operation="observation")
    assert rt.conversations.teaching.tick()
    respond(rt, {"status": "needs_clarification", "message": "What unit applies?", "plan_json": None})
    assert c.work(root, work_id="observation")["state"] == "needs_input"
    prior = rt.conversations.teaching.get(key, first["interaction_id"])

    clarified = c.teach(root, text=evidence, operation="research", reply_to="observation")
    task = rt.conversations.teaching.get(key, clarified["interaction_id"])
    assert task["previous_task_id"] == first["interaction_id"]
    assert [i["text"] for i in task["inputs"]] == [original, evidence]
    assert task["material_manifest"]["lineage_id"] == first["interaction_id"]
    assert task["material_manifest"]["entries"][0] == prior["material_manifest"]["entries"][0]
    assert task["material_manifest"]["entries"][1]["byte_count"] == len(evidence.encode())

    # Reopening the connector and recovering the same intent must not create a
    # third message or reinterpret the evidence as already accepted knowledge.
    restored = Connector(c.client, Journal(tmp_path / "private"))
    again = restored.teach(root, text=evidence, operation="research", reply_to="observation")
    assert again["interaction_id"] == clarified["interaction_id"]
    assert again["admissions"] == []
    assert (
        rt.conversations.teaching.get(key, again["interaction_id"])["material_manifest"]
        == task["material_manifest"]
    )
    assert rt.learning.usage()["calls"] == 1
    assert rt.store.info(key)["revision_id"] == before["revision_id"]
    assert rt.store.info(key)["mode"] == before["mode"] == "backward"


def test_connector_preparation_failure_retains_diagnostic_without_clarification_loop(rig, tmp_path):
    from tests.test_teaching_materials import facts_reply

    rt, gw = rig
    key = rt.create("Connector source preparation")["id"]
    recorded(rt, gw, {})
    c, root = connector(rt, tmp_path / "project", tmp_path / "private")
    c.project(root, model_id=key)
    item = c.teach(root, text="Retain this supplied observation.", operation="facts")
    uid = item["interaction_id"]
    assert rt.conversations.teaching.tick()
    task = rt.conversations.teaching.get(key, uid)
    respond(rt, facts_reply(task, ["invented-source-reference"]))
    final = c.work(root, work_id="facts")
    assert final["state"] == "failed"
    assert final["failure_diagnostics"]["code"] == "unknown_material_reference"
    assert final["admissions"] == []
    calls = rt.learning.usage()["calls"]
    assert c.work(root, work_id="facts")["interaction_id"] == uid
    assert rt.learning.usage()["calls"] == calls == 1
    with rt.store.db(key) as db:
        assert db.execute("SELECT count(*) FROM chat_questions").fetchone()[0] == 0


def test_connector_preserves_checked_historical_unit(rig, tmp_path):
    from tests.test_ask_history import command
    from tests.test_sources import ingest, install, project

    rt, gw = rig
    key = rt.create("Connector quantities")["id"]
    install(rt, key)
    assert project(rt, key, ingest(rt, key))["status"] == "accepted"
    recorded(rt, gw, proposal(command()))
    c, root = connector(rt, tmp_path / "project", tmp_path / "private")
    c.project(root, model_id=key)
    item = c.ask(root, text="What was recorded?", operation="units")
    assert rt.conversations.ask.tick()
    dispatch(rt, gw)
    assert rt.conversations.ask.tick()
    execute(rt, key)
    assert rt.conversations.ask.tick()
    narration(rt, work(rt, key, item["interaction_id"]), explanation="The recorded capacity was 10 places.")
    result = c.work(root, work_id="units")
    assert result["checked_outcome"]["value_metadata"]["unit"] == "places"
    assert result["summary"].startswith("Model answer: 10 places.")
    assert result["explanation"] == "The recorded capacity was 10 places."
    assert rt.learning.usage()["calls"] == 2


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
