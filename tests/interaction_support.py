"""Synthetic provider replies and ordinary interaction fixtures. No remote calls."""

from uuid import uuid4

from awm_adm.runtime.protocol import dumps, loads

from .ported.provider_fixtures import wire_expression
from .teaching_wire import assessed_reply, native_reply, selected_reply, shared_reply, temporal_reply

TEXT = "The site has capacity ten places from 2020 through the end of 2023."


def proposal(command=None, status="ready", clarification=None, assumptions=None):
    return {
        "status": status,
        "command": command,
        "clarification": clarification,
        "assumptions": assumptions or [],
    }


def narration(rt, work, **changes):
    value = work["packet"]
    reply = {
        "packet_digest": value["digest"],
        "outcome_digest": value["outcome_digest"],
        "status": value["outcome"]["status"],
        "claim_ids": ["outcome"],
        "support_ids": value["support_ids"],
        "explanation": "This is the model's local result within the stated scope.",
        "authority": "explanation_only",
        **changes,
    }
    job = rt.learning.claim()
    assert job["grant_id"] == work["grant_id"]
    rt.learning.authorize(job["grant_id"], job["lease"])
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {
            "status": "succeeded",
            "text": dumps(reply).decode(),
            "usage": {"input_tokens": 100, "output_tokens": 50},
        },
    )
    assert rt.conversations.tick()


def plan(turn_ids):
    return {
        "kind": "capability",
        "summary": "A bounded doubling function for whole numbers from zero to five.",
        "children": [
            {
                "kind": "capability",
                "objective": "Double a bounded number",
                "input_ids": turn_ids,
                "interfaces": {
                    "math.double": {
                        "kind": "function",
                        "params": {"n": {"kind": "int", "min": 0, "max": 5}},
                        "returns": {"kind": "int", "min": 0, "max": 10},
                    }
                },
            }
        ],
        "vocabulary": {"aliases": {"double": ["math.double"]}},
        "requirements": None,
    }


def respond(rt, reply):
    reply = native_reply(reply)
    job = rt.learning.claim()
    assert job is not None
    with rt.store.db() as db:
        grant = loads(db.execute("SELECT body FROM grants WHERE id=?", (job["grant_id"],)).fetchone()[0])
    version = grant["provenance"]["prompt_version"]
    if version in {
        "adm-teaching-preparation/8",
        "adm-teaching-preparation/9",
        "adm-teaching-preparation/10",
        "adm-teaching-preparation/11",
        "adm-teaching-preparation/12",
        "adm-teaching-preparation/14",
        "adm-teaching-preparation/15",
        "adm-teaching-preparation/16",
        "adm-teaching-preparation/17",
        "adm-teaching-preparation/22",
        "adm-teaching-preparation/23",
        "adm-teaching-preparation/20",
        "adm-teaching-preparation/21",
        "adm-teaching-preparation/18",
        "adm-teaching-preparation/19",
    }:
        task = rt.conversations.teaching.get(grant["adm"], grant["conversation_work_id"])
        convert = (
            temporal_reply
            if grant["provenance"]["prompt_version"].endswith(
                ("/10", "/11", "/12", "/14", "/16", "/18", "/20", "/22")
            )
            else shared_reply
            if grant["provenance"]["prompt_version"].endswith("/9")
            else selected_reply
        )
        version = grant["provenance"]["prompt_version"]
        if not version.endswith(("/15", "/17", "/19", "/21", "/23")):
            reply = convert(reply, task["material_manifest"])
        if version.endswith(("/14", "/15", "/16", "/17", "/18", "/19", "/20", "/21", "/22", "/23")):
            reply = assessed_reply(
                reply,
                [i["id"] for i in task["inputs"]],
                temporal=version.endswith(("/14", "/16", "/18", "/20", "/22")),
            )
    if version.endswith(("/22", "/23")):
        reply["profile"] = (
            "awm-adm-teaching-reply/8" if version.endswith("/22") else "awm-adm-teaching-reply/9"
        )
        for child in (reply.get("plan") or {}).get("children", []):
            child.setdefault("reuse_symbols", [])
    rt.learning.authorize(job["grant_id"], job["lease"])
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {
            "status": "succeeded",
            "text": dumps(reply).decode(),
            "usage": {"input_tokens": 100, "output_tokens": 200},
        },
    )
    assert rt.conversations.tick()


