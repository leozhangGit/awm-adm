"""Deletion fences first, scrubs owned payloads, and retains conservative accounting.

All transitions serialize on the existing store lock. No distributed transaction
is assumed: gateway redaction is an idempotent acknowledgement protocol.
"""

import hashlib
import os
import time
from uuid import uuid4

from ..runtime.protocol import RuntimeFault, dumps, loads
from ..runtime.storage import identifier
from .models import DeleteInput, RenameInput


def fingerprint(value):
    return hashlib.sha256(dumps(value)).hexdigest()


# Only these fields survive in a deleted model's dispatch accounting record.
GRANT_FIELDS = {
    "id",
    "adm",
    "purpose",
    "lane",
    "lease",
    "connection_id",
    "connection_version",
    "configuration_digest",
    "input_estimate",
    "limits",
    "price_binding",
    "allowance_id",
    "operation_id",
    "generation",
    "settings_generation",
    "spending_generation",
    "expires",
    "deadline",
}


def accounting_outcome(value):
    """No provider text, arbitrary errors or source references survive deletion."""
    return {
        "status": "failed" if value["status"] == "succeeded" else value["status"],
        "usage": value.get("usage"),
        "text": None,
        "error": "model_deleted",
        "diagnostics": value.get("diagnostics", {}),
    }


