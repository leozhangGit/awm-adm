"""Durable task ownership over bounded acquisition episodes. No provider-supplied authority.

The ADM transaction owns commands, publication fences and completion delivery.
Registry reservations precede child creation and retain uncertainty on interruption.
"""

import base64
import threading

from ..contracts import CallLimits, Request
from ..conversations.presentation import outcome, readable
from ..engine.data import read_json, thaw
from ..learning.service import FINAL, fault, fingerprint
from ..providers.wire import make_wire, provenance
from ..runtime.protocol import RuntimeFault, dumps, loads, unpack
from ..wire import decode
from .execution_models import COMPLETION_SCHEMA, CompletionReply, TaskCommand
from .review import candidate

TERMINAL = {"succeeded", "partially_succeeded", "failed", "exhausted", "cancelled", "needs_input"}
ACTIVE = {"queued", "running", "awaiting_decision", "paused"}
LOCAL_FINAL = {"succeeded", "failed", "cancelled", "inconclusive", "needs_input", "interrupted", "expired"}


class Execution:
    def __init__(self, teaching):
        self.t, self.s, self.rt, self.store = teaching, teaching.s, teaching.rt, teaching.store
        self.learning, self.finance = self.rt.learning, self.s.finance
        self.lock = threading.Lock()
        self.position = 0

    @staticmethod
    def view(run):
        value = {
            k: v
            for k, v in run.items()
            if k
            in {
                "profile",
                "version",
                "status",
                "phase",
                "summary",
                "narration",
                "narration_failure",
                "finished_at_ms",
                "deadline_ms",
                "reason",
            }
        }
        value["steps"] = [
            {k: v for k, v in s.items() if k in {"id", "status", "reason", "source_progress", "feed_id"}}
            for s in run["steps"]
        ]
        review = run.get("review")
        value["review"] = (
            {k: v for k, v in review.items() if k in {"digest", "behaviors", "expires_at_ms"}}
            if review
            else None
        )
        return value

    def save(self, db, task):
        run = task["execution"]
        run["version"] += 1
        task["status"] = run["status"]
        self.t.save(db, task)

    def valid(self, key, task, *, spending=False):
        run = task["execution"]
        self.s._current(key, run["context"])
        if self.s._authority() != run["authority_generation"]:
            fault("stale_context", "Teaching owner authority changed")
        if self.learning.settings()["generation"] != run["learning_generation"]:
            fault("stale_context", "Learning configuration changed")
        if self.finance.settings()["generation"] != run["spending_generation"]:
            fault("stale_context", "Spending authority changed")
        if spending:
            with self.store.db() as db:
                allowance, price = self.finance.valid(db, task["allowance_id"])
            if allowance["scope_id"] != task["id"] or allowance["adm_id"] != key:
                fault("forbidden", "Execution allowance belongs to another task")
            return allowance, price

    def command(self, key, uid, body, principal):
        value = TaskCommand.model_validate(body).model_dump()
        if not value["source_consent"]:
            value.pop("source_consent")
        digest = fingerprint({"task": uid, "owner": principal, "command": value})
        with self.store.lock, self.store.db(key) as db, self.store.transaction(db):
            old = db.execute(
                "SELECT digest,body FROM teaching_commands WHERE id=?", (value["idempotency_key"],)
            ).fetchone()
            if old:
                if old["digest"] != digest:
                    fault("conflict", "Teaching command identity has different content")
                return loads(old["body"])
            if (
                db.execute("SELECT count(*) FROM teaching_commands").fetchone()[0]
                >= self.store.limits.queue_items_per_adm
            ):
                fault("quota_exceeded", "Retained teaching command limit reached")
            task = self.t.get(key, uid)
            if task.get("specification_digest") != value["specification_digest"]:
                fault("stale_context", "Prepared teaching meaning changed")
            run = task.get("execution")
            if value["expected_version"] != (run["version"] if run else 0):
                fault("stale_context", "Teaching task changed; review its current state")
            action = value["action"]
            # Cancellation is always possible, including after a model/authority change.
            if action != "cancel":
                self.s._current(key, value["context"])
            if action == "start":
                if run or task["status"] != "prepared" or task["context"] != value["context"]:
                    fault("conflict", "Only the unchanged prepared specification can start")
                with self.store.db() as registry:
                    allowance, price = self.finance.valid(registry, task["allowance_id"])
                if any(c["interfaces"] for c in task["specification"]["children"]):
                    self.learning._usable(price["connection_id"], price["connection_version"], "acquisition")
                self.learning._usable(price["connection_id"], price["connection_version"], "task_narration")
                spec = task["specification"]
                # This digest was checked by preparation against the pinned snapshot.
                # Existing independent requirements, never proposed requirements, decide eligibility.
                package = unpack(self.store.revision(key)["snapshot"])
                manifest = thaw(read_json(package.manifest))
                entry = next(e for e in manifest["files"] if e["role"] == "conformance")
                independent = thaw(read_json(package.files[entry["path"]]))
                publication = (
                    "checked_auto"
                    if independent.get("contracts") or independent.get("invariants")
                    else "review"
                )
                # Hold local completion work before paid work can consume its room.
                completion_reservations = {}
                for phase in ("vocabulary", "followup"):
                    if phase == "followup" and not (task.get("ask_gap") or {}).get("request_id"):
                        continue
                    reservation = {
                        "operation_id": task["id"] + "-" + phase,
                        "kind": "local_check",
                        "max_work": 1000000,
                        "payload_digest": fingerprint(
                            {"specification": task["specification_digest"], "phase": phase}
                        ),
                    }
                    self.finance.child(task["allowance_id"], reservation)
                    completion_reservations[phase] = reservation
                run = task["execution"] = {
                    "profile": "awm-adm-teaching-execution/1",
                    "version": 0,
                    "status": "queued",
                    "context": value["context"],
                    "authority_generation": self.s._authority(),
                    "learning_generation": self.learning.settings()["generation"],
                    "spending_generation": self.finance.settings()["generation"],
                    "publication": publication,
                    "started_at_ms": self.s.now(),
                    "deadline_ms": min(
                        task["budget"]["expires_at_ms"],
                        self.s.now()
                        + (
                            86400000
                            if task.get("source_queue")
                            else 3600000
                            if task.get("renewals")
                            else 900000
                        ),
                    ),
                    "connection_id": price["connection_id"],
                    "connection_version": price["connection_version"],
                    "input_bound": price["input_bound"],
                    "steps": [
                        {"id": child["id"], "status": "prepared", "episode_id": None}
                        for child in spec["children"]
                    ],
                    "review": None,
                    "phase": "children",
                    "followup": None,
                    "summary": None,
                    "completion_reservations": completion_reservations,
                    "disclosure": "Prepared task and its owner inputs/interfaces, bounded diagnostic feedback and accepted model definitions for acquisition; bounded completion outcomes and linked local answer for explanation. Other conversations are excluded.",
                }
                self.s.intake.start_check(key, task, value)
                run["source_consent"] = value.get("source_consent", False)
                if value.get("source_consent"):
                    run["disclosure"] += (
                        " Explicitly selected uploaded/pushed material is additionally authorized for this source scope and bounded provider processing."
                    )
                task["execution_authorized"] = True
            elif not run or run["status"] in TERMINAL:
                fault("conflict", "Task is not active; continuation requires a new task")
            elif action == "cancel":
                self.stop(task, "cancelled", "owner_cancelled")
            elif action == "finish":
                if not task.get("source_queue"):
                    fault("conflict", "Only standing source intake can be finished")
                run["closing_sources"] = True
                run["closing_source_sequence"] = db.execute(
                    "SELECT COALESCE(max(seq),0) FROM source_versions"
                ).fetchone()[0]
            elif action == "pause":
                if run["status"] == "paused":
                    fault("conflict", "Task is already paused")
                run["resume_status"], run["status"] = run["status"], "paused"
            elif action == "resume":
                if run["status"] != "paused":
                    fault("conflict", "Task is not paused")
                self.valid(key, task)
                if self.s.now() >= run["deadline_ms"] and run["resume_status"] != "awaiting_decision":
                    fault("stale_context", "Task deadline expired; continuation needs new authority")
                run["status"] = run.pop("resume_status")
            else:
                self.valid(key, task)
                review = run.get("review")
                if (
                    run["status"] != "awaiting_decision"
                    or not review
                    or value["review_digest"] != review["digest"]
                ):
                    fault("stale_context", "Candidate review changed")
                if self.s.now() >= review["expires_at_ms"]:
                    fault("stale_context", "Candidate review expired")
                if review.get("kind") == "source":
                    self.s.intake.review(key, task, action == "approve", db=db)
                    run["source_review"] = review if action == "approve" else None
                    row = None
                else:
                    row = db.execute(
                        "SELECT * FROM learning_receipts WHERE id=?", (review["receipt_id"],)
                    ).fetchone()
                if review.get("kind") != "source":
                    if (
                        row is None
                        or row["status"] != "awaiting_review"
                        or fingerprint(loads(row["data"])["package"]) != review["candidate_digest"]
                    ):
                        fault("stale_context", "Candidate no longer matches this review")
                    data = loads(row["data"])
                    data["approval_revision"] = run["context"]["revision_id"] if action == "approve" else None
                    db.execute(
                        "UPDATE learning_receipts SET status=?,data=? WHERE id=?",
                        ("approved" if action == "approve" else "rejected", dumps(data), row["id"]),
                    )
                    ep = self.learning._get(key, row["episode"])
                    ep.update(
                        status="ready" if action == "approve" else "rejected",
                        reason=None if action == "approve" else "owner_declined",
                    )
                    ep["parent_review_until"] = review["expires_at_ms"]
                    self.learning._save(db, ep)
                if action == "approve":
                    run["local_finish_until_ms"] = max(
                        run.get("local_finish_until_ms", 0), review["expires_at_ms"]
                    )
                run.update(status="running", review=None)
            self.save(db, task)
            ack = {
                "id": value["idempotency_key"],
                "task_id": uid,
                "action": action,
                "version": run["version"],
                "status": run["status"],
            }
            self.store.capacity(len(dumps(task)) + 4096)
            db.execute("INSERT INTO teaching_commands VALUES(?,?,?,?)", (ack["id"], uid, digest, dumps(ack)))
            conv = self.s._conversation(db, task["conversation_id"])
            text = {
                "start": "Teaching started within the approved task allowance. Checked work will be admitted automatically when independent requirements exist; otherwise I will ask you to review the candidate's meaning.",
                "pause": "Teaching is paused. A call already dispatched may still return and remain charged; no candidate will publish while paused.",
                "resume": "Teaching resumed within its original scope and remaining allowance.",
                "approve": "Candidate approved for local admission checks. Approval does not bypass those checks.",
                "decline": "Candidate declined. The model has not accepted this candidate.",
                "finish": "Intake is closing. Already received material will finish within the original allowance; new push is refused.",
                "cancel": "Teaching cancelled. Accepted work remains; outstanding or unknown calls remain accounted for.",
            }[action]
            self.s._turn(db, key, conv, "system", text)
            self.store.emit(db, key, "teaching.execution", uid, data=ack)
        self.s.wake.set()
        self.learning.wake.set()
        return ack

    @staticmethod
    def stop(task, status, reason):
        run = task["execution"]
        run.update(status=status, reason=reason, review=None)
        for step in run["steps"]:
            if step["status"] not in {"accepted", "unresolved"}:
                step.update(status="unresolved", reason=reason)

    def parent(self, key, ep):
        """Called under the store lock before dispatch and every publication."""
        task = self.t.get(key, ep["parent_task"])
        run = task["execution"]
        if run["status"] == "paused":
            return False
        if run["status"] not in {"queued", "running", "awaiting_decision"} or run["phase"] != "children":
            fault("stale_context", "Teaching task no longer owns this episode")
        self.valid(key, task)
        if ep.get("parent_review_until") and self.s.now() >= ep["parent_review_until"]:
            fault("stale_context", "Candidate review authority expired")
        if not any(s["episode_id"] == ep["id"] for s in run["steps"]):
            # Child creation intent is durable before create; acknowledgement can be lost.
            if not any(
                s.get("episode_input", {}).get("idempotency_key") == ep["body"]["idempotency_key"]
                for s in run["steps"]
            ):
                fault("forbidden", "Episode is outside this teaching task")
        return True

    def published(self, db, key, ep, revision, context):
        task = self.t.get(key, ep["parent_task"])
        run = task["execution"]
        step = next(
            s
            for s in run["steps"]
            if s.get("episode_id") == ep["id"]
            or s.get("episode_input", {}).get("idempotency_key") == ep["body"]["idempotency_key"]
        )
        step.update(status="accepted", episode_id=ep["id"], revision_id=revision)
        run["context"] = {
            **run["context"],
            "revision_id": revision,
            "theory_root": context["theory_version"],
            "support_root": context["support_root"],
            "policy_epoch": context["policy_epoch"],
        }
        ep["published_revision"] = revision
        self.save(db, task)

    def recover(self, key):
        with self.store.lock, self.store.db(key) as db, self.store.transaction(db):
            for row in db.execute(
                "SELECT body FROM teaching_tasks WHERE json_extract(body,'$.execution') IS NOT NULL"
            ).fetchall():
                task = loads(row[0])
                run = task["execution"]
                if run["status"] in TERMINAL:
                    continue
                # Known accepted work and known local candidates are reconciled by tick.
                # Completion dispatch is never repeated, including a lost grant acknowledgement.
                if run["phase"] == "narration":
                    run["narration_failure"] = "app_restarted"
                    run["phase"] = "deliver"
                self.save(db, task)

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
                        "SELECT body FROM teaching_tasks WHERE json_extract(body,'$.execution') IS NOT NULL ORDER BY seq"
                    ).fetchall()
                for row in rows:
                    task = loads(row[0])
                    run = task["execution"]
                    if run.get("delivered"):
                        continue
                    try:
                        if self.advance(key, task):
                            return True
                    except (RuntimeFault, ValueError, KeyError, TypeError) as error:
                        code = error.code if isinstance(error, RuntimeFault) else "invalid_execution"
                        with self.store.lock, self.store.db(key) as db, self.store.transaction(db):
                            task = self.t.get(key, task["id"])
                            self.stop(
                                task,
                                "needs_input"
                                if code == "stale_context"
                                else "exhausted"
                                if code in {"quota_exceeded", "resource_exhausted", "invalid_limits"}
                                else "failed",
                                code,
                            )
                            self.save(db, task)
                        return True
            return False
        finally:
            self.lock.release()

    def advance(self, key, task):
        if task["execution"]["phase"] == "vocabulary" and task["execution"]["status"] == "running":
            return self.vocabulary(key, task)
        with self.store.lock:
            task = self.t.get(key, task["id"])
            run = task["execution"]
            if run["status"] in TERMINAL:
                self.cancel_children(key, task)
                self.deliver(key, task)
                return True
            if run["status"] == "paused":
                deadline = (run.get("review") or {}).get("expires_at_ms", run["deadline_ms"])
                if self.s.now() >= deadline:
                    self.stop(task, "exhausted", "deadline_while_paused")
                    self.persist(key, task)
                    return True
                return False
            self.valid(key, task)
            if run["phase"] == "children" and self.s.intake.ensure_policy(key, task):
                return True
            for step in run["steps"]:
                if step["status"] == "accepted" and step.get("episode_id"):
                    ep = self.learning._get(key, step["episode_id"])
                    self.finance.settle_work(task["allowance_id"], "episode:" + step["id"], ep["work"])
            if run["phase"] == "narration":
                return self.narrated(key, task)
            if run["phase"] == "deliver":
                self.deliver(key, task)
                return True
            if run["phase"] == "followup":
                return self.followup(key, task)
            if run["status"] == "awaiting_decision":
                active = next(s for s in run["steps"] if s["status"] == "running")
                if active.get("feed_id"):
                    review = run["review"]
                    ep = self.rt.sources.get(key, "source_episodes", review["receipt_id"])
                    if ep["status"] in {"accepted", "rejected", "failed", "stopped", "cancelled"}:
                        run.update(status="running", review=None)
                        self.persist(key, task)
                        return True
                    if self.s.now() >= review["expires_at_ms"]:
                        self.stop(task, "exhausted", "review_expired")
                        self.persist(key, task)
                        return True
                    return False
                ep = self.learning._get(key, active["episode_id"])
                if ep["status"] in FINAL:
                    run.update(status="running", review=None)
                    return self.observe(key, task, active)
                if self.s.now() < run["review"]["expires_at_ms"]:
                    return False
                self.stop(task, "exhausted", "review_expired")
                self.persist(key, task)
                return True
            active = next(
                (s for s in run["steps"] if s["status"] not in {"accepted", "unresolved", "prepared"}), None
            )
            if active:
                if active.get("feed_id") or active.get("source_intent"):
                    return self.s.intake.observe(key, task, active)
                return self.observe(key, task, active)
            pending = [s for s in run["steps"] if s["status"] == "prepared"]
            if self.s.now() >= run["deadline_ms"] and pending:
                self.stop(task, "exhausted", "deadline")
                self.persist(key, task)
                return True
            if pending:
                by_id = {s["id"]: s for s in run["steps"]}
                children = {c["id"]: c for c in task["specification"]["children"]}
                step = next(
                    (
                        s
                        for s in pending
                        if all(
                            by_id[d]["status"] in {"accepted", "unresolved"}
                            for d in children[s["id"]]["depends_on"]
                        )
                    ),
                    None,
                )
                if step is None:
                    fault("invalid_input", "Unresolvable teaching dependency")
                child = children[step["id"]]
                if any(by_id[d]["status"] != "accepted" for d in child["depends_on"]):
                    step.update(status="unresolved", reason="dependency_unresolved")
                elif child["material"] is not None:
                    self.s.intake.prepare(key, task, step, child)
                    return True
                elif not child["interfaces"]:
                    step.update(status="unresolved", reason="missing_interface")
                else:
                    self.prepare_child(key, task, step, child)
                self.persist(key, task)
                return True
            run.update(status="running", phase="vocabulary")
            self.persist(key, task)
            return True

    def persist(self, key, task):
        with self.store.db(key) as db, self.store.transaction(db):
            self.save(db, task)

    def prepare_child(self, key, task, step, child):
        run = task["execution"]
        self.valid(key, task, spending=True)
        remaining = min(
            self.rt.config.learning.episode.max_duration_ms, max(1, run["deadline_ms"] - self.s.now())
        )
        cap = min(6000000, self.rt.config.learning.episode.max_work)
        body = {
            "idempotency_key": step["id"],
            "expected_revision": run["context"]["revision_id"],
            "connection_id": run["connection_id"],
            "connection_version": run["connection_version"],
            "allowance_id": task["allowance_id"],
            "publication": run["publication"],
            "task": {
                "description": child["objective"],
                "owner_inputs": [i for i in task["inputs"] if i["id"] in child["input_ids"]],
                **(
                    {
                        "supplied_material": [
                            m
                            for m in self.s.intake.disclosed(key, task)
                            if m["input_id"] in child["input_ids"]
                        ]
                    }
                    if any(i.get("attachments") for i in task["inputs"])
                    else {}
                ),
                "acquisition_contract": child["acquisition_contract"],
            },
            "construction": True,
            "disclose_model": True,
            "limits": {
                "max_calls": 2,
                "max_input_tokens": 2 * max(32000, run["input_bound"]),
                "max_output_tokens": 16384,
                "max_work": cap,
                "max_duration_ms": remaining,
                "no_progress_attempts": 2,
            },
            "call_limits": CallLimits(
                max_input_tokens=max(32000, run["input_bound"]),
                max_output_tokens=min(8192, self.rt.config.learning.call.max_output_tokens),
                max_duration_ms=min(60000, remaining, self.rt.config.learning.call.max_duration_ms),
            ).model_dump(),
        }
        # Persist immutable creation intent before crossing the registry/ADM boundary.
        step.update(status="creating", episode_input=body)
        run["status"] = "running"

    def observe(self, key, task, step):
        run = task["execution"]
        if step["status"] == "creating":
            ep = self.learning.create(key, step["episode_input"], parent_task=task["id"])
            step.update(status="running", episode_id=ep["id"])
            self.persist(key, task)
            return True
        ep = self.learning.episode(key, step["episode_id"])
        if ep["status"] == "awaiting_review":
            receipt = next(r for r in reversed(ep["receipts"]) if r["status"] == "awaiting_review")
            review = {
                "receipt_id": receipt["id"],
                "receipt_sequence": receipt["seq"],
                "candidate_digest": fingerprint(receipt["data"]["package"]),
                "context": run["context"],
                "preview": receipt["data"]["preview"],
                "behaviors": candidate(receipt["data"]["preview"]),
                "expires_at_ms": self.s.now() + 86400000,
            }
            review["digest"] = fingerprint(review)
            run.update(status="awaiting_decision", review=review)
            self.persist(key, task)
            return True
        if ep["status"] not in FINAL:
            return False
        # Publication normally updates task state in the SAME transaction. This also
        # handles an acknowledged episode with no publication, without re-acquiring.
        step.update(
            status="accepted" if ep["status"] == "accepted" else "unresolved",
            reason=ep.get("reason"),
            episode_status=ep["status"],
        )
        self.finance.settle_work(task["allowance_id"], "episode:" + step["id"], ep["work"])
        self.persist(key, task)
        return True

    def cancel_children(self, key, task):
        self.s.intake.cancel(key, task)
        followup = task["execution"].get("followup") or {}
        if followup.get("status") == "pending":
            self.store.cancel_request(key, followup["request_id"])
        for step in task["execution"]["steps"]:
            eid = step.get("episode_id")
            if eid:
                self.learning.cancel(key, eid)

    def vocabulary(self, key, task):
        with self.store.lock:
            task = self.t.get(key, task["id"])
            run = task["execution"]
            self.valid(key, task)
            if run["status"] != "running":
                return False
            if any(s["status"] != "accepted" for s in run["steps"]) or run.get("vocabulary_started"):
                run.update(phase="followup", vocabulary="not_installed_incomplete_or_interrupted")
                self.persist(key, task)
                return True
            vocabulary = task["specification"]["plan"]["vocabulary"]
            operation = task["id"] + "-vocabulary"
            local_until = max(run["deadline_ms"] + 60000, run.get("local_finish_until_ms", 0))
            if self.s.now() >= local_until:
                run.update(phase="followup", vocabulary="not_installed_local_window_expired")
                self.persist(key, task)
                return True
            reservation = run.get("completion_reservations", {}).get("vocabulary") or {
                "operation_id": operation,
                "kind": "local_check",
                "max_work": 1000000,
                "payload_digest": fingerprint({"context": run["context"], "vocabulary": vocabulary}),
            }
            try:
                self.finance.child(task["allowance_id"], reservation)
            except RuntimeFault:
                run.update(phase="followup", vocabulary="not_installed_allowance_unavailable")
                self.persist(key, task)
                return True
            run["vocabulary_started"] = True
            self.persist(key, task)
            captured = run["context"]
        checked = self.rt.language._compute(
            key,
            captured["revision_id"],
            vocabulary,
            "language_vocabulary",
            limits={
                **self.rt.limits(),
                "max_work": min(1000000, self.rt.limits()["max_work"]),
                "max_duration_ms": min(5000, self.rt.limits()["max_duration_ms"]),
            },
        )
        with self.store.lock, self.store.db(key) as db, self.store.transaction(db):
            task = self.t.get(key, task["id"])
            run = task["execution"]
            self.valid(key, task)
            self.finance.settle_work(task["allowance_id"], operation, checked["work"])
            if run["status"] != "running" or run["context"] != captured or self.s.now() >= local_until:
                return True
            generation = captured["vocabulary_generation"] + 1
            if generation > self.store.limits.queue_items_per_adm:
                fault("quota_exceeded", "Vocabulary history allowance exhausted")
            self.store.capacity(len(dumps(vocabulary)) + 4096)
            db.execute("INSERT INTO language_profiles VALUES(?,?)", (generation, dumps(vocabulary)))
            self.store.emit(db, key, "language.vocabulary_changed", key, data={"generation": generation})
            run.update(
                context={**captured, "vocabulary_generation": generation},
                phase="followup",
                vocabulary="installed",
            )
            self.save(db, task)
        return True

    def followup(self, key, task):
        run, gap = task["execution"], task.get("ask_gap")
        if (
            gap
            and not run["followup"]
            and self.s.now() >= max(run["deadline_ms"] + 60000, run.get("local_finish_until_ms", 0))
        ):
            run["followup"] = {
                "status": "expired",
                "text": "The local follow-up window expired. Accepted knowledge is retained; return to Ask for a fresh question.",
            }
        if gap and not gap.get("request_id") and not run["followup"]:
            run["followup"] = {
                "status": "needs_input",
                "text": "The original question has no confirmed local query. Return to Ask to clarify it; no query or provider interpretation was invented.",
            }
        if gap and gap.get("request_id") and any(s["status"] == "accepted" for s in run["steps"]):
            if not run["followup"]:
                original = self.store.request(key, gap["request_id"])
                if original["status"] not in {"needs_input", "waiting_for_learning"}:
                    run["followup"] = {"status": "not_pending", "original_request_id": gap["request_id"]}
                else:
                    envelope = Request(
                        idempotency_key="teach-followup:" + task["id"],
                        query=original["query"],
                        limits={**self.rt.limits(), "max_work": min(1000000, self.rt.limits()["max_work"])},
                        on_gap="report",
                    ).model_dump()
                    reservation = run.get("completion_reservations", {}).get("followup") or {
                        "operation_id": task["id"] + "-followup",
                        "kind": "local_check",
                        "max_work": envelope["limits"]["max_work"],
                        "payload_digest": fingerprint(envelope),
                    }
                    self.finance.child(task["allowance_id"], reservation)
                    with self.store.db(key) as db, self.store.transaction(db):
                        rid = self.store.submit_transaction(
                            db, key, envelope, expected_revision=run["context"]["revision_id"]
                        )
                        run["followup"] = {
                            "status": "pending",
                            "original_request_id": gap["request_id"],
                            "request_id": rid,
                            "context": run["context"],
                        }
                        self.save(db, task)
                    self.rt.coordinator.wake.set()
                    return True
            if run["followup"]["status"] == "pending":
                request = self.store.request(key, run["followup"]["request_id"])
                if request["status"] not in LOCAL_FINAL:
                    return False
                run["followup"].update(
                    status=request["status"], outcome=outcome(request), text=readable(outcome(request))
                )
        # Vocabulary/requirements proposals remain separate proposals. Publication
        # establishes checked definitions; no provider proposal installs owner policy.
        self.summary(task)
        run.update(phase="narration")
        self.persist(key, task)  # intent before provider reservation, never auto-repeat
        try:
            self.narrate(key, task)
        except (RuntimeFault, ValueError):
            run.update(phase="deliver", narration_failure="unavailable_or_exhausted")
            self.persist(key, task)
        return True

    def summary(self, task):
        run = task["execution"]
        for step in run["steps"]:
            if step.get("feed_id"):
                rows = self.s.intake.rows(run["context"]["adm_id"], step["feed_id"])
                step.setdefault("source_progress", {})["accepted"] = sum(
                    r["status"] == "accepted" for r in rows
                )
        accepted = [
            s["id"]
            for s in run["steps"]
            if s["status"] == "accepted" or s.get("source_progress", {}).get("accepted", 0)
        ]
        unresolved = [s["id"] for s in run["steps"] if s["status"] != "accepted"]
        status = (
            run["status"]
            if run["status"] in TERMINAL
            else "succeeded"
            if not unresolved
            else "partially_succeeded"
            if accepted
            else "failed"
        )
        objectives = {c["id"]: c["objective"] for c in task["specification"]["children"]}
        usage = self.finance.view(task["allowance_id"])
        summary = {
            "status": status,
            "accepted_ids": accepted,
            "unresolved_ids": unresolved,
            "accepted": [
                objectives[s["id"]]
                + (
                    f" ({s['source_progress']['accepted']} source items accepted; scope incomplete)"
                    if s["status"] != "accepted"
                    else ""
                )
                for s in run["steps"]
                if s["id"] in accepted
            ],
            "unresolved": [
                {
                    "objective": objectives[s["id"]],
                    "reason": s.get("reason", run.get("reason", "not_completed")),
                }
                for s in run["steps"]
                if s["id"] in unresolved
            ],
            "context": run["context"],
            "followup": run["followup"],
            "stop_reason": run.get("reason"),
            "vocabulary": run.get("vocabulary", "not_installed"),
            "completion_explanation": "available"
            if run.get("narration")
            else "unavailable"
            if run.get("narration_failure") or run["status"] in TERMINAL
            else "pending",
            "completion_explanation_reason": run.get("narration_failure"),
            "spend": {
                k: usage[k]
                for k in ("settled_micro_usd", "reserved_micro_usd", "unknown_micro_usd", "unresolved_calls")
            },
        }
        run["summary"] = summary
        return summary

    def narrate(self, key, task):
        run = task["execution"]
        _, price = self.valid(key, task, spending=True)
        conn = self.learning._usable(run["connection_id"], run["connection_version"], "task_narration")
        packet = run["summary"]
        if len(dumps(packet)) > 32768:
            fault("quota_exceeded", "Completion outcome exceeds bounded explanation packet")
        digest = fingerprint(packet)
        spec = {
            "name": "adm_teaching_completion",
            "instructions": "Explain the supplied checked teaching outcome plainly. Report accepted and unresolved objectives separately. Do not claim external truth, replace local outcomes or propose actions as completed. Return the exact packet digest and accepted/unresolved IDs. Your prose is explanation only.",
            "context": {"packet_digest": digest, "packet": packet},
            "prompt_version": "teaching-completion/1",
            "schema": COMPLETION_SCHEMA,
        }
        raw, estimate = make_wire(conn, spec, 4096)
        prov = provenance(spec, raw)
        operation = task["id"] + "-completion"
        self.finance.child(
            task["allowance_id"],
            {
                "operation_id": operation,
                "kind": "narration",
                "max_work": 0,
                "payload_digest": prov["request_hash"],
            },
        )
        gid = self.learning.reserve(
            {
                "purpose": "task_narration",
                "teaching_task_id": task["id"],
                "operation_id": operation,
                "allowance_id": task["allowance_id"],
                "base_revision": run["context"]["revision_id"],
                "connection_id": conn["id"],
                "connection_version": conn["version"],
                "configuration_digest": conn["configuration_digest"],
                "wire": base64.b64encode(raw).decode(),
                "input_estimate": estimate,
                "limits": CallLimits(
                    max_input_tokens=max(32000, price["input_bound"]), max_output_tokens=4096
                ).model_dump(),
                "provenance": prov,
                "recorded_index": 0,
                "deadline": min(run["deadline_ms"] / 1000, self.learning.now() + 60),
            },
            adm=key,
        )
        run.update(narration_grant_id=gid, packet_digest=digest, narration_packet=packet)
        self.persist(key, task)

    def narration_valid(self, body):
        task = self.t.get(body["adm"], body["teaching_task_id"])
        run = task["execution"]
        if run["status"] != "running" or run["phase"] != "narration":
            fault("stale_context", "Task no longer owns completion narration")
        self.valid(body["adm"], task, spending=True)

    def narrated(self, key, task):
        run = task["execution"]
        if not run.get("narration_grant_id"):
            run.update(phase="deliver", narration_failure="interrupted_handoff")
        else:
            with self.store.db() as registry:
                row = registry.execute(
                    "SELECT outcome FROM grants WHERE id=?", (run["narration_grant_id"],)
                ).fetchone()
            grant = {"outcome": loads(row[0]) if row[0] else None}
            if not grant.get("outcome"):
                return False
            try:
                reply = CompletionReply.model_validate(decode(grant["outcome"]["text"].encode())).model_dump()
                if reply["packet_digest"] != run["packet_digest"] or any(
                    reply[k] != run["summary"][k] for k in ("accepted_ids", "unresolved_ids")
                ):
                    raise ValueError("Narration changed the checked outcome")
                run["narration"] = reply
            except (ValueError, TypeError, KeyError, AttributeError):
                run["narration_failure"] = "invalid_or_failed_narration"
            run["phase"] = "deliver"
        self.persist(key, task)
        return True

    def deliver(self, key, task):
        run = task["execution"]
        if run.get("delivered"):
            return
        summary = self.summary(task)
        text = "Teaching finished. " + (
            "Accepted: " + "; ".join(summary["accepted"]) + ". "
            if summary["accepted"]
            else "No new capability was accepted. "
        )
        if summary["unresolved"]:
            text += (
                "Unresolved: "
                + "; ".join(s["objective"] + " (" + str(s["reason"]) + ")" for s in summary["unresolved"])
                + ". "
            )
        if summary["vocabulary"] != "installed":
            text += "Vocabulary was not installed (" + summary["vocabulary"].replace("_", " ") + "). "
        if not run.get("narration"):
            text += (
                "AI completion explanation was unavailable; this summary reports the saved local outcomes. "
            )
        if (run.get("followup") or {}).get("text"):
            text += run["followup"]["text"]
        with self.store.db(key) as db, self.store.transaction(db):
            fresh = self.t.get(key, task["id"])
            if fresh["execution"].get("delivered"):
                return
            conv = self.s._conversation(db, task["conversation_id"])
            self.s._turn(db, key, conv, "system", text, context=run["context"])
            gap = task.get("ask_gap")
            if gap and (run.get("followup") or {}).get("text"):
                work = loads(self.s._one(db, "chat_work", gap["work_id"])["body"])
                original = self.s._conversation(db, work["conversation_id"])
                self.s._turn(
                    db,
                    key,
                    original,
                    "system",
                    "Teaching completed. Local follow-up: " + run["followup"]["text"],
                    context=run["context"],
                )
            run.update(status=summary["status"], delivered=True, finished_at_ms=self.s.now())
            self.save(db, task)
            self.store.emit(
                db,
                key,
                "teaching.completed",
                task["id"],
                data={
                    "status": run["status"],
                    "accepted": len(summary["accepted"]),
                    "unresolved": len(summary["unresolved"]),
                },
            )