def material():
    return {
        "projection": {
            "namespace": "records",
            "entities": ["asset"],
            "predicates": [
                {"symbol": "records.capacity", "kind": "integer", "unit": "items", "minimum": 0, "maximum": 5}
            ],
            "cells": [
                {
                    "kind": "interval",
                    "effective_from": "2025-01-01T00:00:00Z",
                    "effective_to": "2026-01-01T00:00:00Z",
                    "granularity": "year",
                }
            ],
        },
        "sources": [
            {"source_id": "owner-note", "attribution": "Owner supplied note", "evidence_group": "owner"}
        ],
    }


def command(rt, key, uid, action, **kw):
    task = rt.conversations.teaching.get(key, uid)
    run = task.get("execution", {})
    body = {
        "idempotency_key": str(uuid4()),
        "context": rt.conversations.context(key),
        "specification_digest": task["specification_digest"],
        "expected_version": run.get("version", 0),
        "action": action,
        "review_digest": (run.get("review") or {}).get("digest"),
        **kw,
    }
    return rt.conversations.teaching.execution.command(key, uid, body, "owner")


def reply(rt, value):
    job = rt.learning.claim()
    assert job
    with rt.store.db() as db:
        grant = loads(db.execute("SELECT body FROM grants WHERE id=?", (job["grant_id"],)).fetchone()[0])
    version = grant["provenance"]["prompt_version"]
    if version in {
        "adm-source-extraction/3",
        "adm-source-extraction/4",
        "adm-source-extraction/6",
        "adm-source-extraction/6-context-1",
        "adm-source-extraction/7",
        "adm-source-extraction/7-context-1",
    }:
        from copy import deepcopy

        value = deepcopy(value)
        for c in value.get("claims", []):
            scope = c["temporal_scope"]
            if scope["kind"] in ("point", "interval"):
                scope["kind"] = "instant" if scope["kind"] == "point" else "validity"
                scope.pop("granularity", None)
                scope.update(precision="second", timezone_basis="UTC")
                c.update(
                    observed_time={
                        "kind": "unknown",
                        "effective_from": None,
                        "effective_to": None,
                        "precision": None,
                        "timezone_basis": None,
                    },
                    reported_time={
                        "kind": "unknown",
                        "effective_from": None,
                        "effective_to": None,
                        "precision": None,
                        "timezone_basis": None,
                    },
                    occurrence_id=None,
                )
    rt.learning.authorize(job["grant_id"], job["lease"])
    rt.learning.outcome(
        job["grant_id"],
        job["lease"],
        {
            "status": "succeeded",
            "text": dumps(value).decode(),
            "usage": {"input_tokens": 100, "output_tokens": 200},
        },
    )
    return job


def definition():
    return {
        "format": "adm-construction/1",
        "result": {
            "status": "draft",
            "definitions": {
                "math.double": {
                    "body": wire_expression(
                        {"op": "add", "args": [{"op": "var", "name": "n"}, {"op": "var", "name": "n"}]}
                    )
                }
            },
            "declarations": [],
            "discard": [],
            "retractions": [],
            "summary": "Authored doubling fixture",
        },
    }


def uploaded(rt, key, **kw):
    return rt.conversations.intake.upload(
        key,
        {
            "idempotency_key": str(uuid4()),
            "name": "history.md",
            "media_type": "text/markdown",
            "content": TEXT,
            "source_id": "records",
            **kw,
        },
    )