class Lifecycle:
    def __init__(self, runtime):
        self.runtime, self.store = runtime, runtime.store
        self.ready = False

    def rename(self, key, body):
        body = RenameInput.model_validate(body).model_dump()
        name = body["name"]
        if any(ord(c) < 32 for c in name) or not name.strip():
            raise RuntimeFault("invalid_input", "Use a printable model name")
        with self.store.lock, self.store.db() as db, self.store.transaction(db):
            info = self.store.info(key)
            if info["name"] != body["expected_name"]:
                if info["name"] == name:
                    return info
                raise RuntimeFault("stale_context", "Model name changed")
            db.execute("UPDATE instances SET name=? WHERE id=?", (name, key))
        return self.store.info(key)

    def request(self, key, body):
        identifier(key)
        body = DeleteInput.model_validate(body).model_dump()
        meaning = fingerprint({"adm": key, "body": body})
        idem = fingerprint(body["idempotency_key"])
        with self.store.lock, self.store.db() as db, self.store.transaction(db):
            prior = db.execute("SELECT * FROM deletions WHERE idem=?", (idem,)).fetchone()
            if prior:
                if prior["digest"] != meaning:
                    raise RuntimeFault("conflict", "Deletion identity names different input")
                return self.view(prior["id"])
            if db.execute("SELECT 1 FROM deletions WHERE adm=?", (key,)).fetchone():
                raise RuntimeFault("conflict", "An existing deletion owns this model")
            info = self.store.info(key)
            if (
                info["status"] not in ("ready", "failed")
                or not body["confirm_delete"]
                or info["name"] != body["confirm_name"]
                or info.get("revision_id") != body["expected_revision"]
                or info.get("policy_epoch") != body["expected_epoch"]
            ):
                raise RuntimeFault("stale_context", "Confirm the current named model and scope")
            if db.execute("SELECT count(*) FROM deletions").fetchone()[0] >= 10000:
                raise RuntimeFault("quota_exceeded", "Retained deletion allowance reached")
            self.store.capacity(8192)
            operation = str(uuid4())
            now = time.time()
            inventory = {
                "profile": "awm-adm-deletion-inventory/1",
                "files": [f"{key}.db{suffix}" for suffix in ("", "-wal", "-shm", "-journal")],
                "scope": [
                    "model_database",
                    "operations",
                    "credentials",
                    "allowances",
                    "dispatch_payloads",
                    "gateway_payloads",
                ],
                "outside_scope": [
                    "independent_models",
                    "shared_connections",
                    "exported_files",
                    "external_backups",
                ],
                "digest": fingerprint(
                    {"adm": key, "revision": info.get("revision_id"), "epoch": info.get("policy_epoch")}
                ),
            }
            db.execute(
                "INSERT INTO deletions VALUES(?,?,?,?, 'requested',NULL,1,?,?,?)",
                (operation, key, idem, meaning, dumps(inventory), now, now),
            )
            # The durable request is already a publication/read fence. Advancing
            # the stage later cannot reopen the model after an interrupted request.
            db.execute("UPDATE instances SET status='deleting',name='' WHERE id=?", (key,))
        self._cancel_compute(key)
        self.runtime.coordinator.wake.set()
        return self.view(operation)

    def view(self, operation):
        with self.store.db() as db:
            row = db.execute("SELECT * FROM deletions WHERE id=?", (operation,)).fetchone()
            if not row:
                raise RuntimeFault("not_found", "Unknown deletion operation")
            waiting = db.execute(
                "SELECT count(*) FROM deletion_grants WHERE operation_id=? AND acknowledged=0", (operation,)
            ).fetchone()[0]
        return {
            "profile": "awm-adm-deletion/1",
            "operation_id": row["id"],
            "adm_id": row["adm"],
            "stage": row["stage"],
            "resume_stage": row["resume_stage"],
            "version": row["version"],
            "inventory": loads(row["inventory"]),
            "gateway_pending": waiting,
            "message": "Cleanup needs attention. Retry this operation after resolving the storage or gateway issue."
            if row["stage"] == "blocked"
            else None,
        }

    def listing(self, after=0, limit=20, scope="all"):
        with self.store.db() as db:
            if scope == "completed":
                rows = db.execute(
                    "SELECT rowid,id FROM deletions WHERE stage='deleted' AND (?=0 OR rowid<?) "
                    "ORDER BY rowid DESC LIMIT ?",
                    (after, after, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT rowid,id FROM deletions WHERE rowid>? AND (?='all' OR stage!='deleted') "
                    "ORDER BY rowid LIMIT ?",
                    (after, scope, limit),
                ).fetchall()
            return {
                "items": [self.view(r["id"]) for r in rows],
                "next_cursor": rows[-1]["rowid"] if rows else after,
            }

    def retry(self, operation, version):
        with self.store.db() as db, self.store.transaction(db):
            row = db.execute("SELECT * FROM deletions WHERE id=?", (operation,)).fetchone()
            if row is None:
                raise RuntimeFault("not_found", "Unknown deletion operation")
            if row["stage"] != "blocked" or row["version"] != version:
                raise RuntimeFault("stale_context", "Deletion progress changed")
            self._advance(db, operation, row["resume_stage"])
        self.runtime.coordinator.wake.set()
        return self.view(operation)

    @staticmethod
    def _advance(db, operation, stage):
        db.execute(
            "UPDATE deletions SET stage=?,resume_stage=NULL,version=version+1,updated=? WHERE id=?",
            (stage, time.time(), operation),
        )

    def _cancel_compute(self, key):
        for component in (
            self.runtime,
            *(getattr(self.runtime, n, None) for n in ("learning", "language", "conversations")),
        ):
            supervisor = getattr(component, "supervisor", None)
            if supervisor:
                supervisor.cancel_scope(key)

    def _fence(self, db, key):
        for row in db.execute("SELECT * FROM credentials").fetchall():
            scope = loads(row["scope"])
            if key not in scope.get("adms", []):
                continue
            remaining = [a for a in scope["adms"] if a != key]
            if remaining and scope.get("permissions") != ["append"]:
                scope["adms"] = remaining
                db.execute("UPDATE credentials SET scope=? WHERE id=?", (dumps(scope), row["id"]))
            else:
                db.execute("DELETE FROM credentials WHERE id=?", (row["id"],))
        for row in db.execute(
            "SELECT * FROM allowances WHERE json_extract(body,'$.adm_id')=?", (key,)
        ).fetchall():
            value = loads(row["body"])
            value["scope_id"] = "deleted"
            value["idempotency_key"] = fingerprint(value["idempotency_key"])
            db.execute(
                "UPDATE allowances SET state='closed',body=?,idem=? WHERE id=?",
                (dumps(value), "deleted:" + value["idempotency_key"], row["id"]),
            )
            db.execute("DELETE FROM budget_children WHERE allowance_id=?", (row["id"],))

    def _drain(self, db, operation, key):
        for row in db.execute("SELECT * FROM grants WHERE adm=?", (key,)).fetchall():
            body = loads(row["body"])
            if body.get("model_deleted"):
                continue
            safe = {k: v for k, v in body.items() if k in GRANT_FIELDS}
            safe.update(episode=None, model_deleted=True)
            status = row["status"]
            outcome = loads(row["outcome"]) if row["outcome"] else None
            # Ready/leased have not passed gateway authorization; dispatched or
            # restarted leases remain conservative until identified usage arrives.
            if status in ("ready", "leased"):
                status = "not_dispatched"
                self.runtime.learning.allowances.settle(db, row["id"], not_dispatched=True)
                db.execute(
                    "UPDATE grants SET calls=0,input_tokens=0,output_tokens=0,unresolved=0 WHERE id=?",
                    (row["id"],),
                )
                outcome = {"status": status, "usage": None}
            elif status == "dispatched":
                status = "outcome_unknown"
                self.runtime.learning.allowances.settle(db, row["id"])
                outcome = {"status": status, "usage": None}
            db.execute(
                "UPDATE grants SET body=?,episode=NULL,status=?,outcome=? WHERE id=?",
                (dumps(safe), status, dumps(accounting_outcome(outcome)) if outcome else None, row["id"]),
            )
            # Every grant gets a gateway tombstone, including grants that never
            # reached it, so a delayed authorized request cannot reintroduce data.
            db.execute("INSERT OR IGNORE INTO deletion_grants VALUES(?,?,0)", (row["id"], operation))
        db.execute("DELETE FROM source_arrivals WHERE adm=?", (key,))
        db.execute("UPDATE provider_lanes SET last_adm=NULL WHERE last_adm=?", (key,))
        # Preserve only opaque replay identity and digest; erase imported/exported
        # snapshots, names and operation payloads, including in-flight exports.
        db.execute(
            "UPDATE operations SET body='{}',result=NULL,status='deleted',error=NULL WHERE adm=?", (key,)
        )

    def tick(self):
        if not self.ready:
            return False
        with self.store.lock:
            with self.store.db() as db:
                row = db.execute(
                    "SELECT * FROM deletions WHERE stage NOT IN ('deleted','blocked') ORDER BY updated LIMIT 1"
                ).fetchone()
            if row is None:
                return False
            operation, key, stage = row["id"], row["adm"], row["stage"]
            try:
                self._cancel_compute(key)
                if stage == "requested":
                    with self.store.db() as db, self.store.transaction(db):
                        self._fence(db, key)
                        self._advance(db, operation, "fenced")
                elif stage == "fenced":
                    with self.store.db() as db, self.store.transaction(db):
                        self._drain(db, operation, key)
                        self._advance(db, operation, "draining")
                elif stage == "draining":
                    with self.store.db() as db, self.store.transaction(db):
                        self._advance(db, operation, "purging")
                elif stage == "purging":
                    for name in loads(row["inventory"])["files"]:
                        path = self.store.root / name
                        if path.is_symlink() or (path.exists() and not path.is_file()):
                            raise RuntimeFault("invalid_data_path", "Unexpected model artifact")
                        path.unlink(missing_ok=True)
                    fd = os.open(self.store.root, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                    with self.store.db() as db, self.store.transaction(db):
                        if db.execute(
                            "SELECT 1 FROM deletion_grants WHERE operation_id=? AND acknowledged=0",
                            (operation,),
                        ).fetchone():
                            # App content is gone; no gateway contact or provider
                            # usage resolution is needed to reach this point.
                            db.execute("UPDATE deletions SET updated=? WHERE id=?", (time.time(), operation))
                            return False
                        db.execute("UPDATE instances SET status='deleted' WHERE id=?", (key,))
                        self._advance(db, operation, "deleted")
                return True
            except Exception:
                with self.store.db() as db:
                    db.execute(
                        "UPDATE deletions SET stage='blocked',resume_stage=?,version=version+1,updated=? WHERE id=?",
                        (stage, time.time(), operation),
                    )
                return False

    def gateway_cleanup(self, acknowledgments):
        with self.store.db() as db, self.store.transaction(db):
            for grant in acknowledgments:
                db.execute("UPDATE deletion_grants SET acknowledged=1 WHERE grant_id=?", (grant,))
            return [
                r[0]
                for r in db.execute("SELECT grant_id FROM deletion_grants WHERE acknowledged=0 LIMIT 100")
            ]
