"""Durable interpretation and explicit consent, separate from theory admission."""

import base64
import sqlite3
import threading
from uuid import uuid4

from ..application.store import context_binding
from ..contracts import IntentDraft, Request
from ..learning.service import fault, fingerprint
from ..providers.wire import make_wire, provenance
from ..runtime.protocol import RuntimeFault, dumps, loads
from .models import (
    ConversationInput,
    ExecuteInput,
    InterpretationInput,
    TeachInput,
    Vocabulary,
    VocabularyInput,
)
from .parser import blocked
from .prompt import specification

PENDING = {"queued", "checking", "awaiting_provider"}
MAX_CONVERSATIONS = 100
MAX_TURNS = 100
MAX_CONTEXT_BYTES = 16384
TERMINAL_HEADROOM = 1024


class LanguageService:
    def __init__(self, runtime, *, start=True):
        self.runtime, self.store, self.learning = runtime, runtime.store, runtime.learning
        from ..runtime.supervisor import Supervisor

        self.supervisor = Supervisor(runtime.config.runtime.conversation_check_processes)
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.position = 0
        for row in self.store.list():
            if row["status"] == "ready":
                with self.store.db(row["id"]) as db:
                    for old in db.execute(
                        "SELECT data FROM interpretations WHERE status IN ('queued','checking','awaiting_provider')"
                    ).fetchall():
                        item = loads(old[0])
                        self._fail(row["id"], item, "app_restarted")
        if start:
            self.thread = threading.Thread(target=self.loop, name="adm-language", daemon=True)
            self.thread.start()

    def close(self):
        self.stop.set()
        self.supervisor.close()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=self.runtime.config.request.max_duration_ms / 1000 + 4)

    def vocabulary(self, key):
        self.store.info(key)
        with self.store.db(key) as db:
            row = db.execute("SELECT * FROM language_profiles ORDER BY generation DESC LIMIT 1").fetchone()
        return {
            "generation": row["generation"],
            "vocabulary": Vocabulary.model_validate(loads(row["data"])).model_dump(),
        }

    def _compute(self, key, revision, vocabulary, operation, **extra):
        pinned = self.store.revision(key, revision)
        with self.store.db(key) as db:
            results = [
                r[0]
                for r in db.execute(
                    "SELECT result_id FROM requests WHERE status='succeeded' ORDER BY seq DESC LIMIT 100"
                )
            ]
        return self.supervisor.run(
            {
                "operation": operation,
                "snapshot": pinned["snapshot"],
                "context": pinned["context"],
                "vocabulary": vocabulary,
                "result_ids": results,
                "limits": self.runtime.limits(),
                **extra,
            },
            cancel=self.stop,
        )

    def catalog(self, key):
        with self.store.lock:
            info, meta = self.store.info(key), self.vocabulary(key)
        value = self._compute(key, info["revision_id"], meta["vocabulary"], "language_catalog")
        return {
            **value["catalog"],
            "revision_id": info["revision_id"],
            "generation": meta["generation"],
            "context": context_binding(info),
            "limits": {
                "conversations": MAX_CONVERSATIONS,
                "turns_per_conversation": MAX_TURNS,
                "context_turns": 6,
                "context_bytes": MAX_CONTEXT_BYTES,
            },
        }

    def set_vocabulary(self, key, body):
        body = VocabularyInput.model_validate(body).model_dump()
        self._compute(key, body["expected_revision"], body["vocabulary"], "language_vocabulary")
        with self.store.db(key) as db, self.store.transaction(db):
            self._current(key, body["expected_revision"], body["expected_generation"])
            generation = body["expected_generation"] + 1
            if generation > self.store.limits.queue_items_per_adm:
                fault("quota_exceeded", "Vocabulary history allowance exhausted")
            self.store.capacity(len(dumps(body["vocabulary"])) + 4096)
            db.execute("INSERT INTO language_profiles VALUES(?,?)", (generation, dumps(body["vocabulary"])))
            self.store.emit(db, key, "language.vocabulary_changed", key, data={"generation": generation})
        self.wake.set()
        return self.vocabulary(key)

    def _current(self, key, revision, generation):
        info = self.store.info(key)
        if (
            info["archived"]
            or info["revision_id"] != revision
            or self.vocabulary(key)["generation"] != generation
        ):
            fault("stale_context", "Model or language vocabulary changed")
        return info

    def conversations(self, key):
        self.store.info(key)
        with self.store.db(key) as db:
            return [
                dict(r)
                for r in db.execute("SELECT id,title,created FROM conversations ORDER BY seq DESC LIMIT 100")
            ]

    def create_conversation(self, key, body):
        self.store.info(key)
        body = ConversationInput.model_validate(body).model_dump()
        with self.store.db(key) as db, self.store.transaction(db):
            old = db.execute(
                "SELECT * FROM conversations WHERE idem=?", (body["idempotency_key"],)
            ).fetchone()
            if old:
                if old["digest"] != fingerprint(body):
                    fault("conflict", "Conversation idempotency mismatch")
                return {"id": old["id"], "title": old["title"]}
            if self.store.info(key)["archived"]:
                fault("conflict", "Archived model")
            if db.execute("SELECT count(*) FROM conversations").fetchone()[0] >= MAX_CONVERSATIONS:
                fault("quota_exceeded", "Conversation allowance exhausted")
            uid = str(uuid4())
            self.store.capacity(4096)
            db.execute(
                "INSERT INTO conversations(id,idem,digest,title,created) VALUES(?,?,?,?,?)",
                (uid, body["idempotency_key"], fingerprint(body), body["title"], self.learning.now()),
            )
        return {"id": uid, "title": body["title"]}

    def conversation(self, key, uid):
        self.store.info(key)
        with self.store.db(key) as db:
            row = db.execute("SELECT id,title,created FROM conversations WHERE id=?", (uid,)).fetchone()
            if row is None:
                fault("not_found", "Conversation not found in this ADM")
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM interpretations WHERE conversation=? ORDER BY seq", (uid,)
                )
            ]
            teaching = [
                loads(r[0])
                for r in db.execute(
                    "SELECT data FROM teaching_drafts WHERE conversation=? ORDER BY seq", (uid,)
                )
            ]
        summaries = []
        for uid in ids:
            item = self._raw(key, uid)
            summaries.append(
                {
                    "id": uid,
                    "status": item["status"],
                    "utterance": item["body"]["utterance"],
                    "translator": item["body"]["translator"],
                    "created": item["created"],
                }
            )
        return {**dict(row), "interpretations": summaries, "teaching_drafts": teaching}

    def _room(self, db, conversation, addition):
        if not db.execute("SELECT 1 FROM conversations WHERE id=?", (conversation,)).fetchone():
            fault("not_found", "Conversation not found in this ADM")
        counts = sum(
            db.execute(f"SELECT count(*) FROM {table} WHERE conversation=?", (conversation,)).fetchone()[0]
            for table in ("interpretations", "teaching_drafts")
        )
        if counts >= MAX_TURNS:
            fault("quota_exceeded", "Conversation turn allowance exhausted; start a new conversation")
        count, size = db.execute(
            "SELECT count(*),COALESCE(sum(length(data)),0) FROM interpretations"
        ).fetchone()
        extra_count, extra_size = db.execute(
            "SELECT count(*),COALESCE(sum(length(data)),0) FROM teaching_drafts"
        ).fetchone()
        reserved = (
            TERMINAL_HEADROOM
            * db.execute(
                "SELECT count(*) FROM interpretations WHERE status NOT IN ('failed','cancelled')"
            ).fetchone()[0]
        )
        if (
            count + extra_count >= self.store.limits.queue_items_per_adm
            or size + extra_size + reserved + addition + TERMINAL_HEADROOM
            > self.store.limits.queue_bytes_per_adm
        ):
            fault("quota_exceeded", "Retained language allowance exhausted")
        self.store.capacity(addition + 4096)

    def get(self, key, uid):
        self.store.info(key)
        with self.store.db(key) as db:
            row = db.execute("SELECT data FROM interpretations WHERE id=?", (uid,)).fetchone()
            if row is None:
                fault("not_found", "Interpretation not found in this ADM")
            item = loads(row[0])
            executed = db.execute(
                "SELECT request FROM language_executions WHERE interpretation=?", (uid,)
            ).fetchone()
        item["request_id"] = executed[0] if executed else None
        item["usage"] = self.learning.grant_view(item["grant_id"]) if item["grant_id"] else None
        item["provider_failure"] = self.learning.provider_failure(item.get("grant_id"))
        item["stale"] = (
            self.store.info(key)["revision_id"] != item["revision_id"]
            or self.vocabulary(key)["generation"] != item["language_generation"]
        )
        if executed:
            item["request"] = self.store.request(key, executed[0])
        return item

    def _save(self, db, key, item):
        # Do not persist derived API views, request copies or credentials.
        raw = dumps(item)
        headroom = 0 if item["status"] in {"failed", "cancelled"} else TERMINAL_HEADROOM
        if len(raw) + headroom > 1_048_576:
            fault("quota_exceeded", "Interpretation exceeds retained byte allowance")
        self.store.capacity(len(raw) + 4096)
        size = db.execute(
            "SELECT COALESCE(sum(length(data)),0) FROM interpretations WHERE id<>?", (item["id"],)
        ).fetchone()[0]
        size += db.execute("SELECT COALESCE(sum(length(data)),0) FROM teaching_drafts").fetchone()[0]
        reserved = (
            TERMINAL_HEADROOM
            * db.execute(
                "SELECT count(*) FROM interpretations WHERE id<>? AND status NOT IN ('failed','cancelled')",
                (item["id"],),
            ).fetchone()[0]
        )
        if size + reserved + len(raw) + headroom > self.store.limits.queue_bytes_per_adm:
            fault("quota_exceeded", "Retained language byte allowance exhausted")
        db.execute("UPDATE interpretations SET status=?,data=? WHERE id=?", (item["status"], raw, item["id"]))
        self.store.emit(db, key, "interpretation.changed", item["id"], data={"status": item["status"]})

    def create(self, key, body, *, parent=None, revalidation=None):
        body = InterpretationInput.model_validate(body).model_dump()
        if body.get("allowance_id") is None:
            body.pop("allowance_id", None)
        identity = fingerprint({"body": body, "parent": parent, "revalidation": revalidation})
        with self.store.lock, self.store.db(key) as db, self.store.transaction(db):
            old = db.execute(
                "SELECT id,digest FROM interpretations WHERE idem=?", (body["idempotency_key"],)
            ).fetchone()
            if old:
                if old["digest"] != identity:
                    fault("conflict", "Interpretation idempotency mismatch")
                return self.get(key, old["id"])
            meta = self.vocabulary(key)
            info = self._current(key, body["expected_revision"], meta["generation"])
            if parent:
                previous = self.get(key, parent)
                if previous["body"]["conversation_id"] != body["conversation_id"]:
                    fault("conflict", "Clarification belongs to a different conversation")
            self._room(db, body["conversation_id"], len(dumps(body)))
            selected = []
            for uid in body["context_turn_ids"]:
                turn = self.get(key, uid)
                if turn["body"]["conversation_id"] != body["conversation_id"]:
                    fault("forbidden", "Context must belong to this conversation")
                selected.append({"id": uid, "utterance": turn["body"]["utterance"]})
            if len(dumps(selected)) > MAX_CONTEXT_BYTES:
                fault("invalid_limits", "Selected user history exceeds the disclosure bound")
            config = None
            if body["translator"] == "external":
                c = self.learning._usable(body["connection_id"], body["connection_version"], "interpretation")
                for name, limit in body["call_limits"].items():
                    if limit > getattr(self.runtime.config.learning.call, name):
                        fault("invalid_limits", "Translation call exceeds configured caps")
                config = {k: c[k] for k in ("provider", "model", "configuration_digest")}
                config["connection_id"] = c["id"]
            uid = str(uuid4())
            item = {
                "id": uid,
                "body": body,
                "status": "queued",
                "created": self.learning.now(),
                "revision_id": info["revision_id"],
                "language_generation": meta["generation"],
                "vocabulary": meta["vocabulary"],
                "context": context_binding(info),
                "parent_id": parent,
                "revalidation": revalidation,
                "selected_context": selected,
                "provider_configuration": config,
                "authority_generation": self.learning.settings()["generation"],
                "grant_id": None,
                "draft": None,
                "catalog": None,
                "choices": [],
                "error": None,
                "generation": self.store.generation,
                "deadline": self.learning.now() + body["call_limits"]["max_duration_ms"] / 1000 + 60,
            }
            self._room(db, body["conversation_id"], len(dumps(item)))
            db.execute(
                "INSERT INTO interpretations(id,idem,digest,conversation,status,data) VALUES(?,?,?,?,'queued',?)",
                (uid, body["idempotency_key"], identity, body["conversation_id"], dumps(item)),
            )
            self.store.emit(db, key, "interpretation.changed", uid, data={"status": "queued"})
        self.wake.set()
        return self.get(key, uid)

    def revalidate(self, key, uid, body):
        source = self.get(key, uid)
        if not source["draft"] or source["draft"]["status"] != "ready":
            fault("conflict", "Only a complete preview can be revalidated")
        return self.create(
            key,
            {
                "idempotency_key": body["idempotency_key"],
                "expected_revision": body["expected_revision"],
                "conversation_id": source["body"]["conversation_id"],
                "utterance": source["body"]["utterance"],
            },
            parent=uid,
            revalidation={
                "query": source["draft"]["query"],
                "command": source.get("proposed_command")
                or (source.get("revalidation") or {}).get("command")
                or source["body"]["utterance"],
                "source_catalog_digest": source["draft"]["catalog_digest"],
                "source_translator": source["draft"]["translator"],
                "assumptions": source["draft"]["assumptions"],
            },
        )

    def _raw(self, key, uid):
        with self.store.db(key) as db:
            row = db.execute("SELECT data FROM interpretations WHERE id=?", (uid,)).fetchone()
        if row is None:
            fault("not_found", "Interpretation not found")
        return loads(row[0])

    def _fail(self, key, item, reason):
        with self.store.db(key) as db, self.store.transaction(db):
            item = self._raw(key, item["id"])
            if item["status"] not in PENDING:
                return
            item.update(status="failed", error=reason)
            self._save(db, key, item)

    def cancel(self, key, uid):
        with self.store.lock:
            item = self._raw(key, uid)
            if item["status"] in PENDING or item["status"] == "ready":
                with self.store.db(key) as db, self.store.transaction(db):
                    item.update(status="cancelled", error="owner_cancelled")
                    self._save(db, key, item)
        return self.get(key, uid)

    def grant_valid(self, grant):
        item = self._raw(grant["adm"], grant["interpretation_id"])
        self._current(grant["adm"], item["revision_id"], item["language_generation"])
        if item["status"] != "awaiting_provider" or item["grant_id"] != grant["id"]:
            fault("stale_context", "Interpretation no longer owns the grant")

    def execute(self, key, uid, body):
        body = ExecuteInput.model_validate(body).model_dump()
        body["limits"] = self.runtime.limits(body["limits"])
        identity = fingerprint(body)
        with self.store.lock:
            with self.store.db(key) as db:
                old = db.execute(
                    "SELECT * FROM language_executions WHERE interpretation=? OR idem=?",
                    (uid, body["idempotency_key"]),
                ).fetchone()
            if old:
                if (
                    old["interpretation"] != uid
                    or old["digest"] != identity
                    or old["idem"] != body["idempotency_key"]
                ):
                    fault("conflict", "This preview already has a different execution consent")
                return self.store.request(key, old["request"])
            item = self._raw(key, uid)
            self._current(key, item["revision_id"], item["language_generation"])
            if item["status"] != "ready" or not item["draft"] or item["draft"]["status"] != "ready":
                fault("conflict", "Interpretation is not executable")
            if (
                body["expected_revision"] != item["revision_id"]
                or body["expected_catalog_digest"] != item["draft"]["catalog_digest"]
            ):
                fault("stale_context", "Consent does not match the preview")
        self._compute(
            key, item["revision_id"], item["vocabulary"], "language_revalidate", draft=item["draft"]
        )
        with self.store.db(key) as db, self.store.transaction(db):
            self._current(key, item["revision_id"], item["language_generation"])
            fresh = self._raw(key, uid)
            if fresh["status"] != "ready":
                fault("conflict", "Preview was cancelled")
            old = db.execute(
                "SELECT * FROM language_executions WHERE interpretation=? OR idem=?",
                (uid, body["idempotency_key"]),
            ).fetchone()
            if old:
                if (
                    old["interpretation"] != uid
                    or old["digest"] != identity
                    or old["idem"] != body["idempotency_key"]
                ):
                    fault("conflict", "Execution consent changed")
                request_id = old["request"]
            else:
                envelope = Request(
                    idempotency_key="interpretation:" + uid,
                    query=item["draft"]["query"],
                    limits=body["limits"],
                ).model_dump()
                request_id = self.store.submit_transaction(
                    db, key, envelope, expected_revision=item["revision_id"]
                )
                db.execute(
                    "INSERT INTO language_executions VALUES(?,?,?,?)",
                    (uid, body["idempotency_key"], identity, request_id),
                )
                self.store.emit(db, key, "interpretation.executed", uid, data={"request_id": request_id})
        self.runtime.coordinator.wake.set()
        return self.store.request(key, request_id)

    def teach(self, key, conversation, body):
        body = TeachInput.model_validate(body).model_dump()
        identity = fingerprint({"conversation": conversation, **body})
        with self.store.db(key) as db, self.store.transaction(db):
            old = db.execute(
                "SELECT digest,data FROM teaching_drafts WHERE idem=?", (body["idempotency_key"],)
            ).fetchone()
            if old:
                if old["digest"] != identity:
                    fault("conflict", "Teaching idempotency mismatch")
                return loads(old["data"])
            self._current(key, body["expected_revision"], self.vocabulary(key)["generation"])
            self._room(db, conversation, len(dumps(body)))
            item = {
                "id": str(uuid4()),
                "conversation_id": conversation,
                "text": body["text"],
                "revision_id": body["expected_revision"],
                "status": "draft",
                "created": self.learning.now(),
                "authority": "none",
                "next_step": "Open the Teach workspace to prepare a checked task with its own learning allowance. Preparation does not start learning. Attach supplied material in Teach or use Advanced model tools for explicit source extraction.",
            }
            self._room(db, conversation, len(dumps(item)))
            db.execute(
                "INSERT INTO teaching_drafts(id,idem,digest,conversation,data) VALUES(?,?,?,?,?)",
                (item["id"], body["idempotency_key"], identity, conversation, dumps(item)),
            )
            self.store.emit(db, key, "teaching.drafted", item["id"])
        return item

    def loop(self):
        while not self.stop.is_set():
            try:
                progress = self.tick()
            except (RuntimeFault, ValueError, sqlite3.Error, OSError):
                progress = False
            if not progress:
                self.wake.wait(0.25)
                self.wake.clear()

    def tick(self):
        keys = [r["id"] for r in self.store.list() if r["status"] == "ready"]
        if not keys:
            return False
        self.position %= len(keys)
        keys = keys[self.position :] + keys[: self.position]
        self.position += 1
        for key in keys:
            with self.store.db(key) as db:
                rows = db.execute(
                    "SELECT data FROM interpretations WHERE status IN ('queued','awaiting_provider') ORDER BY seq"
                ).fetchall()
            for row in rows:
                item = loads(row[0])
                try:
                    with self.store.lock:
                        self._current(key, item["revision_id"], item["language_generation"])
                        if self.learning.now() >= item["deadline"]:
                            fault("resource_exhausted", "Interpretation deadline expired")
                    if item["status"] == "queued":
                        self._prepare(key, item)
                        return True
                    with self.store.db() as db:
                        grant = db.execute("SELECT * FROM grants WHERE id=?", (item["grant_id"],)).fetchone()
                    if grant["outcome"] is None:
                        continue
                    grant_body, outcome = loads(grant["body"]), loads(grant["outcome"])
                    if outcome["status"] != "succeeded":
                        fault(
                            outcome.get("error") or "provider_unavailable",
                            "Provider did not complete a known response",
                        )
                    self.learning._grant_valid(grant_body)
                    value = self._compute(
                        key,
                        item["revision_id"],
                        item["vocabulary"],
                        "language_parse",
                        utterance=item["body"]["utterance"],
                        provider_text=outcome["text"],
                    )
                    item["provenance"] = {
                        **grant_body["provenance"],
                        "grant_id": grant["id"],
                        "requested_model": item["provider_configuration"]["model"],
                        "returned_model": outcome["returned_model"],
                        "response_id": outcome["response_id"],
                    }
                    self._complete(key, item, value, grant_body)
                    return True
                except RuntimeFault as error:
                    if error.code == "busy":
                        continue
                    self._fail(key, self._raw(key, item["id"]), error.code)
                    return True
                except (ValueError, KeyError, TypeError):
                    self._fail(key, self._raw(key, item["id"]), "invalid_interpretation")
                    return True
        return False

    def _prepare(self, key, item):
        body = item["body"]
        # Local interpretation also rejects administrative/teaching phrases before
        # any remote reservation can be issued.
        command = item["revalidation"]["command"] if item["revalidation"] else body["utterance"]
        value = self._compute(
            key, item["revision_id"], item["vocabulary"], "language_parse", utterance=command
        )
        if item["revalidation"]:
            # Revalidation preserves the already reviewed query, not an inferred
            # replacement. A new confirmation is still required.
            from ..engine.results import semantic_query

            parsed = value["parsed"]
            if parsed["status"] == "ready" and fingerprint(semantic_query(parsed["query"])) != fingerprint(
                semantic_query(item["revalidation"]["query"])
            ):
                parsed.update(
                    status="needs_clarification",
                    query=None,
                    clarification="The current vocabulary changes this request's meaning. Submit a clarified question and review a new preview.",
                )
            parsed["assumptions"] = item["revalidation"]["assumptions"]
        if body["translator"] == "local" or blocked(body["utterance"]):
            self._complete(key, item, value)
            return
        with self.store.lock:
            self._current(key, item["revision_id"], item["language_generation"])
            fresh = self._raw(key, item["id"])
            if fresh["status"] != "queued":
                return
            if item["authority_generation"] != self.learning.settings()["generation"]:
                fault("stale_context", "Remote authority changed")
            c = self.learning._usable(body["connection_id"], body["connection_version"], "interpretation")
            with self.store.db(key) as db:
                result_ids = [
                    r[0]
                    for r in db.execute(
                        "SELECT result_id FROM requests WHERE status='succeeded' ORDER BY seq DESC LIMIT 100"
                    )
                ]
            spec = specification(body["utterance"], value["catalog"], item["selected_context"], result_ids)
            raw, estimate = make_wire(c, spec, body["call_limits"]["max_output_tokens"])
            grant_id = self.learning.reserve(
                {
                    "purpose": "interpretation",
                    "allowance_id": body.get("allowance_id"),
                    "interpretation_id": item["id"],
                    "base_revision": item["revision_id"],
                    "connection_id": c["id"],
                    "connection_version": c["version"],
                    "configuration_digest": c["configuration_digest"],
                    "wire": base64.b64encode(raw).decode(),
                    "input_estimate": estimate,
                    "limits": body["call_limits"],
                    "provenance": provenance(spec, raw),
                    "recorded_index": 0,
                    "deadline": min(
                        item["deadline"], self.learning.now() + body["call_limits"]["max_duration_ms"] / 1000
                    ),
                },
                adm=key,
            )
            item.update(status="awaiting_provider", grant_id=grant_id, catalog=value["catalog"])
            with self.store.db(key) as db, self.store.transaction(db):
                self._save(db, key, item)

    def _complete(self, key, item, value, grant=None):
        with self.store.db(key) as db, self.store.transaction(db):
            if self.learning.now() >= item["deadline"]:
                fault("resource_exhausted", "Interpretation deadline expired")
            self._current(key, item["revision_id"], item["language_generation"])
            if self._raw(key, item["id"])["status"] not in PENDING:
                return
            if grant:
                self.learning._grant_valid(grant)
            parsed = value["parsed"]
            draft = IntentDraft(
                interpretation_id=item["id"],
                context=item["context"],
                catalog_digest=value["catalog"]["digest"],
                utterance=item["body"]["utterance"],
                translator=item["body"]["translator"],
                provider_configuration=item["provider_configuration"],
                **{k: parsed[k] for k in ("status", "query", "assumptions", "clarification")},
            ).model_dump()
            item.update(
                status=parsed["status"],
                draft=draft,
                choices=parsed["choices"],
                catalog=value["catalog"],
                proposed_command=value.get("proposed_command"),
            )
            self._save(db, key, item)
