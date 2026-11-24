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
from .models import Presentation
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
                                    else "The question could not be interpreted. No local query or learning was started. Please check the connection or rephrase your question."
                                ),
                            )
                        return True
            return False
        finally:
            self.lock.release()

    def prepare(self, key, work):
        from ..temporal import context

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
        spec = interpret_spec(work["text"], checked["catalog"], work["selected_context"], ids, automatic=True)
        work.setdefault("temporal_context", context())
        spec["context"]["temporal_context"] = work["temporal_context"]
        spec["context"]["pending_question"] = work["question"]
        spec["context"]["pending_intent"] = work.get("pending_intent")
        if work["preferences"].get("historical_lookup"):
            with self.store.lock:
                self.s.grant_valid({"adm": key, "conversation_work_id": work["id"]})
                work["fact_projection"] = self.rt.sources.policy(key).get("projection")
            from ..temporal_evidence.guidance import ASK as TEMPORAL_ASK
            from ..temporal_evidence.guidance import RECALL

            spec["instructions"] += history.INSTRUCTIONS + TEMPORAL_ASK + RECALL
            spec["prompt_version"] = "adm-ask-interpretation/temporal-3"
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
            conn = self.rt.interactions.connection_for(work, purpose)
            if purpose == "ask_narration" and not work["preferences"].get("narrate_results"):
                fault("forbidden", "Result explanation is not part of this interaction")
            output_limit = min(4096, self.rt.config.learning.call.max_output_tokens)
            raw, estimate = make_wire(conn, spec, output_limit)
            if len(raw) > self.rt.config.server.max_body_bytes:
                fault("resource_exhausted", "This interpretation context exceeds the request size limit")
            prov = provenance(spec, raw)
            operation = work["id"] + ("-narration" if purpose == "ask_narration" else "-interpretation")
            gid = self.rt.learning.reserve(
                {
                    "purpose": purpose,
                    "conversation_work_id": work["id"],
                    "operation_id": operation,
                    "base_revision": work["context"]["revision_id"],
                    "connection_id": conn["id"],
                    "connection_version": conn["version"],
                    "configuration_digest": conn["configuration_digest"],
                    "wire": base64.b64encode(raw).decode(),
                    "input_estimate": estimate,
                    "limits": CallLimits(
                        max_input_tokens=max(estimate, self.rt.config.learning.call.max_input_tokens),
                        max_output_tokens=output_limit,
                        max_duration_ms=self.rt.config.learning.call.max_duration_ms,
                    ).model_dump(),
                    "provenance": prov,
                    "recorded_index": 0,
                    "deadline": min(
                        work["deadline_ms"] / 1000,
                        self.rt.learning.now() + self.rt.config.learning.call.max_duration_ms / 1000,
                    ),
                },
                adm=key,
            )
            work.update(
                status="awaiting_narration" if purpose == "ask_narration" else "awaiting_provider",
                grant_id=gid,
            )
            work["links"].append({"kind": "provider_grant", "id": gid})
            self.save(key, work)

    def interpreted(self, key, work, text):
        historical = (
            history.parse(
                text,
                work.get("fact_projection"),
                work.get("accepted_fact_projections", ()),
                temporal_context=work.get("temporal_context"),
            )
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
            text = parsed["clarification"] or (
                "Before I check, can you confirm this detail? " + "; ".join(parsed["assumptions"])
                if parsed["assumptions"]
                else "What would you like the model to check? Please include the missing details."
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
            work["packet"], work["local_outcome"] = packet(
                work["context"],
                request,
                question=work["text"],
                user_turns=work["selected_context"],
                temporal_resolution=(work.get("interpretation") or {})
                .get("parsed", {})
                .get("temporal_resolution"),
            )
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
            work["packet"], work["local_outcome"] = packet(
                work["context"], request, question=work["text"], user_turns=work["selected_context"]
            )
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
