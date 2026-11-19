"""Synthetic provider replies and ordinary interaction fixtures. No remote calls."""

from uuid import uuid4

from awm_adm.runtime.protocol import dumps

from .ported.provider_fixtures import wire_expression
from .teaching_wire import native_reply

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
