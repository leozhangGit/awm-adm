"""Bounded scheduler for durable local requests and model operations."""

import hashlib
import threading
import time
from uuid import uuid4

from ..contracts import Request, Result
from ..engine.artifacts import digest
from ..engine.data import encode
from ..engine.execution import normalize_query
from ..engine.results import semantic_query
from ..runtime.protocol import RuntimeFault, dumps, loads
from .store import context_binding, failure


def wrap_result(key, lease, value):
    query = lease["envelope"]["query"]
    context = lease["context"]
    b = value.get("binding", {})
    body = {k: v for k, v in b.items() if k != "digest"}
    if (
        b.get("profile") != "adm-result/0.1"
        or b.get("theory_version") != context["theory_version"]
        or encode(b.get("query")) != encode(semantic_query(query))
        or b.get("digest") != digest(encode(body))
    ):
        raise RuntimeFault("invalid_result", "Local result does not match pinned query")
    if value.get("status") not in {"succeeded", "inconclusive", "needs_input"}:
        raise RuntimeFault("invalid_result", "Invalid local result status")
    if value["status"] != "succeeded":
        return None
    scope = value.get("scope") or {}
    actions = scope.get("transitions", [])
    selection = {"kind": "not_applicable", "actions": None}
    if query["op"] == "find_plan":
        explicit = query.get("transitions")
        selection = {
            "kind": "module_all" if explicit is None else "explicit",
            "actions": sorted(explicit) if explicit is not None else None,
        }
    elif query["op"] == "check_certificate":
        selection = {"kind": "explicit", "actions": sorted(query["certificate"]["transitions"])}
    claims = []
    names = {c["claim"] for c in value.get("assurance", {}).get("claims", []) if c["status"] == "established"}
    for source, dest in [
        ("computed_value", "value"),
        ("plan_valid", "valid_witness"),
        ("shortest_action_count", "shortest_action_count"),
        ("unreachable", "unreachable"),
        ("no_plan_within_depth", "no_plan_within_bound"),
    ]:
        if source in names:
            claims.append(dest)
    finite = (
        "checked"
        if value.get("guarantee") == "exhaustive_finite"
        or value.get("correspondence", {}).get("guarantee") == "exhaustive_finite"
        else "not_checked"
    )
    lean = "checked" if value.get("checker", {}).get("guarantee") == "lean_kernel" else "not_requested"
    return Result(
        result_id=str(uuid4()),
        binding={
            "context": context_binding(context),
            "request_id": lease["id"],
            "attempt_id": lease["attempt"],
            "query_digest": digest(encode(semantic_query(query))),
            "selection": selection,
            "resolved_actions": actions,
        },
        value=value,
        claims=claims,
        lean_kernel=lean,
        exhaustive_finite=finite,
        empirical_fidelity=value.get("assurance", {}).get("empirical_fidelity", "not_established"),
    ).model_dump()


