"""Durable read-only Ask orchestration. No acquisition or provider-supplied authority."""

import base64
import threading

from ..contracts import CallLimits, Request
from ..language.prompt import specification as interpret_spec
from ..learning.service import fault, fingerprint
from ..providers.wire import make_wire, provenance
from ..runtime.protocol import RuntimeFault, dumps, loads
from ..wire import decode
from . import history
from .models import GapInput, Presentation
from .presentation import packet, readable, validate
from .presentation import specification as narrate_spec

ACTIVE = {"queued", "awaiting_provider", "awaiting_local", "awaiting_narration"}
TERMINAL_LOCAL = {"succeeded", "needs_input", "inconclusive", "failed", "cancelled", "interrupted", "expired"}


class Ask:
    def __init__(self, service):
        self.s, self.rt, self.store = service, service.runtime, service.store
        self.lock = threading.Lock()
        self.position = 0

    def save(self, key, work):
        with self.store.db(key) as db, self.store.transaction(db):
            self.s._save_work(db, key, work, "conversation.queued")

    def recover(self, key, work):
        if not work.get("request_id"):
            return False
        if work.get("local_outcome"):
            self.complete(key, work, reason="app_restarted")
            return True
        # Existing local identity may finish or have been interrupted by the local
        # scheduler. Reattach; never resubmit or repeat any outbound call.
        work["status"] = "awaiting_local"
        work["skip_narration"] = "app_restarted"
        self.save(key, work)
        return True

    def tick(self):
        if not self.lock.acquire(blocking=False):
            return False
        try:
            keys = [m["id"] for m in self.store.list() if m["status"] == "ready"]
            if not keys:
                return False
            self.position %= len(keys)
            keys = keys[self.position :] + keys[: self.position]
            self.position += 1
            for key in keys:
                with self.store.db(key) as db:
                    rows = db.execute(
                        "SELECT body FROM chat_work WHERE status IN ('queued','awaiting_provider','awaiting_local','awaiting_narration') ORDER BY seq LIMIT 100"
                    ).fetchall()
                for row in rows:
                    work = loads(row[0])
                    if work.get("flow") != "ask":
                        continue
                    try:
                        if work["status"] == "awaiting_local":
                            request = self.store.request(key, work["request_id"])
                            if request["status"] not in TERMINAL_LOCAL:
                                continue
                            self.local_done(key, work, request)
                            return True
                        with self.store.lock:
                            self.s.grant_valid({"adm": key, "conversation_work_id": work["id"]})
                        if work["status"] == "queued":
                            self.prepare(key, work)
                            return True
                        with self.store.db() as db:
                            grant = db.execute(
                                "SELECT body,outcome FROM grants WHERE id=?", (work["grant_id"],)
                            ).fetchone()
                        if not grant["outcome"]:
                            continue
                        response = loads(grant["outcome"])
                        if response["status"] != "succeeded":
                            fault("provider_unavailable", "Ask provider response failed")
                        with self.store.lock:
                            self.rt.learning._grant_valid(loads(grant["body"]))
                        text = response.get("text", "")
                        if len(text.encode()) > 16384:
                            raise ValueError("Oversized Ask reply")
                        if work["status"] == "awaiting_narration":
                            reply = validate(decode(text.encode()), work["packet"])
                            self.complete(key, work, reply=reply)
                        else:
                            self.interpreted(key, work, text)
                        return True
                    except (RuntimeFault, ValueError, TypeError, KeyError) as error:
                        code = error.code if isinstance(error, RuntimeFault) else "invalid_provider_reply"
                        work["failure_code"] = code
                        if work.get("request_id"):
                            # Narration/context failures cannot hide a saved local outcome.
                            self.complete(key, work, reason=code)
                        else:
                            self.s._finish(
                                key,
                                work,
                                "failed",
                                (
                                    "The model or interaction authority changed. Please restate your question against the current model. No local request or learning task was started."
                                    if code == "stale_context"
                                    else str(error) + " No local request or learning task was started."
                                    if code
                                    in {
                                        "remote_calls_disabled",
                                        "allowance_expired",
                                        "allowance_closed",
                                        "allowance_exhausted",
                                        "spending_disabled",
                                        "price_unavailable",
                                        "connection_unavailable",
                                        "purpose_unavailable",
                                        "allowance_unavailable",
                                    }
                                    else "The question could not be interpreted under the current model, provider or allowance. No local request or learning task was started. Check Details; there is no automatic retry."
                                ),
                            )
                        return True
            return False
        finally:
            self.lock.release()

    def prepare(self, key, work):
        meta = self.rt.language.vocabulary(key)
        checked = self.rt.language._compute(
            key,
            work["context"]["revision_id"],
            meta["vocabulary"],
            "language_ask_catalog" if work["preferences"].get("snapshot_history") else "language_catalog",
        )
        work["vocabulary"] = meta["vocabulary"]
        work["catalog_digest"] = checked["catalog"]["digest"]
        # Only this conversation's explicitly linked successful results may be named.
        with self.store.db(key) as db:
            conv = self.s._conversation(db, work["conversation_id"])
        ids = [x["resource_id"] for x in conv.get("links", []) if x["kind"] == "result"][:32]
        spec = interpret_spec(work["text"], checked["catalog"], work["selected_context"], ids)
        spec["name"] = "adm_ask_intent"
        spec["prompt_version"] = "adm-ask-interpretation/2"
        spec["instructions"] = (
            spec["instructions"]
            .replace(
                "typed intent preview. Only an explicitly confirmed preview runs locally.",
                "checked intent. The owner has authorized automatic read-only local execution in this Ask conversation. Return ready only when meaning and all slots are explicit; any uncertainty must ask for clarification.",
            )
            .replace("for the owner's review", "without silently filling missing slots")
        )
        spec["context"]["pending_question"] = work["question"]
        spec["context"]["pending_intent"] = work.get("pending_intent")
        if work["preferences"].get("historical_lookup"):
            with self.store.lock:
                self.s.grant_valid({"adm": key, "conversation_work_id": work["id"]})
                work["fact_projection"] = self.rt.sources.policy(key).get("projection")
            spec["instructions"] += history.INSTRUCTIONS
            spec["context"]["owner_fact_projection"] = work["fact_projection"]
            if work["preferences"].get("snapshot_history"):
                work["accepted_fact_projections"] = checked["accepted_fact_projections"]
                spec["context"]["accepted_fact_projections"] = work["accepted_fact_projections"]
                spec["instructions"] += history.SNAPSHOT_INSTRUCTIONS
        work["allowed_result_ids"] = ids
        self.reserve(key, work, "ask_interpretation", spec)

    def reserve(self, key, work, purpose, spec):
        with self.store.lock:
            self.s.grant_valid({"adm": key, "conversation_work_id": work["id"]})
            from .readiness import require

            require(self.s, {"preferences": work["preferences"]})
            with self.store.db() as db:
                allowance, price = self.s.finance.valid(db, work["preferences"]["allowance_id"])
            if (
                allowance["adm_id"] != key
                or allowance["scope"] != "interaction"
                or allowance["scope_id"] != work["conversation_id"]
            ):
                fault("forbidden", "Ask allowance is bound to another conversation")
            if purpose == "ask_narration" and not work["preferences"].get("narrate_results"):
                fault("forbidden", "Result disclosure is not authorized")
            conn = self.rt.learning._usable(price["connection_id"], price["connection_version"], purpose)
            raw, estimate = make_wire(conn, spec, 4096)
            prov = provenance(spec, raw)
            operation = work["id"] + ("-narration" if purpose == "ask_narration" else "-interpretation")
            self.s.finance.child(
                allowance["id"],
                {
                    "operation_id": operation,
                    "kind": "narration" if purpose == "ask_narration" else "preparation",
                    "max_work": 1,
                    "payload_digest": prov["request_hash"],
                },
            )
            gid = self.rt.learning.reserve(
                {
                    "purpose": purpose,
                    "conversation_work_id": work["id"],
                    "operation_id": operation,
                    "allowance_id": allowance["id"],
                    "base_revision": work["context"]["revision_id"],
                    "connection_id": conn["id"],
                    "connection_version": conn["version"],
                    "configuration_digest": conn["configuration_digest"],
                    "wire": base64.b64encode(raw).decode(),
                    "input_estimate": estimate,
                    "limits": CallLimits(
                        max_input_tokens=work["preferences"].get("call_input_bound", 32000),
                        max_output_tokens=4096,
                    ).model_dump(),
                    "provenance": prov,
                    "recorded_index": 0,
                    "deadline": min(work["deadline_ms"] / 1000, self.rt.learning.now() + 60),
                },
                adm=key,
            )
            work.update(
                status="awaiting_narration" if purpose == "ask_narration" else "awaiting_provider",
                grant_id=gid,
            )
            work["links"].append({"kind": "provider_grant", "id": gid})
            self.save(key, work)
            self.s.finance.settle_work(allowance["id"], operation, 1)

    def interpreted(self, key, work, text):
        historical = (
            history.parse(text, work.get("fact_projection"), work.get("accepted_fact_projections", ()))
            if "fact_projection" in work
            else None
        )
        value = (
            {"parsed": historical, "catalog": {"digest": work["catalog_digest"]}}
            if historical
            else self.rt.language._compute(
                key,
                work["context"]["revision_id"],
                work["vocabulary"],
                "language_parse",
                utterance=work["text"],
                provider_text=text,
            )
        )
        parsed = value["parsed"]
        work["interpretation"] = value
        with self.store.lock:
            self.s.grant_valid({"adm": key, "conversation_work_id": work["id"]})
            if value["catalog"]["digest"] != work["catalog_digest"]:
                fault("stale_context", "Interpretation meaning changed")
        if parsed["status"] != "ready" or parsed["assumptions"]:
            status = (
                "needs_input" if parsed["status"] in {"ready", "needs_clarification"} else parsed["status"]
            )
            text = parsed["clarification"] or "Please clarify the missing or assumed details: " + "; ".join(
                parsed["assumptions"]
            )
            if status == "needs_input":
                with self.store.lock, self.store.db(key) as db, self.store.transaction(db):
                    self.s.grant_valid({"adm": key, "conversation_work_id": work["id"]})
                    conv = self.s._conversation(db, work["conversation_id"])
                    q = self.s._question(
                        db,
                        key,
                        conv,
                        text,
                        work["context"],
                        "ask_intent",
                        {
                            "original_text": (work.get("pending_intent") or {}).get(
                                "original_text", work["text"]
                            ),
                            "interpretation": parsed,
                        },
                        work["depth"],
                    )
                    work["links"].append({"kind": "question", "id": q["id"]})
                    work.update(status=status, finished_at_ms=self.s.now())
                    self.s._save_work(db, key, work, "conversation.completed")
            else:
                self.s._finish(key, work, status, text + " No query or learning task was started.")
            return
        query = parsed["query"]
        if query["op"] == "explain" and query["result_id"] not in work["allowed_result_ids"]:
            raise ValueError("Result was not disclosed in this conversation")
        # Reparse/revalidate in a bounded child immediately before the atomic enqueue.
        checked = (
            value
            if historical
            else self.rt.language._compute(
                key,
                work["context"]["revision_id"],
                work["vocabulary"],
                "language_parse",
                utterance=value["proposed_command"],
            )
        )
        if (
            checked["parsed"]["status"] != "ready"
            or checked["parsed"]["query"] != query
            or checked["catalog"]["digest"] != work["catalog_digest"]
        ):
            fault("stale_context", "Checked intent meaning changed")
        envelope = Request(
            idempotency_key="ask:" + work["id"], query=query, limits=self.rt.limits(), on_gap="report"
        ).model_dump()
        with self.store.lock, self.store.db(key) as db, self.store.transaction(db):
            self.s.grant_valid({"adm": key, "conversation_work_id": work["id"]})
            work["request_id"] = self.store.submit_transaction(
                db, key, envelope, expected_revision=work["context"]["revision_id"]
            )
            work["status"] = "awaiting_local"
            work["links"].append({"kind": "request", "id": work["request_id"]})
            self.s._save_work(db, key, work, "conversation.queued")
        self.rt.coordinator.wake.set()

    def local_done(self, key, work, request):
        if not work.get("local_outcome"):
            work["packet"], work["local_outcome"] = packet(work["context"], request)
            work["outcome_digest"] = fingerprint(request.get("result") or work["local_outcome"])
        self.save(key, work)
        if work.get("skip_narration") or not work["preferences"].get("narrate_results") or not work["packet"]:
            self.complete(
                key,
                work,
                reason=work.get("skip_narration")
                or (
                    "disclosure_disabled"
                    if not work["preferences"].get("narrate_results")
                    else "packet_limit"
                ),
            )
        else:
            self.reserve(key, work, "ask_narration", narrate_spec(work["packet"]))

    def complete(self, key, work, *, reply=None, reason=None):
        if not work.get("local_outcome"):
            request = self.store.request(key, work["request_id"])
            if request["status"] not in TERMINAL_LOCAL:
                return
            work["packet"], work["local_outcome"] = packet(work["context"], request)
            work["outcome_digest"] = fingerprint(request.get("result") or work["local_outcome"])
        value, body = work["packet"], work["local_outcome"]
        text = readable(body)
        presentation = {
            "profile": "awm-adm-v3-presentation/0.2",
            "id": work["id"],
            "context": work["context"],
            "subject_kind": "result" if body["result_id"] else "request",
            "subject_id": body["result_id"] or body["request_id"],
            "outcome_digest": value["outcome_digest"] if value else work["outcome_digest"],
            "packet_digest": value["digest"]
            if value
            else fingerprint({"omitted": "packet_limit", "outcome": fingerprint(body)}),
            "status": "ready" if reply else "fallback",
            "text": reply["explanation"] if reply else text,
            "support_ids": reply["support_ids"] if reply else [],
            "authoritative": False,
        }
        presentation = Presentation.model_validate(presentation).model_dump()
        record = {
            "presentation": presentation,
            "outcome_text": text,
            "outcome": body,
            "packet": value,
            "request_id": work["request_id"],
            "narration": reply,
            "fallback_reason": reason,
        }
        with self.store.lock, self.store.db(key) as db, self.store.transaction(db):
            current = loads(self.s._one(db, "chat_work", work["id"])["body"])
            if current["status"] not in ACTIVE:
                return
            if reply:
                self.s.grant_valid({"adm": key, "conversation_work_id": work["id"]})
            conv = self.s._conversation(db, work["conversation_id"])
            turn = self.s._turn(db, key, conv, "system", text, context=work["context"])
            record["turn_id"] = turn["id"]
            db.execute(
                "INSERT INTO chat_presentations VALUES(?,?,?)",
                (work["id"], work["conversation_id"], dumps(record)),
            )
            work.update(
                status="completed",
                local_status=body["status"],
                presentation_id=work["id"],
                finished_at_ms=self.s.now(),
            )
            self.s._save_work(db, key, work, "conversation.completed")

    def get(self, key, uid):
        with self.store.db(key) as db:
            return loads(self.s._one(db, "chat_presentations", uid)["body"])

    def summaries(self, key, cid):
        with self.store.db(key) as db:
            records = [
                loads(r[0])
                for r in db.execute(
                    "SELECT body FROM chat_presentations WHERE conversation=? LIMIT 100", (cid,)
                )
            ]
        return [
            {
                "id": r["presentation"]["id"],
                "turn_id": r["turn_id"],
                "status": r["presentation"]["status"],
                "explanation": r["presentation"]["text"] if r["narration"] else None,
                "fallback_reason": r["fallback_reason"],
                "local_status": r["outcome"]["status"],
            }
            for r in records
        ]

    def gap(self, key, uid, body):
        body = GapInput.model_validate(body).model_dump()
        with self.store.lock:
            with self.store.db(key) as db:
                work = loads(self.s._one(db, "chat_work", uid)["body"])
            if work["status"] != "needs_learning" and work.get("local_status") != "needs_input":
                fault("conflict", "This exchange does not report a learning gap")
            self.s._current(key, body["context"])
            if body["context"] != work["context"]:
                fault("stale_context", "The original Ask meaning changed; start a fresh question")
            conv = self.s.create(
                key,
                {
                    "idempotency_key": "gap:" + body["idempotency_key"],
                    "channel": "teach",
                    "title": "Learning from an Ask gap",
                },
            )
            with self.store.db(key) as db, self.store.transaction(db):
                current = self.s._conversation(db, conv["id"])
                reference = {
                    "work_id": uid,
                    "context": work["context"],
                    "text": work["text"],
                    "request_id": work.get("request_id"),
                    "interpretation": work.get("interpretation"),
                    "authority": "none",
                }
                if current.get("ask_gap"):
                    if current["ask_gap"] != reference:
                        fault("conflict", "Gap identity belongs to a different Ask")
                    return current
                current["ask_gap"] = reference
                db.execute("UPDATE chat_conversations SET body=? WHERE id=?", (dumps(current), conv["id"]))
                self.s._turn(
                    db,
                    key,
                    current,
                    "system",
                    "Original Ask: "
                    + work["text"]
                    + "\nThe original query and context are preserved in Details. Set up a separate Teach allowance to prepare this objective. No learning task, provider call or publication was created by this transfer.",
                    context=work["context"],
                )
            return current
