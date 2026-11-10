"""Owner-reviewed time renewal of an unchanged, unstarted preparation.

Registry accounting and its journal commit together. Applying that journal to the
ADM is idempotent and never starts execution or repeats provider preparation.
"""

from uuid import uuid4

from pydantic import Field

from ..contracts import ClosedModel, Digest, Identifier
from ..conversations.models import Context
from ..learning.service import fault, fingerprint
from ..runtime.protocol import RuntimeFault, dumps, loads


class RenewalInput(ClosedModel):
    idempotency_key: Identifier
    context: Context
    task_digest: Digest
    allowance_digest: Digest
    authority_generation: int = Field(ge=0)
    spending_generation: int = Field(ge=0)
    learning_generation: int = Field(ge=0)
    expires_at_ms: int = Field(gt=0)


class Renewal:
    def __init__(self, teaching):
        self.t, self.s, self.store = teaching, teaching.s, teaching.store
        self.finance = self.s.finance

    def retained(self, key, uid):
        task = self.t.get(key, uid)
        self.s._current(key, task["context"])
        if task.get("execution") or task["status"] not in {"awaiting_review", "prepared"}:
            fault("conflict", "Only an unchanged, unstarted preparation can receive more review time")
        if len(task.get("renewals", [])) >= 8:
            fault("quota_exceeded", "This preparation has reached its eight-renewal limit")
        with self.store.db(key) as db:
            proposal = loads(self.s._one(db, "chat_proposals", task["proposal_id"])["body"])
        if proposal["payload"]["authority_generation"] != self.s._authority():
            fault("stale_context", "Administrator authority changed; prepare a new task")
        if proposal["payload"]["spending_generation"] != self.finance.settings()["generation"]:
            fault("stale_context", "Spending authority changed; prepare a new task")
        return task, proposal

    def preview(self, key, uid):
        with self.store.lock, self.store.db() as db:
            task, _ = self.retained(key, uid)
            row = self.finance.one(db, "allowances", task["allowance_id"])
            allowance = loads(row["body"])
            price = self.finance.price(db, allowance["price_id"])
            self.s.learning._usable(price["connection_id"], price["connection_version"], "task_preparation")
            usage = self.finance.totals(db, allowance["id"])
            if row["state"] != "active" or usage["unresolved_calls"]:
                fault("conflict", "Closed allowances or unsettled calls cannot be renewed")
            expiry = min(self.s.now() + 3600000, price["valid_until_ms"])
            if expiry <= max(self.s.now() + 60000, allowance["expires_at_ms"]):
                fault("conflict", "No additional review time is available within the current price")
            return {
                "command": {
                    "idempotency_key": str(uuid4()),
                    "context": task["context"],
                    "task_digest": fingerprint(task),
                    "allowance_digest": fingerprint(allowance),
                    "authority_generation": self.s._authority(),
                    "spending_generation": self.finance.settings()["generation"],
                    "learning_generation": self.s.learning.settings()["generation"],
                    "expires_at_ms": expiry,
                },
                "previous_expiry_ms": allowance["expires_at_ms"],
                "cap_micro_usd": allowance["cap_micro_usd"],
                "remaining_micro_usd": max(0, allowance["cap_micro_usd"] - usage["settled_micro_usd"]),
                "max_calls": allowance["max_calls"],
                "calls_used": db.execute(
                    "SELECT count(*) FROM charges WHERE allowance_id=?", (allowance["id"],)
                ).fetchone()[0],
            }

    def confirm(self, key, uid, body, principal):
        value = RenewalInput.model_validate(body).model_dump()
        identity = fingerprint({"adm": key, "task": uid, "command": value, "principal": principal})
        idem = "teaching-renewal:" + value["idempotency_key"]
        with self.store.lock:
            with self.store.db() as db, self.store.transaction(db):
                self.finance.checkpoint(db)
                old = db.execute("SELECT * FROM operations WHERE idem=?", (idem,)).fetchone()
                if old:
                    if old["digest"] != identity:
                        fault("conflict", "Renewal identity has different content")
                    operation = old["id"]
                else:
                    task, proposal = self.retained(key, uid)
                    self.s._current(key, value["context"])
                    if (
                        fingerprint(task) != value["task_digest"]
                        or self.s._authority() != value["authority_generation"]
                        or self.finance.settings()["generation"] != value["spending_generation"]
                        or self.s.learning.settings()["generation"] != value["learning_generation"]
                    ):
                        fault("stale_context", "Preparation or authority changed; review renewal again")
                    row = self.finance.one(db, "allowances", task["allowance_id"])
                    allowance = loads(row["body"])
                    price = self.finance.price(db, allowance["price_id"])
                    self.s.learning._usable(
                        price["connection_id"], price["connection_version"], "task_preparation"
                    )
                    expiry = value["expires_at_ms"]
                    if fingerprint(allowance) != value["allowance_digest"] or row["state"] != "active":
                        fault("stale_context", "Allowance changed; review renewal again")
                    if (
                        not max(self.s.now(), allowance["expires_at_ms"])
                        < expiry
                        <= min(self.s.now() + 3600000, price["valid_until_ms"])
                    ):
                        fault("invalid_limits", "Renewal grants at most one hour within the pinned price")
                    if self.finance.totals(db, allowance["id"])["unresolved_calls"]:
                        fault("conflict", "Unsettled calls must be resolved before renewal")
                    if (
                        db.execute("SELECT count(*) FROM operations").fetchone()[0]
                        >= self.store.limits.queue_items_per_adm
                    ):
                        fault("quota_exceeded", "Retained operation limit reached")
                    after = {**allowance, "expires_at_ms": expiry}
                    db.execute("UPDATE allowances SET body=? WHERE id=?", (dumps(after), allowance["id"]))
                    # Restoring expired financial/call/token holds must fit CURRENT installation room.
                    self.finance.valid(db, allowance["id"])
                    for scope in ("installation", "per_adm"):
                        adm = key if scope == "per_adm" else None
                        used = self.s.learning.usage_snapshot(db, adm=adm)
                        lane = self.s.learning.usage_snapshot(db, adm=adm, lane="learning")
                        held = self.finance.summary_holds(db, adm=adm)
                        for field in ("calls", "input_tokens", "output_tokens"):
                            cap = getattr(self.s.learning.config.learning.quotas, field + "_" + scope)
                            if used[field] + held[field] > cap or lane[field] + held[field] > max(
                                1, cap * 60 // 100
                            ):
                                fault(
                                    "quota_exceeded", "Renewal cannot restore protected completion capacity"
                                )
                    operation = str(uuid4())
                    replacement = {**proposal, "id": str(uuid4()), "expires_at_ms": expiry}
                    journal = {
                        "task_id": uid,
                        "command": value,
                        "principal": principal,
                        "allowance_before": allowance,
                        "allowance_after": after,
                        "replacement_proposal": replacement if task["status"] == "awaiting_review" else None,
                        "original_proposal_id": proposal["id"],
                    }
                    self.store.capacity(len(dumps(journal)) * 3 + 32768)
                    db.execute(
                        "INSERT INTO operations(id,idem,digest,kind,adm,body,status,created) VALUES(?,?,?,'teaching_renewal',?,?,'committed',?)",
                        (operation, idem, identity, key, dumps(journal), self.s.now() / 1000),
                    )
            return self.apply(key, operation)

    def apply(self, key, operation):
        with self.store.lock, self.store.db() as registry:
            row = registry.execute("SELECT * FROM operations WHERE id=?", (operation,)).fetchone()
            journal = loads(row["body"])
            if row["status"] != "committed":
                return loads(row["result"])
            task = self.t.get(key, journal["task_id"])
            command = journal["command"]
            result = {
                "operation_id": operation,
                "task_id": task["id"],
                "status": "renewed",
                "expires_at_ms": command["expires_at_ms"],
            }
            try:
                if operation not in task.get("renewals", []):
                    self.s._current(key, command["context"])
                    if (
                        fingerprint(task) != command["task_digest"]
                        or self.s._authority() != command["authority_generation"]
                        or self.finance.settings()["generation"] != command["spending_generation"]
                        or self.s.learning.settings()["generation"] != command["learning_generation"]
                        or self.s.now() >= command["expires_at_ms"]
                    ):
                        fault("stale_context", "Renewal cannot be applied after context or authority changes")
                    task["renewals"] = [*task.get("renewals", []), operation]
                    task["budget"] = {**task["budget"], "expires_at_ms": command["expires_at_ms"]}
                    with self.store.db(key) as db, self.store.transaction(db):
                        replacement = journal["replacement_proposal"]
                        if replacement:
                            db.execute(
                                "UPDATE chat_proposals SET status='superseded' WHERE id=?",
                                (journal["original_proposal_id"],),
                            )
                            db.execute(
                                "INSERT INTO chat_proposals VALUES(?,?,'pending',?)",
                                (replacement["id"], task["conversation_id"], dumps(replacement)),
                            )
                            task["proposal_id"] = replacement["id"]
                        self.t.save(db, task)
                        conv = self.s._conversation(db, task["conversation_id"])
                        self.s._turn(
                            db,
                            key,
                            conv,
                            "system",
                            "More review time is authorized for the same saved preparation and remaining allowance. Previous charges and all cost, call, token and work caps are unchanged. Review the preparation and choose Start teaching separately; no provider call or learning was started.",
                        )
                        self.store.emit(
                            db, key, "teaching.renewed", task["id"], data={"operation_id": operation}
                        )
            except RuntimeFault:
                result["status"] = "stale"
            with self.store.transaction(registry):
                registry.execute(
                    "UPDATE operations SET status=?,result=? WHERE id=?",
                    ("succeeded" if result["status"] == "renewed" else "failed", dumps(result), operation),
                )
            return result

    def recover(self, key):
        with self.store.db() as db:
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM operations WHERE adm=? AND kind='teaching_renewal' AND status='committed' ORDER BY rowid",
                    (key,),
                )
            ]
        for uid in ids:
            self.apply(key, uid)