class Coordinator:
    def __init__(self, runtime, *, start=True):
        self.runtime = runtime
        self.store = runtime.store
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.lock = threading.RLock()
        self.active = {}
        self.threads = []
        if start:
            for i in range(runtime.config.runtime.serving_processes):
                thread = threading.Thread(target=self.loop, name=f"adm-scheduler-{i}", daemon=True)
                self.threads.append(thread)
                thread.start()

    def submit(self, key, body, *, expected_revision=None):
        parsed = Request.model_validate(body).model_dump()
        parsed["limits"] = self.runtime.limits(parsed["limits"])
        if parsed["query"]["op"] != "lookup_fact":
            parsed["query"] = normalize_query(parsed["query"], parsed["limits"])
        uid = self.store.submit(key, parsed, expected_revision=expected_revision)
        self.wake.set()
        return self.store.request(key, uid)

    def cancel(self, key, uid):
        result = self.store.cancel_request(key, uid)
        with self.lock:
            event = self.active.get((key, uid))
            if event:
                event.set()
        return result

    def changed(self, key):
        with self.lock:
            for (adm, _uid), event in self.active.items():
                if adm == key and self.store.request(adm, _uid)["status"] != "evaluating":
                    event.set()

    def perform(self, key, lease):
        cancel = threading.Event()
        with self.lock:
            self.active[(key, lease["id"])] = cancel
            if self.stopping.is_set():
                cancel.set()
        try:
            # Cancellation may have committed before this child was registered.
            if self.store.request(key, lease["id"])["status"] != "evaluating":
                return
            rev = self.store.revision(key, lease["revision"])
            body = lease["envelope"]
            task = {
                "operation": "query",
                "snapshot": rev["snapshot"],
                "context": lease["context"],
                "query": body["query"],
                "limits": body["limits"],
                "lean_executable": self.runtime.config.proof.lean_executable,
            }
            if body["query"]["op"] == "explain":
                with self.store.db(key) as db:
                    row = db.execute(
                        "SELECT result FROM requests WHERE result_id=? AND status='succeeded'",
                        (body["query"]["result_id"],),
                    ).fetchone()
                history = loads(row[0]) if row else None
                if history is None:
                    raise RuntimeFault("not_found", "No recorded result in this ADM")
                task["explanation"] = history
            value = self.runtime.supervisor.run(task, cancel=cancel)
            wrapped = wrap_result(key, lease, value)
            error = None
            if value["status"] != "succeeded":
                code = "resource_exhausted" if value["status"] == "inconclusive" else "needs_specification"
                error = failure(
                    code,
                    "Local computation was inconclusive"
                    if code == "resource_exhausted"
                    else "Query needs supported model content or corrected input",
                )
                # Bounded trusted local diagnostics; remote learning is not implied.
                error["details"] = {
                    "local_result": value,
                    "learning_available": True,
                    "authorization_required": True,
                }
            self.store.finish_request(key, lease, value["status"], result=wrapped, error=error)
        except RuntimeFault as error:
            try:
                code = (
                    "resource_exhausted"
                    if error.code in ("resource_exhausted", "busy", "stopped")
                    else "internal_error"
                )
                self.store.finish_request(
                    key,
                    lease,
                    "inconclusive" if code == "resource_exhausted" else "failed",
                    error=failure(
                        code, "Local attempt did not complete; inspect or explicitly retry", "reconcile"
                    ),
                )
            except RuntimeFault:
                pass  # The authoritative cancellation/epoch/reclaim already won.
        except Exception:
            try:
                self.store.finish_request(
                    key,
                    lease,
                    "failed",
                    error=failure("internal_error", "Local computation failed", "reconcile"),
                )
            except Exception:
                pass
        finally:
            with self.lock:
                self.active.pop((key, lease["id"]), None)

    def operation(self, kind, body, *, adm=None):
        raw = dumps({"kind": kind, "adm": adm, "body": body})
        fingerprint = hashlib.sha256(raw).hexdigest()
        with self.store.db() as db, self.store.transaction(db):
            old = db.execute(
                "SELECT id,digest FROM operations WHERE idem=?", (body["idempotency_key"],)
            ).fetchone()
            if old:
                if old["digest"] != fingerprint:
                    raise RuntimeFault("conflict", "Operation key already names different input")
                return self.operation_info(old["id"])
            if (
                db.execute("SELECT count(*) FROM operations").fetchone()[0]
                >= self.runtime.config.runtime.queue_items_per_adm
            ):
                raise RuntimeFault("quota_exceeded", "Retained operation limit reached")
            self.store.capacity(len(raw) + 4096)
            if adm:
                self.store.info(adm)
            if kind == "export":
                rev = self.store.revision(adm)
                body = {**body, "revision_id": rev["revision_id"]}
            uid = str(uuid4())
            db.execute(
                "INSERT INTO operations(id,idem,digest,kind,adm,body,status,created) VALUES(?,?,?,?,?,?,'received',?)",
                (uid, body["idempotency_key"], fingerprint, kind, adm, dumps(body), time.time()),
            )
        self.wake.set()
        return self.operation_info(uid)

    def operation_info(self, uid):
        with self.store.db() as db:
            row = db.execute("SELECT * FROM operations WHERE id=?", (uid,)).fetchone()
            if row is None:
                raise RuntimeFault("not_found", "Unknown operation")
            deleted = (
                row["adm"]
                and db.execute(
                    "SELECT 1 FROM instances WHERE id=? AND status IN ('deleting','deleted')", (row["adm"],)
                ).fetchone()
            )
            return {
                "operation_id": row["id"],
                "kind": row["kind"],
                "adm_id": row["adm"],
                "status": "deleted" if deleted else row["status"],
                "result": loads(row["result"]) if row["result"] and not deleted else None,
                "error": failure(
                    "internal_error",
                    "Operation interrupted or rejected; inspect before retrying",
                    "reconcile",
                )
                if row["error"]
                else None,
            }

    def run_operation(self):
        with self.store.db() as db, self.store.transaction(db):
            row = db.execute(
                "SELECT * FROM operations WHERE status='received' ORDER BY created LIMIT 1"
            ).fetchone()
            if row is None:
                return False
            db.execute("UPDATE operations SET status='running' WHERE id=?", (row["id"],))
        try:
            body = loads(row["body"])
            if row["kind"] == "create":
                # Reserve first; save the link before checking. Recovery can reconcile
                # a committed instance without ever creating a duplicate.
                with self.store.lock:
                    key = self.store.reserve(body["name"])
                    with self.store.db() as db:
                        db.execute("UPDATE operations SET adm=? WHERE id=?", (key, row["id"]))
                try:
                    prepared = self.runtime.supervisor.run(
                        {
                            "operation": "prepare",
                            "mode": body["mode"],
                            "snapshot": body.get("snapshot"),
                            "limits": self.runtime.limits(),
                        }
                    )
                    self.store.install(key, prepared, body["mode"])
                except BaseException:
                    self.store.failed_creation(key)
                    raise
                result = {"adm_id": key}
            else:
                rev = self.store.revision(row["adm"], body["revision_id"])
                result = self.runtime.supervisor.run(
                    {
                        "operation": "export",
                        "snapshot": rev["snapshot"],
                        "context": rev["context"],
                        "limits": self.runtime.limits(),
                    }
                )
                if len(dumps(result)) > self.runtime.config.server.max_body_bytes - 4096:
                    raise RuntimeFault("resource_exhausted", "Export exceeds the bounded public import size")
            with self.store.db() as db:
                if row["adm"]:
                    self.store.info(row["adm"])
                self.store.capacity(len(dumps(result)))
                db.execute(
                    "UPDATE operations SET status='succeeded',result=? WHERE id=?", (dumps(result), row["id"])
                )
        except Exception:
            with self.store.db() as db:
                db.execute(
                    "UPDATE operations SET status='failed',error='operation_failed' WHERE id=? AND status!='deleted'",
                    (row["id"],),
                )
        return True

    def loop(self):
        offset = 0
        while not self.stopping.is_set():
            worked = False
            try:
                self.runtime.lifecycle.tick()
                rows = [r for r in self.store.list() if r["status"] == "ready"]
                if rows:
                    offset %= len(rows)
                    rows = rows[offset:] + rows[:offset]
                    offset += 1
                for row in rows:
                    self.store.reclaim(row["id"])
                    lease = self.store.claim_request(row["id"])
                    if lease:
                        worked = True
                        self.perform(row["id"], lease)
                        break
                if not worked:
                    worked = self.run_operation()
            except Exception:
                # Durable state stays authoritative; bounded retry also handles temporary
                # storage/busy failures without creating new attempts or remote calls.
                pass
            if not worked:
                self.wake.wait(0.1)
                self.wake.clear()

    def close(self):
        self.stopping.set()
        self.wake.set()
        with self.lock:
            for event in self.active.values():
                event.set()
        self.runtime.supervisor.close()
        for thread in self.threads:
            thread.join(timeout=5)
