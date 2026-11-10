"""Durable, funded teaching preparation. No episode, source job or publication."""

import base64
import threading
from uuid import uuid4

from ..contracts import CallLimits
from ..learning.service import fault, fingerprint
from ..providers.wire import make_wire, provenance
from ..runtime.protocol import RuntimeFault, dumps, loads
from .prompt import NATIVE_PROMPT_VERSIONS, specification
from .provider_format import PROFILE
from .review import headers


class Teaching:
    def __init__(self, conversations):
        self.s, self.rt, self.store = conversations, conversations.runtime, conversations.store
        self.lock = threading.Lock()
        self.position = 0
        from .execution import Execution

        self.execution = Execution(self)
        from .renewal import Renewal

        self.renewal = Renewal(self)

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

    def allocated(self, db, key, conv, payload, allowance):
        uid = payload["task_id"]
        if db.execute("SELECT 1 FROM teaching_tasks WHERE id=?", (uid,)).fetchone():
            return
        task = {
            "profile": "awm-adm-teaching-task/1",
            "id": uid,
            "conversation_id": conv["id"],
            "context": self.s.context(key),
            "status": "preparing",
            "objective": None,
            "inputs": [],
            "allowance_id": allowance["id"],
            "budget": {
                k: payload[k]
                for k in (
                    "cap_micro_usd",
                    "price_id",
                    "expires_at_ms",
                    "max_calls",
                    "max_input_tokens",
                    "max_output_tokens",
                    "max_children",
                    "max_work",
                )
            },
            "source_queue": bool(payload.get("source_queue")),
            "created_at_ms": self.s.now(),
            "ask_gap": conv.get("ask_gap"),
            "specification": None,
            "execution_authorized": False,
        }
        db.execute(
            "INSERT INTO teaching_tasks(id,conversation,status,body) VALUES(?,?,?,?)",
            (uid, conv["id"], task["status"], dumps(task)),
        )

    def begin(self, db, key, conv, turn, question):
        task = loads(self.s._one(db, "teaching_tasks", conv["preferences"]["task_id"])["body"])
        if task["specification"] is not None or task["status"] not in {"preparing", "needs_input"}:
            fault("conflict", "This task is already prepared or stopped; set up a new teaching task")
        if task["context"] != turn["context"]:
            fault("stale_context", "Teaching scope changed; set up a fresh task")
        if len(task["inputs"]) >= 4 or sum(len(dumps(i)) for i in task["inputs"]) + len(dumps(turn)) > 24576:
            fault("quota_exceeded", "Teaching preparation is limited to four input turns and 24 KiB")
        task["inputs"].append(
            {
                "id": turn["id"],
                "text": turn["text"],
                **({"attachments": self.s.intake.inputs(db, key, turn)} if turn["attachment_ids"] else {}),
            }
        )
        task["objective"] = task["objective"] or turn["text"]
        task["question"] = question["question"] if question else None
        task["status"] = "preparing"
        self.save(db, task)

    def stop(self, key, work, status, code=None):
        task = self.get(key, work["preferences"]["task_id"])
        if task["specification"] is None:
            task.update(status=status, failure_code=code)
            if work.get("failure_diagnostics"):
                task["failure_diagnostics"] = work["failure_diagnostics"]
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
                            fault("provider_unavailable", "Teaching provider response failed")
                        with self.store.lock:
                            self.rt.learning._grant_valid(loads(grant["body"]))
                        task = self.get(key, work["preferences"]["task_id"])
                        checked = self.compute(
                            key,
                            work,
                            "teaching_check",
                            provider_text=outcome.get("text", ""),
                            input_ids=[i["id"] for i in task["inputs"]],
                            reply_format=(
                                PROFILE
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
                        work["failure_code"] = code
                        self.stop(key, work, "failed", code)
                        self.s._finish(
                            key,
                            work,
                            "failed",
                            "Teaching preparation stopped: the proposal, model context, provider or allowance could not pass local checks. No configuration was installed and no learning started. Review Details; a new preparation needs a fresh explicit setup.",
                        )
                        return True
            return False
        finally:
            self.lock.release()

    def prepare(self, key, work):
        task = self.get(key, work["preferences"]["task_id"])
        self.s.finance.child(
            task["allowance_id"],
            {
                "operation_id": work["id"] + "-check",
                "kind": "local_check",
                "max_work": 2000000,
                "max_duration_ms": 10000,
                "payload_digest": fingerprint(
                    {"task": task["id"], "context": work["context"], "inputs": task["inputs"]}
                ),
            },
        )
        checked = self.compute(key, work, "teaching_catalog")
        spec = specification(task, checked["catalog"], checked["requirements"], self.rt.sources.policy(key))
        spec["context"]["supplied_material"] = self.s.intake.disclosed(key, task)
        with self.store.lock:
            self.s.grant_valid({"adm": key, "conversation_work_id": work["id"]})
            with self.store.db() as db:
                allowance, price = self.s.finance.valid(db, task["allowance_id"])
            if (
                allowance["scope"] != ("source" if task.get("source_queue") else "task")
                or allowance["scope_id"] != task["id"]
                or allowance["adm_id"] != key
            ):
                fault("forbidden", "Teaching allowance belongs to another task")
            conn = self.rt.learning._usable(
                price["connection_id"], price["connection_version"], "task_preparation"
            )
            raw, estimate = make_wire(conn, spec, 8192)
            prov = provenance(spec, raw)
            self.s.finance.child(
                allowance["id"],
                {
                    "operation_id": work["id"],
                    "kind": "preparation",
                    "max_work": 0,
                    "payload_digest": prov["request_hash"],
                },
            )
            gid = self.rt.learning.reserve(
                {
                    "purpose": "task_preparation",
                    "conversation_work_id": work["id"],
                    "operation_id": work["id"],
                    "allowance_id": allowance["id"],
                    "base_revision": work["context"]["revision_id"],
                    "connection_id": conn["id"],
                    "connection_version": conn["version"],
                    "configuration_digest": conn["configuration_digest"],
                    "wire": base64.b64encode(raw).decode(),
                    "input_estimate": estimate,
                    "limits": CallLimits(
                        max_input_tokens=max(32000, price["input_bound"]), max_output_tokens=8192
                    ).model_dump(),
                    "provenance": prov,
                    "recorded_index": 0,
                    "deadline": min(work["deadline_ms"] / 1000, self.rt.learning.now() + 60),
                },
                adm=key,
            )
            work.update(
                status="awaiting_provider", grant_id=gid, provenance=prov, catalog_work=checked["work"]
            )
            work["links"].append({"kind": "provider_grant", "id": gid})
            with self.store.db(key) as db, self.store.transaction(db):
                self.s._save_work(db, key, work, "conversation.queued")
        # The remainder stays reserved until proposal validation or a failure.

    def reject(self, key, work, task, checked):
        # A known checked rejection settles only measured local work. Provider
        # charges have their separate durable outcome; no second call is made.
        with self.store.lock:
            self.s.grant_valid({"adm": key, "conversation_work_id": work["id"]})
            self.s.finance.settle_work(
                task["allowance_id"], work["id"] + "-check", checked["work"] + work["catalog_work"]
            )
            work["failure_code"] = "invalid_preparation"
            work["failure_diagnostics"] = checked["failure"]
            self.stop(key, work, "failed", "invalid_preparation")
            self.s._finish(
                key,
                work,
                "failed",
                checked["failure"]["message"] + " No configuration was installed and no learning started. "
                "This call's usage remains recorded. No automatic retry; review Details before a new explicit setup.",
            )

    def complete(self, key, work, task, checked):
        reply = checked["reply"]
        with self.store.lock:
            self.s.grant_valid({"adm": key, "conversation_work_id": work["id"]})
            self.s.finance.settle_work(
                task["allowance_id"], work["id"] + "-check", checked["work"] + work["catalog_work"]
            )
            if reply["status"] != "ready":
                status = "needs_input" if reply["status"] == "needs_clarification" else "unsupported"
                self.stop(key, work, status)
                self.s._finish(
                    key,
                    work,
                    status,
                    "Preparation only; no model change or learning has started.",
                    {
                        "kind": "clarification" if status == "needs_input" else "unavailable",
                        "text": reply["message"],
                    },
                )
                return
            plan = checked["plan"]
            spec = {
                "profile": "awm-adm-teaching-specification/1",
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
                        "depends_on": [
                            task["id"] + f"-child-{parent + 1}" for parent in checked["dependencies"][i]
                        ],
                    }
                    for i, (child, contract) in enumerate(
                        zip(plan["children"], checked["contracts"], strict=True)
                    )
                ],
                "allowance_id": task["allowance_id"],
                "budget": task["budget"],
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
            payload = {
                "operation": "teaching_specification",
                "task_id": task["id"],
                "specification": spec,
                "authority_generation": self.s._authority(),
                "spending_generation": self.s.finance.settings()["generation"],
            }
            proposal = {
                "profile": "awm-adm-v3-proposal/0.1",
                "id": str(uuid4()),
                "turn_id": work["turn_id"],
                "context": work["context"],
                "kind": "task",
                "payload_digest": fingerprint(payload),
                "expires_at_ms": min(self.s.now() + 600000, task["budget"]["expires_at_ms"]),
                "payload": payload,
            }
            self.store.capacity(len(dumps(payload)) * 3 + 32768)
            task.update(status="awaiting_review", summary=plan["summary"], proposal_id=proposal["id"])
            with self.store.db(key) as db, self.store.transaction(db):
                self.save(db, task)
                db.execute(
                    "INSERT INTO chat_proposals VALUES(?,?,?,?)",
                    (proposal["id"], task["conversation_id"], "pending", dumps(proposal)),
                )
                conv = self.s._conversation(db, task["conversation_id"])
                self.s._turn(
                    db,
                    key,
                    conv,
                    "system",
                    "The teaching specification passed structural and finite-scope checks. Review the proposed meaning and coverage below. Saving it does not install requirements, disclose sources, start learning or change the model.",
                )
                work.update(status="awaiting_review", task_id=task["id"], finished_at_ms=self.s.now())
                self.s._save_work(db, key, work, "conversation.completed")

    def apply(self, key, decision, proposal, cid):
        payload = proposal["payload"]
        task = self.get(key, payload["task_id"])
        status = "declined"
        try:
            if decision["answer"] == "accept":
                self.s._current(key, decision["context"])
                if (
                    self.s.now() >= proposal["expires_at_ms"]
                    or self.s._authority() != payload["authority_generation"]
                    or self.s.finance.settings()["generation"] != payload["spending_generation"]
                ):
                    fault("stale_context", "Teaching decision expired")
                with self.store.db() as db:
                    self.s.finance.valid(db, task["allowance_id"])
                if task["status"] != "awaiting_review" or task["proposal_id"] != proposal["id"]:
                    fault("stale_context", "Teaching proposal changed")
                task.update(
                    status="prepared",
                    specification=payload["specification"],
                    specification_digest=fingerprint(payload["specification"]),
                    decision_id=decision["id"],
                    prepared_at_ms=self.s.now(),
                )
                task["source_review"] = self.s.intake.scope_review(task)
                status = "accepted"
        except RuntimeFault:
            status = "stale"
        if status != "accepted":
            task["status"] = status
        decision = {**decision, "status": status}
        with self.store.db(key) as db, self.store.transaction(db):
            self.save(db, task)
            for row in db.execute(
                "SELECT body FROM chat_work WHERE conversation=? AND status='awaiting_review'", (cid,)
            ).fetchall():
                work = loads(row[0])
                if work.get("task_id") == task["id"]:
                    work["status"] = "prepared" if status == "accepted" else status
                    self.s._save_work(db, key, work, "conversation.completed")
            db.execute(
                "UPDATE chat_decisions SET status=?,body=? WHERE id=?",
                (status, dumps(decision), decision["id"]),
            )
            db.execute("UPDATE chat_proposals SET status=? WHERE id=?", (status, proposal["id"]))
            conv = self.s._conversation(db, cid)
            self.s._turn(
                db,
                key,
                conv,
                "system",
                "Teaching task prepared and saved. Choose Start teaching to review and authorize execution within the remaining task allowance. The model, owner requirements and source permissions are unchanged. Preparation costs remain in this task's learning allowance."
                if status == "accepted"
                else "The teaching specification was not approved with current authority. No learning started; reserved usage remains accounted for.",
            )
            self.store.emit(
                db,
                key,
                "teaching.prepared" if status == "accepted" else "teaching.stopped",
                task["id"],
                data={"status": task["status"]},
            )
        return decision
