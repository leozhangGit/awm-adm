"""One visible model channel, with independently pinned durable exchanges underneath."""

from uuid import uuid4

from ..learning.service import fault, fingerprint
from ..runtime.protocol import dumps, loads
from .models import DirectMessage


class Interactions:
    def __init__(self, runtime):
        self.rt, self.store, self.s = runtime, runtime.store, runtime.conversations

    def submit(self, key, channel, source, *, origin="api", source_queue=False, expected_revision=None):
        body = DirectMessage.model_validate(source).model_dump()
        body["idempotency_key"] = body["idempotency_key"] or str(uuid4())
        if channel not in {"ask", "teach"}:
            fault("invalid_input", "Choose Ask or Teach")
        if channel == "ask" and body["attachments"]:
            fault("invalid_input", "Use Teach to supply material to the model")
        identity = fingerprint({"channel": channel, "input": body, "source_queue": source_queue})
        with self.store.lock:
            with self.store.db(key) as db:
                old = db.execute(
                    "SELECT id,digest FROM direct_interactions WHERE idem=?", (body["idempotency_key"],)
                ).fetchone()
            if old:
                if old["digest"] != identity:
                    fault("conflict", "This submission identity has different content")
                return self.get(key, old["id"])
            context = self.s.context(key)
            if expected_revision is not None and expected_revision != context["revision_id"]:
                fault("stale_context", "Model revision changed; retrieve current knowledge before submitting")
            self.s._current(key, context)
            conn = self.rt.learning.connection_manager.active(
                "ask_interpretation" if channel == "ask" else "task_preparation"
            )
            prefs = {
                "direct": True,
                "source_queue": source_queue,
                "purpose": channel,
                "connection_id": conn["id"],
                "connection_version": conn["version"],
                "connection_generation": self.rt.learning.settings()["generation"],
                "narrate_results": True,
                "historical_lookup": True,
                "snapshot_history": True,
            }
            uid, cid = str(uuid4()), str(uuid4())
            with self.store.db(key) as db, self.store.transaction(db):
                if (
                    db.execute("SELECT count(*) FROM direct_interactions").fetchone()[0]
                    >= self.store.limits.queue_items_per_adm
                ):
                    fault("resource_exhausted", "The model's retained interaction storage is full")
                selected, prior, question, result_links = [], None, None, []
                if body["reply_to"]:
                    prior = db.execute(
                        "SELECT * FROM direct_interactions WHERE id=?", (body["reply_to"],)
                    ).fetchone()
                    if not prior or prior["channel"] != channel:
                        fault(
                            "invalid_input",
                            "The reply must refer to an interaction in this model and channel",
                        )
                    previous = loads(self.s._one(db, "chat_work", prior["id"])["body"])
                    if previous["status"] in {
                        "queued",
                        "awaiting_provider",
                        "awaiting_local",
                        "awaiting_narration",
                    }:
                        fault(
                            "conflict",
                            "That interaction is still working; send an independent question or wait for its reply",
                        )
                    selected = [
                        *previous.get("selected_context", []),
                        {"id": previous["turn_id"], "text": previous["text"]},
                    ][-6:]
                    # Older words explain the reference; current accepted knowledge supplies premises.
                    while len(dumps(selected)) > 16384:
                        selected.pop(0)
                    row = db.execute(
                        "SELECT body FROM chat_questions WHERE conversation=? AND status='pending'",
                        (prior["conversation"],),
                    ).fetchone()
                    question = loads(row[0]) if row else None
                    if previous.get("request_id"):
                        result = db.execute(
                            "SELECT result_id FROM requests WHERE id=? AND status='succeeded'",
                            (previous["request_id"],),
                        ).fetchone()
                        if result and result[0]:
                            result_links.append({"kind": "result", "resource_id": result[0]})
                if channel == "teach":
                    prefs["task_id"] = uid
                conv = {
                    "id": cid,
                    "channel": channel,
                    "title": body["text"][:128] or "Supplied material",
                    "created_at_ms": self.s.now(),
                    "preferences": prefs,
                    "links": result_links,
                }
                db.execute(
                    "INSERT INTO chat_conversations(id,idem,digest,body) VALUES(?,?,?,?)",
                    (cid, "direct:" + uid, identity, dumps(conv)),
                )
                self.s._space(db, cid, len(dumps(body)))
                for aid in body["attachments"]:
                    self.s._one(db, "chat_attachments", aid)
                turn = self.s._turn(
                    db, key, conv, "owner", body["text"], context=context, attachments=body["attachments"]
                )
                work = {
                    "id": uid,
                    "flow": channel,
                    "conversation_id": cid,
                    "turn_id": turn["id"],
                    "context": context,
                    "selected_context": selected,
                    "question": question["question"] if question else None,
                    "pending_intent": question["data"]
                    if question and question["kind"] == "ask_intent"
                    else None,
                    "text": body["text"],
                    "preferences": prefs,
                    "authority_generation": self.s._authority(),
                    "status": "queued",
                    "grant_id": None,
                    "created_at_ms": self.s.now(),
                    "deadline_ms": self.s.now() + 300000,
                    "depth": question["depth"] + 1 if question else 0,
                    "links": [],
                }
                if work["depth"] >= 4:
                    fault("needs_specification", "Please restate the full request with the missing details")
                if channel == "teach":
                    self.s.teaching.direct_task(db, key, conv, work, turn, previous if prior else None)
                db.execute(
                    "INSERT INTO chat_work(id,conversation,status,body) VALUES(?,?,'queued',?)",
                    (uid, cid, dumps(work)),
                )
                db.execute(
                    "INSERT INTO direct_interactions(id,idem,digest,channel,conversation,origin,reply_to,created) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        uid,
                        body["idempotency_key"],
                        identity,
                        channel,
                        cid,
                        origin,
                        body["reply_to"],
                        self.rt.learning.now(),
                    ),
                )
                if question:
                    db.execute("UPDATE chat_questions SET status='answered' WHERE id=?", (question["id"],))
                self.store.emit(db, key, "conversation.queued", uid, data={"conversation_id": cid})
            self.s.wake.set()
        return self.get(key, uid)

    def get(self, key, uid):
        self.store.info(key)
        with self.store.db(key) as db:
            row = db.execute("SELECT * FROM direct_interactions WHERE id=?", (uid,)).fetchone()
            if not row:
                fault("not_found", "Interaction not found")
            work = loads(self.s._one(db, "chat_work", uid)["body"])
            turns = [
                loads(r[0])
                for r in db.execute(
                    "SELECT body FROM chat_turns WHERE conversation=? ORDER BY seq", (row["conversation"],)
                )
            ]
            presentation = db.execute("SELECT body FROM chat_presentations WHERE id=?", (uid,)).fetchone()
            task = db.execute("SELECT body FROM teaching_tasks WHERE id=?", (uid,)).fetchone()
            question = db.execute(
                "SELECT body FROM chat_questions WHERE conversation=? AND status='pending'",
                (row["conversation"],),
            ).fetchone()
        result = {
            "id": uid,
            "sequence": row["seq"],
            "idempotency_key": row["idem"],
            "channel": row["channel"],
            "origin": row["origin"],
            "reply_to": row["reply_to"],
            "created_at_ms": int(row["created"] * 1000),
            "status": work["status"],
            "text": work["text"],
            "reply": next((t["text"] for t in reversed(turns) if t["author"] != "owner"), None),
            "request_id": work.get("request_id"),
            "result_id": None,
            "outcome": None,
            "outcome_text": None,
            "explanation": None,
            "outcome_label": None,
            "failure_code": work.get("failure_code"),
        }
        if question:
            result["reply"] = loads(question[0])["question"]
        if work.get("local_outcome"):
            from ..conversations.presentation import readable

            result.update(
                outcome=work["local_outcome"],
                outcome_text=readable(work["local_outcome"]),
                result_id=work["local_outcome"].get("result_id"),
            )
        if presentation:
            value = loads(presentation[0])
            result.update(
                outcome=value["outcome"],
                outcome_text=value["outcome_text"],
                result_id=value["outcome"].get("result_id"),
            )
            if value["presentation"]["status"] == "ready":
                result["explanation"] = value["presentation"]["text"]
        if task:
            task = loads(task[0])
            result["status"] = task["status"]
            result["task_id"] = task["id"]
            result["failure_code"] = task.get("failure_code") or (task.get("execution") or {}).get("reason")
            result["teaching"] = (
                self.s.teaching.execution.view(task["execution"]) if task.get("execution") else None
            )
            run = task.get("execution") or {}
            if result["teaching"] is not None:
                from .admissions import admissions

                result["teaching"]["admissions"] = admissions(self.store, key, run)
            if run.get("delivered") and run.get("narration"):
                result["explanation"] = run["narration"]["explanation"]
                result["outcome_text"] = result["reply"]
            summary = run.get("summary") or {}
            if (
                run.get("delivered")
                and summary.get("status") == "succeeded"
                and summary.get("accepted")
                and not summary.get("unresolved")
                and not summary.get("followup")
                and summary.get("vocabulary") == "installed"
            ):
                count = len(summary["accepted"])
                result["outcome_label"] = f"Learned and saved · {count} " + (
                    "objective" if count == 1 else "objectives"
                )

        if task and run.get("delivered") and summary.get("status") == "succeeded":
            changes = summary.get("changes") or {}
            # Keep a concise checked diff visible even when the fluent explanation
            # or the normal success label would otherwise hide publication effects.
            if any(e["kind"] != "added" for e in changes.get("entries", [])) or not changes.get(
                "complete", True
            ):
                result["outcome_label"] = changes.get("text") or result.get("outcome_label")
                if self.store.info(key)["mode"] == "forward":
                    result["outcome_label"] = (
                        result["outcome_label"] or ""
                    ) + " Forward mode remains active until you explicitly request backward mode."

        if result["outcome"]:
            from ..conversations.presentation import outcome_label

            result["outcome_label"] = outcome_label(result["outcome"])

        return result

    def cancel(self, key, uid, principal):
        """Stop the exact exchange; accepted knowledge and saved results remain."""
        from ..teaching.execution import TERMINAL

        with self.store.lock:
            view = self.get(key, uid)
            with self.store.db(key) as db:
                work = loads(self.s._one(db, "chat_work", uid)["body"])
            if work["flow"] == "teach":
                task = self.s.teaching.get(key, uid)
                run = task.get("execution")
                if run and run["status"] not in TERMINAL:
                    self.s.teaching.execution.command(
                        key,
                        uid,
                        {
                            "idempotency_key": "stop-interaction:" + uid,
                            "specification_digest": task["specification_digest"],
                            "context": run["context"],
                            "expected_version": run["version"],
                            "action": "cancel",
                        },
                        principal,
                    )
                    return self.get(key, uid)
                if task["status"] in TERMINAL:
                    return view
                self.s.teaching.stop(key, work, "cancelled", "owner_cancelled")
            elif work.get("request_id"):
                if not work.get("local_outcome"):
                    self.store.cancel_request(key, work["request_id"])
                self.s.ask.complete(key, work, reason="owner_cancelled")
                return self.get(key, uid)
            self.s._finish(
                key,
                work,
                "cancelled",
                "Stopped. Accepted knowledge and completed results are retained. A provider call already dispatched may still return.",
            )
            return self.get(key, uid)

    def chat(self, key, channel, *, after=0, limit=20, direction="forward", before=None):
        self.store.info(key)
        if direction not in {"forward", "backward"} or (direction == "forward" and before is not None):
            fault("invalid_input", "Use backward pagination to load older exchanges")
        if direction == "backward" and after:
            fault("invalid_input", "Use before for backward pagination")
        with self.store.db(key) as db:
            if direction == "backward":
                rows = db.execute(
                    "SELECT seq,id FROM direct_interactions WHERE channel=? "
                    "AND (? IS NULL OR seq<?) ORDER BY seq DESC LIMIT ?",
                    (channel, before, before, limit + 1),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT seq,id FROM direct_interactions WHERE channel=? AND seq>? ORDER BY seq LIMIT ?",
                    (channel, after, limit + 1),
                ).fetchall()
        selected = rows[:limit]
        cursor = selected[-1]["seq"] if selected else (before or 0) if direction == "backward" else after
        if direction == "backward":
            selected = list(reversed(selected))
        return {
            "items": [self.get(key, row["id"]) for row in selected],
            "next_cursor": cursor,
            "has_more": len(rows) > limit,
        }

    def connection_for(self, work, purpose):
        prefs = work["preferences"]
        conn = self.rt.learning.connection_manager.active(purpose)
        if (conn["id"], conn["version"], self.rt.learning.settings()["generation"]) != (
            prefs["connection_id"],
            prefs["connection_version"],
            prefs["connection_generation"],
        ):
            fault("stale_context", "The connection changed during this interaction")
        return conn
