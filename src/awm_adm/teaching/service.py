"""Durable teaching preparation followed by checked automatic execution."""

import base64
import threading

from ..learning.diagnostics import capacity_diagnostic
from ..learning.service import fault, fingerprint
from ..llm_limits import captured_call
from ..providers.wire import make_wire, provenance
from ..runtime.protocol import RuntimeFault, dumps, loads
from .diagnostics import PreparationError
from .materials import manifest
from .prompt import ASSESSED_PROMPT_FORMATS, NATIVE_PROMPT_VERSIONS, TEMPORAL_PROMPT_VERSIONS, specification
from .provider_format import MATERIAL_PROFILE, PROFILE, SHARED_PROFILE, TEMPORAL_PROFILE
from .review import headers


class Teaching:
    def __init__(self, conversations):
        self.s, self.rt, self.store = conversations, conversations.runtime, conversations.store
        self.lock = threading.Lock()
        self.position = 0
        from .execution import Execution

        self.execution = Execution(self)

    def get(self, key, uid):
        with self.store.db(key) as db:
            return loads(self.s._one(db, "teaching_tasks", uid)["body"])

    def listing(self, key, after=0, limit=20, *, cid=None):
        with self.store.db(key) as db:
            rows = db.execute(
                "SELECT seq,body FROM teaching_tasks WHERE seq>? AND (? IS NULL OR conversation=?) ORDER BY seq LIMIT ?",
                (after, cid, cid, limit),
            ).fetchall()
        return {
            "items": [
                {
                    k: self.execution.view(v) if k == "execution" else v
                    for k, v in loads(r["body"]).items()
                    if k
                    in {
                        "id",
                        "conversation_id",
                        "context",
                        "status",
                        "objective",
                        "summary",
                        "allowance_id",
                        "created_at_ms",
                        "prepared_at_ms",
                        "specification_digest",
                        "failure_code",
                        "failure_diagnostics",
                        "execution",
                        "source_queue",
                        "source_review",
                        "budget",
                        "renewals",
                    }
                }
                for r in rows
            ],
            "next_cursor": rows[-1]["seq"] if rows else after,
        }

    def save(self, db, task):
        db.execute(
            "UPDATE teaching_tasks SET status=?,body=? WHERE id=?", (task["status"], dumps(task), task["id"])
        )

    def direct_task(self, db, key, conv, work, turn, previous):
        prior = None
        if previous:
            candidate = self.get(key, previous["preferences"]["task_id"])
            if (
                (
                    candidate["status"] in {"needs_input", "unsupported"}
                    or (
                        candidate["status"] == "failed"
                        and candidate.get("failure_code") == "invalid_preparation"
                    )
                )
                and not candidate.get("execution")
                and candidate.get("failure_code") not in {"outcome_unknown", "stale_context", "cancelled"}
            ):
                prior = candidate
        inputs = list(prior["inputs"]) if prior else []
        inputs.append(
            {
                "id": turn["id"],
                "text": turn["text"],
                **({"knowledge_intent": work["knowledge_intent"]} if work.get("knowledge_intent") else {}),
                **({"attachments": self.s.intake.inputs(db, key, turn)} if turn["attachment_ids"] else {}),
            }
        )
        if len(inputs) > 4 or len(dumps(inputs)) > 24576:
            fault(
                "needs_specification",
                "Please restate the teaching request with its necessary details in one message",
            )
        task = {
            "profile": "awm-adm-teaching-task/2",
            "direct": True,
            "id": work["id"],
            "conversation_id": conv["id"],
            "context": work["context"],
            "status": "preparing",
            "objective": prior["objective"] if prior else turn["text"],
            "inputs": inputs,
            "question": work.get("question"),
            "source_queue": work["preferences"].get("source_queue", False),
            "preferences": work["preferences"],
            "created_at_ms": self.s.now(),
            "llm_limits": work["llm_limits"],
            "catalog_predicate_limit": work.get("catalog_predicate_limit", 65_536),
            "episode_policy": work["episode_policy"],
            "deadline_ms": work["deadline_ms"],
            "ask_gap": None,
            "specification": None,
            "execution_authorized": False,
            "intent_authority": "local_teach_submission",
            "source_context_profile": "awm-adm-selected-material/1",
            "previous_task_id": prior["id"] if prior else None,
        }
        task["material_manifest"] = {
            "lineage_id": prior.get("material_manifest", {}).get("lineage_id", prior["id"])
            if prior
            else task["id"]
        }
        task["material_manifest"] = manifest(db, key, task)
        db.execute(
            "INSERT INTO teaching_tasks(id,conversation,status,body) VALUES(?,?,?,?)",
            (task["id"], conv["id"], task["status"], dumps(task)),
        )

    def stop(self, key, work, status, code=None):
        task = self.get(key, work["preferences"]["task_id"])
        if task["specification"] is None:
            task.update(status=status, failure_code=code)
            if work.get("failure_diagnostics"):
                task["failure_diagnostics"] = work["failure_diagnostics"]
            if work.get("preparation_assessment"):
                task["preparation_assessment"] = work["preparation_assessment"]
            with self.store.db(key) as db, self.store.transaction(db):
                self.save(db, task)

    def compute(self, key, work, operation, **extra):
        meta = self.rt.language.vocabulary(key)
        return self.rt.language._compute(
            key,
            work["context"]["revision_id"],
            meta["vocabulary"],
            operation,
            limits={
                **self.rt.limits(),
                "max_work": min(1000000, self.rt.limits()["max_work"]),
                "max_duration_ms": min(5000, self.rt.limits()["max_duration_ms"]),
            },
            **extra,
        )

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
                        "SELECT body FROM chat_work WHERE status IN ('queued','awaiting_provider') ORDER BY seq LIMIT 100"
                    ).fetchall()
                for row in rows:
                    work = loads(row[0])
                    if work.get("flow") != "teach":
                        continue
                    try:
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
                        outcome = loads(grant["outcome"])
                        if outcome["status"] != "succeeded":
                            from .provider_failure import preparation_failure

                            diagnostic = preparation_failure(
                                work["grant_id"], outcome, loads(grant["body"])["limits"]
                            )
                            work.update(failure_code=diagnostic["code"], failure_diagnostics=diagnostic)
                            self.stop(key, work, "failed", diagnostic["code"])
                            self.s._finish(key, work, "failed", diagnostic["message"])
                            return True
                        with self.store.lock:
                            self.rt.learning._grant_valid(loads(grant["body"]))
                        task = self.get(key, work["preferences"]["task_id"])
                        checked = self.compute(
                            key,
                            work,
                            "teaching_check",
                            provider_text=outcome.get("text", ""),
                            input_ids=[i["id"] for i in task["inputs"]],
                            material_manifest=task.get("material_manifest"),
                            reply_format=(
                                ASSESSED_PROMPT_FORMATS[work["provenance"]["prompt_version"]]
                                if work["provenance"]["prompt_version"] in ASSESSED_PROMPT_FORMATS
                                else TEMPORAL_PROFILE
                                if work["provenance"]["prompt_version"] in TEMPORAL_PROMPT_VERSIONS
                                else SHARED_PROFILE
                                if work["provenance"]["prompt_version"] == "adm-teaching-preparation/9"
                                else MATERIAL_PROFILE
                                if work["provenance"]["prompt_version"] == "adm-teaching-preparation/8"
                                else PROFILE
                                if work["provenance"]["prompt_version"] in NATIVE_PROMPT_VERSIONS
                                else None
                                if work["provenance"]["prompt_version"]
                                in {"adm-teaching-preparation/1", "adm-teaching-preparation/2"}
                                else "unsupported"
                            ),
                        )
                        if "failure" in checked:
                            self.reject(key, work, task, checked)
                        else:
                            self.complete(key, work, task, checked)
                        return True
                    except (RuntimeFault, ValueError, TypeError, KeyError) as error:
                        code = error.code if isinstance(error, RuntimeFault) else "invalid_preparation"
                        if isinstance(error, PreparationError):
                            work["failure_diagnostics"] = error.diagnostic
                        work["failure_code"] = code
                        if diagnostic := capacity_diagnostic(error):
                            work["failure_diagnostics"] = diagnostic
                        self.stop(key, work, "failed", code)
                        self.s._finish(
                            key,
                            work,
                            "failed",
                            "Teaching could not start: " + str(error) + ". No new knowledge was accepted.",
                        )
                        return True
            return False
        finally:
            self.lock.release()

    def prepare(self, key, work):
        task = self.get(key, work["preferences"]["task_id"])
        checked = self.compute(key, work, "teaching_catalog")
        spec = specification(task, checked["catalog"], checked["requirements"], self.rt.sources.policy(key))
        work["temporal_context"] = spec["context"]["temporal_context"]
        spec["context"]["supplied_material"] = self.s.intake.disclosed(key, task)
        with self.store.lock:
            self.s.grant_valid({"adm": key, "conversation_work_id": work["id"]})
            conn = self.rt.interactions.connection_for(work, "task_preparation")
            limits = captured_call(work)
            raw, estimate = make_wire(conn, spec, limits["max_output_tokens"])
            if len(raw) > self.rt.config.server.max_body_bytes:
                fault("resource_exhausted", "The teaching context is too large for one preparation")
            prov = provenance(spec, raw)
            gid = self.rt.learning.reserve(
                {
                    "purpose": "task_preparation",
                    "conversation_work_id": work["id"],
                    "operation_id": work["id"],
                    "base_revision": work["context"]["revision_id"],
                    "connection_id": conn["id"],
                    "connection_version": conn["version"],
                    "configuration_digest": conn["configuration_digest"],
                    "wire": base64.b64encode(raw).decode(),
                    "input_estimate": estimate,
                    "limits": limits,
                    "provenance": prov,
                    "recorded_index": 0,
                    "deadline": work["deadline_ms"] / 1000,
                },
                adm=key,
            )
            work.update(
                status="awaiting_provider", grant_id=gid, provenance=prov, catalog_work=checked["work"]
            )
            work["links"].append({"kind": "provider_grant", "id": gid})
            with self.store.db(key) as db, self.store.transaction(db):
                self.s._save_work(db, key, work, "conversation.queued")

    def reject(self, key, work, task, checked):
        # A known checked rejection settles only measured local work. Provider
        # charges have their separate durable outcome; no second call is made.
        with self.store.lock:
            self.s.grant_valid({"adm": key, "conversation_work_id": work["id"]})
            work["failure_code"] = "invalid_preparation"
            work["failure_diagnostics"] = checked["failure"]
            self.stop(key, work, "failed", "invalid_preparation")
            self.s._finish(
                key,
                work,
                "failed",
                checked["failure"]["message"] + " No configuration was installed and no learning started. "
                "The call usage is recorded. This is a preparation error, not a request for you to repair internal fields.",
            )

    def complete(self, key, work, task, checked):
        reply = checked["reply"]
        if work.get("temporal_context"):
            task["temporal_context"] = work["temporal_context"]
        with self.store.lock:
            self.s.grant_valid({"adm": key, "conversation_work_id": work["id"]})
            if reply.get("assessment"):
                task["preparation_assessment"] = reply["assessment"]
                work["preparation_assessment"] = reply["assessment"]
            if reply["status"] != "ready":
                status = "needs_input" if reply["status"] == "needs_clarification" else "unsupported"
                self.stop(key, work, status)
                self.s._finish(
                    key,
                    work,
                    status,
                    reply["message"],
                    {
                        "kind": "clarification" if status == "needs_input" else "unavailable",
                        "text": reply["message"],
                    },
                )
                return
            plan = checked["plan"]
            spec = {
                "profile": "awm-adm-teaching-specification/2",
                "task_id": task["id"],
                "context": task["context"],
                "objective": task["objective"],
                "inputs": task["inputs"],
                "ask_gap": task["ask_gap"],
                "source_queue": task.get("source_queue", False),
                "plan": plan,
                "interface_review": headers(plan),
                "children": [
                    {
                        "id": task["id"] + f"-child-{i + 1}",
                        **child,
                        "acquisition_contract": contract,
                        "preserve_declarations": checked["preserve_declarations"][i],
                        "reaffirm_declarations": checked["reaffirm_declarations"][i],
                        "depends_on": [
                            task["id"] + f"-child-{parent + 1}" for parent in checked["dependencies"][i]
                        ],
                        **(
                            {"material_ids": checked["material_bindings"][i]}
                            if "material_bindings" in checked
                            else {}
                        ),
                    }
                    for i, (child, contract) in enumerate(
                        zip(plan["children"], checked["contracts"], strict=True)
                    )
                ],
                "repair_policy": {
                    "max_attempts": 2,
                    "automatic_retry_unknown": False,
                    "scope_expansion": False,
                },
                "owner_requirements_digest": checked["owner_requirements_digest"],
                "requirements_authority": "uninstalled_proposal",
                "source_policy_authority": "uninstalled_proposal",
                "execution_authorized": False,
            }
            if plan.get("requirements") is not None:
                self.stop(key, work, "needs_input", "independent_requirements")
                self.s._finish(
                    key,
                    work,
                    "needs_input",
                    "Independent acceptance requirements need an explicit policy decision. This teaching request has not changed them.",
                    {
                        "kind": "clarification",
                        "text": "Should I teach the domain rules without changing the model’s independent acceptance requirements?",
                    },
                )
                return
            task.update(
                status="prepared",
                summary=plan["summary"],
                specification=spec,
                specification_digest=fingerprint(spec),
                prepared_at_ms=self.s.now(),
                preparation_assurance="local_structure_and_scope_checked",
            )
            # Verify selected-material scope before changing the exchange state.
            task["execution"] = {
                "connection_id": task["preferences"]["connection_id"],
                "connection_version": task["preferences"]["connection_version"],
            }
            try:
                self.s.intake.start_check(key, task, {"source_consent": True})
            except (RuntimeFault, PreparationError) as error:
                task.pop("execution")
                code = error.code if isinstance(error, RuntimeFault) else "invalid_preparation"
                # Retain the bounded checked proposal for diagnosis, never execution.
                task["failed_specification"] = task["specification"]
                if diagnostic := capacity_diagnostic(error):
                    task["failure_diagnostics"] = diagnostic
                    work["failure_diagnostics"] = diagnostic
                if isinstance(error, PreparationError):
                    task["failure_diagnostics"] = error.diagnostic
                    work["failure_diagnostics"] = error.diagnostic
                task.update(
                    status="unsupported"
                    if code == "unsupported"
                    else "needs_input"
                    if code == "needs_specification"
                    else "failed",
                    specification=None,
                    failure_code=code,
                )
                work["failure_code"] = code
                with self.store.db(key) as db:
                    self.save(db, task)
                self.s._finish(
                    key,
                    work,
                    task["status"],
                    str(error) + " No new knowledge was accepted.",
                    {"kind": "clarification", "text": str(error)}
                    if task["status"] == "needs_input"
                    else None,
                )
                return
            task.pop("execution")
            with self.store.db(key) as db, self.store.transaction(db):
                self.save(db, task)
                work.update(status="prepared", task_id=task["id"], finished_at_ms=self.s.now())
                self.s._save_work(db, key, work, "conversation.completed")
            # The authenticated Teach submission authorizes ordinary execution;
            # no fabricated human review or independent owner policy is recorded.
            self.execution.command(
                key,
                task["id"],
                {
                    "idempotency_key": "direct-start:" + task["id"],
                    "specification_digest": task["specification_digest"],
                    "context": task["context"],
                    "expected_version": 0,
                    "action": "start",
                    "source_consent": True,
                },
                "local_teach_submission",
            )
