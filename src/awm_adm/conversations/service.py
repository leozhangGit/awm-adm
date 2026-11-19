"""Bounded conversation coordinator. Owner decisions, never provider prose, carry authority.

Immutable turns live with the ADM. Direct submissions carry their scope and pinned
connection. Historical records remain readable; retired setup intents never replay.
"""

import threading
from uuid import uuid4

from ..learning.service import fault
from ..runtime.protocol import RuntimeFault, dumps, loads
from .models import (
    Context,
)

PENDING = {"queued", "awaiting_provider", "awaiting_local", "awaiting_narration"}


class Conversations:
    def __init__(self, runtime, *, start=True):
        self.runtime, self.store, self.learning = runtime, runtime.store, runtime.learning
        self.finance = self.learning.allowances
        self.stop, self.wake = threading.Event(), threading.Event()
        self.thread = None
        self.position = 0
        from .ask import Ask

        self.ask = Ask(self)
        from ..teaching.service import Teaching

        self.teaching = Teaching(self)
        from ..intake.service import Intake

        self.intake = Intake(self)
        for model in self.store.list():
            if model["status"] != "ready":
                continue
            key = model["id"]
            with self.store.db(key) as db:
                intents = [
                    loads(r[0]) for r in db.execute("SELECT body FROM chat_decisions WHERE status='applying'")
                ]
                pending = [
                    loads(r[0])
                    for r in db.execute(
                        "SELECT body FROM chat_work WHERE status IN ('queued','awaiting_provider','awaiting_local','awaiting_narration')"
                    )
                ]
            self.teaching.execution.recover(key)
            for decision in intents:
                # Retired setup/financial intents never grant new authority during recovery.
                with self.store.db(key) as db:
                    decision["status"] = "stale"
                    db.execute(
                        "UPDATE chat_decisions SET status='stale',body=? WHERE id=?",
                        (dumps(decision), decision["id"]),
                    )
            for work in pending:
                if work.get("flow") == "ask" and self.ask.recover(key, work):
                    continue
                if work.get("flow") == "teach":
                    self.teaching.stop(key, work, "interrupted", "app_restarted")
                self._finish(
                    key,
                    work,
                    "interrupted",
                    "The app restarted. This exchange was stopped; no provider call will be repeated automatically.",
                )
        if start:
            self.start_worker()

    def start_worker(self):
        """Runtime publishes the service before resumed tasks can dispatch through it."""
        if self.thread is None:
            self.thread = threading.Thread(target=self.loop, name="adm-conversations", daemon=True)
            self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=5)

    def now(self):
        return int(self.learning.now() * 1000)

    def context(self, key):
        with self.store.lock:
            info = self.store.info(key)
            return Context(
                adm_id=key,
                revision_id=info["revision_id"],
                theory_root=info["theory_version"],
                support_root=info["support_root"],
                policy_epoch=info["policy_epoch"],
                vocabulary_generation=self.runtime.language.vocabulary(key)["generation"],
                source_policy_generation=info.get("source_policy_generation", 0),
            ).model_dump()

    def _current(self, key, context):
        if self.store.info(key)["archived"] or context != self.context(key):
            fault("stale_context", "Conversation context changed")

    def _authority(self):
        with self.store.db() as db:
            row = db.execute("SELECT generation FROM administrator WHERE id=1").fetchone()
        return row[0] if row else 0

    @staticmethod
    def _one(db, table, uid):
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (uid,)).fetchone()
        if row is None:
            fault("not_found", "Conversation resource not found in this ADM")
        return row

    def _conversation(self, db, uid):
        return loads(self._one(db, "chat_conversations", uid)["body"])

    def _space(self, db, cid, addition=4096):
        count, size = db.execute(
            "SELECT count(*),COALESCE(sum(length(body)),0) FROM chat_turns WHERE conversation=?", (cid,)
        ).fetchone()
        # Reserve room for the owner's turn, its response and terminal diagnostics.
        if count >= 196 or size + addition + 16384 > 1_048_576:
            fault("quota_exceeded", "This exchange has reached its storage limit; send a fresh request")
        retained = db.execute("SELECT count(*) FROM chat_inputs").fetchone()[0]
        if retained >= self.store.limits.queue_items_per_adm:
            fault("quota_exceeded", "Retained conversation input limit reached")
        self.store.capacity(addition + 32768)

    def _turn(self, db, key, conversation, author, text, *, context=None, attachments=()):
        uid = str(uuid4())
        seq = db.execute(
            "INSERT INTO chat_turns(id,conversation,body) VALUES(?,?,?)", (uid, conversation["id"], b"{}")
        ).lastrowid
        value = {
            "profile": "awm-adm-v3-turn/0.1",
            "id": uid,
            "conversation_id": conversation["id"],
            "channel": conversation["channel"],
            "author": author,
            "sequence": seq,
            "context": context or self.context(key),
            "text": text,
            "attachment_ids": list(attachments),
            "created_at_ms": self.now(),
        }
        db.execute("UPDATE chat_turns SET body=? WHERE id=?", (dumps(value), uid))
        self.store.emit(db, key, "conversation.turn", uid, data={"conversation_id": conversation["id"]})
        return value

    def listing(self, key, channel, after=0, limit=20):
        self.store.info(key)
        with self.store.db(key) as db:
            rows = db.execute(
                "SELECT * FROM chat_conversations WHERE seq>? ORDER BY seq LIMIT 100", (after,)
            ).fetchall()
            selected = [r for r in rows if loads(r["body"])["channel"] == channel][:limit]
        return {
            "items": [loads(r["body"]) for r in selected],
            "next_cursor": selected[-1]["seq"] if selected else after,
        }

    def get(self, key, uid, after=0, limit=20):
        with self.store.db(key) as db:
            record = self._conversation(db, uid)
            rows = db.execute(
                "SELECT seq,body FROM chat_turns WHERE conversation=? AND seq>? ORDER BY seq LIMIT ?",
                (uid, after, limit),
            ).fetchall()
            questions = [
                {**loads(r["body"]), "status": r["status"]}
                for r in db.execute(
                    "SELECT * FROM chat_questions WHERE conversation=? AND status='pending'", (uid,)
                )
            ]
            proposals = [
                {**loads(r["body"]), "status": r["status"]}
                for r in db.execute(
                    "SELECT * FROM chat_proposals WHERE conversation=? AND status IN ('pending','applying')",
                    (uid,),
                )
            ]
            work = [
                loads(r[0])
                for r in db.execute(
                    "SELECT body FROM chat_work WHERE conversation=? ORDER BY seq DESC LIMIT 20", (uid,)
                )
            ]
        current_context = self.context(key)
        stale_proposals = [
            p for p in proposals if p["expires_at_ms"] <= self.now() or p["context"] != current_context
        ]
        proposals = [p for p in proposals if p not in stale_proposals]
        for item in work:
            if item.get("grant_id"):
                grant = self.learning.grant_view(item["grant_id"])
                item["dispatch_status"] = grant["status"]
        from . import readiness

        issues = readiness.conversation(self, record)
        ready = bool((record.get("preferences") or {}).get("direct")) and not issues
        return {
            **record,
            "context": self.context(key),
            "items": [loads(r["body"]) for r in rows],
            "next_cursor": rows[-1]["seq"] if rows else after,
            "has_more": len(rows) == limit,
            "questions": questions,
            "proposals": proposals,
            "stale_proposal_count": len(stale_proposals),
            "readiness_issues": issues,
            "work": [
                {
                    k: v
                    for k, v in w.items()
                    if k
                    in {
                        "id",
                        "flow",
                        "status",
                        "local_status",
                        "context",
                        "turn_id",
                        "request_id",
                        "presentation_id",
                        "grant_id",
                        "dispatch_status",
                        "failure_code",
                        "created_at_ms",
                        "finished_at_ms",
                    }
                }
                for w in work
            ],
            "presentations": self.ask.summaries(key, uid),
            "tasks": self.teaching.listing(key, limit=20, cid=uid)["items"],
            "readiness": (
                "ready_for_ask"
                if (record.get("preferences") or {}).get("purpose") == "ask"
                else "ready_for_teaching"
                if (record.get("preferences") or {}).get("purpose") == "teach"
                else "ready_for_clarification"
            )
            if ready
            else "historical",
            "availability": {
                "clarification": True,
                "automatic_ask": True,
                "teaching_tasks": True,
                "teaching_execution": True,
                "source_upload": False,
            },
            "legacy_history_path": f"/api/v1/adms/{key}/interpretation-sessions",
        }

    def _question(self, db, key, conv, text, context, kind, data, depth=0):
        turn = self._turn(db, key, conv, "assistant", text, context=context)
        q = {
            "id": str(uuid4()),
            "conversation_id": conv["id"],
            "turn_id": turn["id"],
            "context": context,
            "kind": kind,
            "question": text,
            "data": data,
            "depth": depth,
            "expires_at_ms": None,
        }
        db.execute("INSERT INTO chat_questions VALUES(?,?,?,?)", (q["id"], conv["id"], "pending", dumps(q)))
        return q

    def grant_valid(self, body):
        key, uid = body["adm"], body["conversation_work_id"]
        with self.store.db(key) as db:
            work = loads(self._one(db, "chat_work", uid)["body"])
            conv = self._conversation(db, work["conversation_id"])
        self._current(key, work["context"])
        if not work["preferences"].get("direct"):
            fault("stale_context", "Historical work cannot dispatch; submit a new Ask or Teach message")
        self.runtime.interactions.connection_for(
            work,
            body.get("purpose")
            or ("task_preparation" if work.get("flow") == "teach" else "ask_interpretation"),
        )
        if work.get("flow") == "teach":
            task = self.teaching.get(key, work["preferences"]["task_id"])
            if (
                task["status"] != "preparing"
                or task["context"] != work["context"]
                or body.get("purpose", "task_preparation") != "task_preparation"
            ):
                fault("stale_context", "Teaching preparation authority changed")
        elif body.get("purpose") == "task_preparation":
            fault("forbidden", "Task preparation needs Teach authority")
        if body.get("purpose") in {"ask_interpretation", "ask_narration"}:
            expected = (
                "ask_narration"
                if work["status"] in {"awaiting_local", "awaiting_narration"}
                else "ask_interpretation"
            )
            if (
                work.get("flow") != "ask"
                or work["preferences"].get("purpose") != "ask"
                or body["purpose"] != expected
            ):
                fault("forbidden", "Ask dispatch purpose changed")
            if expected == "ask_narration" and not work["preferences"].get("narrate_results"):
                fault("forbidden", "Result disclosure is not authorized")
        if (
            work["status"] not in PENDING
            or work["authority_generation"] != self._authority()
            or work["preferences"] != conv["preferences"]
            or self.now() >= work["deadline_ms"]
        ):
            fault("stale_context", "Conversation no longer authorizes this dispatch")

    def _save_work(self, db, key, work, event):
        db.execute(
            "UPDATE chat_work SET status=?,body=? WHERE id=?", (work["status"], dumps(work), work["id"])
        )
        self.store.emit(
            db,
            key,
            event,
            work["id"],
            data={"conversation_id": work["conversation_id"], "status": work["status"]},
        )

    def _finish(self, key, work, status, text, reply=None):
        with self.store.db(key) as db, self.store.transaction(db):
            current = loads(self._one(db, "chat_work", work["id"])["body"])
            if current["status"] not in PENDING:
                return
            conv = self._conversation(db, work["conversation_id"])
            work = {**work, "status": status, "finished_at_ms": self.now()}
            if reply and reply["kind"] == "clarification":
                q = self._question(
                    db, key, conv, reply["text"], work["context"], "provider", {}, work["depth"]
                )
                work["links"].append({"kind": "question", "id": q["id"]})
            elif reply:
                self._turn(db, key, conv, "assistant", reply["text"], context=work["context"])
            self._turn(db, key, conv, "system", text, context=work["context"])
            self._save_work(db, key, work, "conversation.completed")

    def tick(self):
        # Alternate lanes: a busy Ask conversation cannot starve preparation.
        self.position += 1
        flows = (self.ask, self.teaching, self.teaching.execution)
        offset = self.position % len(flows)
        flows = flows[offset:] + flows[:offset]
        if any(flow.tick() for flow in flows):
            return True
        return False

    def details(self, key, cid):
        with self.store.db(key) as db:
            conv = self._conversation(db, cid)
            turns = [
                loads(r[0])
                for r in db.execute(
                    "SELECT body FROM chat_turns WHERE conversation=? ORDER BY seq LIMIT 200", (cid,)
                )
            ]
            questions = [
                {**loads(r["body"]), "status": r["status"]}
                for r in db.execute("SELECT * FROM chat_questions WHERE conversation=?", (cid,))
            ]
            proposals = [
                {**loads(r["body"]), "status": r["status"]}
                for r in db.execute("SELECT * FROM chat_proposals WHERE conversation=?", (cid,))
            ]
            decisions = [
                loads(r[0])
                for r in db.execute(
                    "SELECT d.body FROM chat_decisions d JOIN chat_proposals p ON p.id=d.proposal WHERE p.conversation=?",
                    (cid,),
                )
            ]
            work = [
                loads(r[0])
                for r in db.execute("SELECT body FROM chat_work WHERE conversation=? ORDER BY seq", (cid,))
            ]
            attachments = [
                loads(self._one(db, "chat_attachments", aid)["body"])
                for aid in sorted({aid for t in turns for aid in t["attachment_ids"]})
            ]
        return {
            "conversation": conv,
            "turns": turns,
            "questions": questions,
            "proposals": proposals,
            "decisions": decisions,
            "work": work,
            "presentations": self.ask.summaries(key, cid),
            "tasks": [
                self.teaching.get(key, t["id"])
                for t in self.teaching.listing(key, limit=100, cid=cid)["items"]
            ],
            "attachments": attachments,
            "provider_usage": [
                self.learning.grant_view(gid)
                for w in work
                for gid in dict.fromkeys(
                    [link["id"] for link in w["links"] if link["kind"] == "provider_grant"]
                )
            ],
            "allowance": self.finance.view(conv["preferences"]["allowance_id"])
            if (conv.get("preferences") or {}).get("allowance_id")
            else None,
        }

    def loop(self):
        while not self.stop.is_set():
            try:
                progress = self.tick()
            except (RuntimeFault, ValueError):
                progress = False
            if not progress:
                self.wake.wait(0.25)
                self.wake.clear()
