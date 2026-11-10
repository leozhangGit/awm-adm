"""Durable local requests and transactional result/outbox publication."""

import hashlib
import time
from uuid import uuid4

from ..contracts import Event
from ..runtime.protocol import RuntimeFault, dumps, loads
from ..runtime.storage import Store, identifier

TERMINAL = {"succeeded", "failed", "cancelled", "inconclusive", "needs_input"}


def context_binding(context):
    return {
        "adm_id": context["instance_id"],
        "theory_root": context["theory_version"],
        "policy_epoch": context["policy_epoch"],
        "support_root": context["support_root"],
        **(
            {"source_policy_generation": context["source_policy_generation"]}
            if "source_policy_generation" in context
            else {}
        ),
    }


def failure(code, message, retry="after_input"):
    return {
        "error_profile": "awm-adm-error/2",
        "code": code,
        "message": message,
        "retry": retry,
        "resource_id": None,
        "details": {},
    }


class ApplicationStore(Store):
    def ensure_revision(self, key):
        with self.db(key) as db, self.transaction(db):
            control = db.execute("SELECT revision FROM control WHERE id=1").fetchone()
            if control[0] is None:
                state = db.execute("SELECT * FROM state WHERE id=1").fetchone()
                version = db.execute("SELECT * FROM versions WHERE root=?", (state["active"],)).fetchone()
                revision = str(uuid4())
                db.execute(
                    "INSERT INTO revisions(id,context,payload,digest) VALUES(?,?,?,?)",
                    (revision, state["context"], version["payload"], version["digest"]),
                )
                db.execute("UPDATE control SET revision=? WHERE id=1", (revision,))

    def install(self, key, prepared, mode):
        super().install(key, prepared, mode)
        self.ensure_revision(key)
        return self.info(key)

    def info(self, key):
        result = super().info(key)
        if result["status"] == "ready":
            with self.db(key) as db:
                control = db.execute("SELECT * FROM control WHERE id=1").fetchone()
                result.update(
                    revision_id=control["revision"],
                    archived=bool(control["archived"]),
                    background_learning=True,
                )
        return result

    def revision(self, key, revision=None):
        self.info(key)
        with self.db(key) as db:
            row = db.execute(
                "SELECT * FROM revisions WHERE id=COALESCE(?,(SELECT revision FROM control WHERE id=1))",
                (revision,),
            ).fetchone()
            if row is None:
                raise RuntimeFault("not_found", "Unknown model revision")
            if hashlib.sha256(row["payload"]).hexdigest() != row["digest"]:
                raise RuntimeFault("corrupt_store", "Model revision failed its content digest")
            return {
                "revision_id": row["id"],
                "context": loads(row["context"]),
                "snapshot": loads(row["payload"]),
            }

    def snapshot(self, key):
        with self.db(key) as db:
            ready = db.execute("SELECT revision FROM control WHERE id=1").fetchone()
        return self.revision(key)["snapshot"] if ready and ready[0] else super().snapshot(key)

    def emit(self, db, key, kind, resource, *, attempt=None, context=None, data=None):
        now = time.time()
        seq = db.execute("INSERT INTO events(payload,created) VALUES(?,?)", (b"{}", now)).lastrowid
        event = Event(
            adm_id=key,
            event_id=f"{key}:{seq}",
            sequence=seq,
            occurred_at_ms=int(now * 1000),
            kind=kind,
            resource_id=resource,
            request_id=resource if kind.startswith("request.") else None,
            attempt_id=attempt,
            context=context_binding(context) if context else None,
            data=data or {},
        )
        db.execute("UPDATE events SET payload=? WHERE seq=?", (dumps(event.model_dump()), seq))
        return seq

    def submit(self, key, envelope, *, expected_revision=None):
        self.info(key)
        with self.db(key) as db, self.transaction(db):
            return self.submit_transaction(db, key, envelope, expected_revision=expected_revision)

    def submit_transaction(self, db, key, envelope, *, expected_revision=None):
        """Caller owns the per-ADM write transaction, including consent if present."""
        raw = dumps(envelope)
        fingerprint = hashlib.sha256(raw).hexdigest()
        previous = db.execute(
            "SELECT id,digest FROM requests WHERE idem=?", (envelope["idempotency_key"],)
        ).fetchone()
        if previous:
            if previous["digest"] != fingerprint:
                raise RuntimeFault("conflict", "Idempotency key already names different input")
            return previous["id"]
        if db.execute("SELECT archived FROM control WHERE id=1").fetchone()[0]:
            raise RuntimeFault("conflict", "Archived instances do not accept new work")
        if (
            expected_revision is not None
            and expected_revision != db.execute("SELECT revision FROM control WHERE id=1").fetchone()[0]
        ):
            raise RuntimeFault("stale_context", "Displayed model revision changed")
        count, size = db.execute("SELECT count(*),COALESCE(sum(length(envelope)),0) FROM requests").fetchone()
        if count >= self.limits.queue_items_per_adm or size + len(raw) > self.limits.queue_bytes_per_adm:
            raise RuntimeFault("quota_exceeded", "Retained request allowance is exhausted")
        self.capacity(len(raw) + 4096)
        current = loads(db.execute("SELECT context FROM state WHERE id=1").fetchone()[0])
        revision = db.execute("SELECT revision FROM control WHERE id=1").fetchone()[0]
        uid, now = str(uuid4()), time.time()
        db.execute(
            "INSERT INTO requests(id,idem,digest,envelope,revision,context,status,created,updated) VALUES(?,?,?,?,?,?,'received',?,?)",
            (uid, envelope["idempotency_key"], fingerprint, raw, revision, dumps(current), now, now),
        )
        db.execute("UPDATE requests SET initial_revision=revision WHERE id=?", (uid,))
        self.emit(db, key, "request.received", uid, context=current)
        return uid

    def request(self, key, uid):
        self.info(key)
        with self.db(key) as db:
            row = db.execute("SELECT * FROM requests WHERE id=?", (identifier(uid),)).fetchone()
            if row is None:
                raise RuntimeFault("not_found", "Unknown request in this ADM")
            return {
                "adm_id": key,
                "request_id": uid,
                "status": row["status"],
                "attempt_id": row["attempt"],
                "result": loads(row["result"]) if row["result"] else None,
                "error": loads(row["error"]) if row["error"] else None,
                "learning_job_ids": [
                    r[0] for r in db.execute("SELECT episode FROM interests WHERE request=?", (uid,))
                ],
                "initial_revision_id": row["initial_revision"],
                "query": loads(row["envelope"])["query"],
                "revision_id": row["revision"],
                "pinned_context": context_binding(loads(row["context"])),
                "current_context": context_binding(self.info(key)),
                "attempts": [
                    dict(r)
                    for r in db.execute(
                        "SELECT id,status,started,ended,revision FROM attempts WHERE request_id=? ORDER BY seq",
                        (uid,),
                    )
                ],
                "created_at_ms": int(row["created"] * 1000),
                "updated_at_ms": int(row["updated"] * 1000),
            }

    def page(self, key, table, after=0, limit=50, *, descending=False):
        if table not in ("requests", "revisions"):
            raise ValueError("Unknown collection")
        self.info(key)
        columns = "seq,id,status,attempt,result_id,context" if table == "requests" else "seq,id"
        comparison, order = ("<", "DESC") if descending else (">", "ASC")
        cursor = 9_007_199_254_740_991 if descending and after == 0 else after
        with self.db(key) as db:
            rows = db.execute(
                f"SELECT {columns} FROM {table} WHERE seq{comparison}? ORDER BY seq {order} LIMIT ?",
                (cursor, limit + 1),
            ).fetchall()
        chosen = rows[:limit]
        return {
            "items": [
                {
                    "adm_id": key,
                    "request_id": r["id"],
                    "status": r["status"],
                    "attempt_id": r["attempt"],
                    "result_id": r["result_id"],
                    "pinned_context": context_binding(loads(r["context"])),
                }
                if table == "requests"
                else {k: v for k, v in self.revision(key, r["id"]).items() if k != "snapshot"}
                for r in chosen
            ],
            "next_cursor": chosen[-1]["seq"] if len(rows) > limit else None,
        }

    def claim_request(self, key):
        with self.db(key) as db, self.transaction(db):
            # A single active request per ADM leaves other instance queues a turn.
            if db.execute("SELECT 1 FROM requests WHERE status='evaluating'").fetchone():
                return None
            row = db.execute("SELECT * FROM requests WHERE status='received' ORDER BY seq LIMIT 1").fetchone()
            if row is None:
                return None
            if (
                db.execute("SELECT count(*) FROM attempts").fetchone()[0]
                >= self.limits.queue_items_per_adm * 4
            ):
                self._terminal(
                    db,
                    key,
                    row,
                    "inconclusive",
                    error=failure("resource_exhausted", "Retained attempt allowance exhausted"),
                )
                return None
            body = loads(row["envelope"])
            now = time.time()
            attempt = str(uuid4())
            db.execute(
                "UPDATE requests SET status='evaluating',attempt=?,generation=?,expires=?,updated=? WHERE id=?",
                (
                    attempt,
                    self.generation,
                    now + body["limits"]["max_duration_ms"] / 1000 + 3,
                    now,
                    row["id"],
                ),
            )
            db.execute(
                "INSERT INTO attempts(id,request_id,generation,status,started) VALUES(?,?,?,'evaluating',?)",
                (attempt, row["id"], self.generation, now),
            )
            db.execute("UPDATE attempts SET revision=? WHERE id=?", (row["revision"], attempt))
            self.emit(
                db, key, "request.evaluating", row["id"], attempt=attempt, context=loads(row["context"])
            )
            return {
                "id": row["id"],
                "attempt": attempt,
                "generation": self.generation,
                "envelope": body,
                "revision": row["revision"],
                "context": loads(row["context"]),
            }

    def _terminal(self, db, key, row, status, *, result=None, error=None):
        now = time.time()
        db.execute(
            "UPDATE requests SET status=?,result=?,result_id=?,error=?,updated=?,expires=NULL WHERE id=?",
            (
                status,
                dumps(result) if result is not None else None,
                result["result_id"] if result is not None else None,
                dumps(error) if error else None,
                now,
                row["id"],
            ),
        )
        if row["attempt"]:
            db.execute("UPDATE attempts SET status=?,ended=? WHERE id=?", (status, now, row["attempt"]))
        self.emit(
            db, key, "request." + status, row["id"], attempt=row["attempt"], context=loads(row["context"])
        )

    def finish_request(self, key, lease, status, *, result=None, error=None):
        with self.db(key) as db, self.transaction(db):
            row = db.execute("SELECT * FROM requests WHERE id=?", (lease["id"],)).fetchone()
            if (
                not row
                or row["status"] != "evaluating"
                or row["attempt"] != lease["attempt"]
                or row["generation"] != self.generation
                or lease["generation"] != self.generation
                or row["expires"] <= time.time()
            ):
                raise RuntimeFault("stale_context", "Request attempt no longer has publication authority")
            current = loads(db.execute("SELECT context FROM state WHERE id=1").fetchone()[0])
            if current["policy_epoch"] != loads(row["context"])["policy_epoch"]:
                raise RuntimeFault("stale_context", "Owner policy changed during computation")
            self.capacity(len(dumps(result)) + 4096)
            if status == "needs_input":
                pending = db.execute(
                    "SELECT e.data FROM episodes e JOIN interests i ON e.id=i.episode WHERE i.request=?",
                    (row["id"],),
                ).fetchall()
                if any(
                    loads(r[0])["status"] not in {"accepted", "rejected", "cancelled", "stopped"}
                    for r in pending
                ):
                    status = "waiting_for_learning"
            self._terminal(db, key, row, status, result=result, error=error)

    def cancel_request(self, key, uid):
        self.info(key)
        with self.db(key) as db, self.transaction(db):
            row = db.execute("SELECT * FROM requests WHERE id=?", (identifier(uid),)).fetchone()
            if row is None:
                raise RuntimeFault("not_found", "Unknown request in this ADM")
            if row["status"] not in TERMINAL:
                self._terminal(db, key, row, "cancelled")
        return self.request(key, uid)

    def reclaim(self, key, *, restart=False):
        with self.db(key) as db, self.transaction(db):
            rows = db.execute("SELECT * FROM requests WHERE status='evaluating'").fetchall()
            for row in rows:
                if not restart and row["expires"] > time.time():
                    continue
                self._terminal(
                    db,
                    key,
                    row,
                    "inconclusive",
                    error=failure(
                        "resource_exhausted",
                        "Local attempt interrupted; explicit retry is available",
                        "reconcile",
                    ),
                )

    def retry_request(self, key, uid):
        info = self.info(key)
        with self.db(key) as db, self.transaction(db):
            row = db.execute("SELECT * FROM requests WHERE id=?", (identifier(uid),)).fetchone()
            if row is None:
                raise RuntimeFault("not_found", "Unknown request")
            if row["status"] == "received":
                return uid
            if row["status"] not in ("inconclusive", "needs_input", "failed") or info["archived"]:
                raise RuntimeFault("conflict", "Request cannot be retried in its current state")
            # Repeating local work preserves the original meaning/revision. A changed
            # policy requires a new request, never silent repinning of an old intent.
            current = loads(db.execute("SELECT context FROM state WHERE id=1").fetchone()[0])
            if loads(row["context"])["policy_epoch"] != current["policy_epoch"]:
                raise RuntimeFault("stale_context", "Submit a new request under the current owner policy")
            db.execute(
                "UPDATE requests SET status='received',result=NULL,error=NULL,attempt=NULL,updated=? WHERE id=?",
                (time.time(), uid),
            )
            self.emit(db, key, "request.received", uid, context=loads(row["context"]), data={"retry": True})
        return uid

    def events(self, key, after=0, limit=50):
        self.info(key)
        with self.db(key) as db:
            floor = db.execute("SELECT floor FROM control WHERE id=1").fetchone()[0]
            latest = db.execute("SELECT COALESCE(max(seq),?) FROM events", (floor,)).fetchone()[0]
            if after < floor:
                raise RuntimeFault(
                    "cursor_expired",
                    "Event cursor expired; reload resource snapshots and resume at the earliest cursor",
                )
            if after > latest:
                raise RuntimeFault("invalid_input", "Event cursor is ahead of this ADM")
            rows = db.execute(
                "SELECT seq,payload FROM events WHERE seq>? ORDER BY seq LIMIT ?", (after, limit)
            ).fetchall()
            return {
                "items": [loads(r["payload"]) for r in rows],
                "cursor": rows[-1]["seq"] if rows else after,
                "earliest_cursor": floor,
                "latest_cursor": latest,
            }

    def prune_events(self, key, through):
        # Explicit owner operation; clients acknowledge independently and never delete.
        page = self.events(key, through, 1)
        with self.db(key) as db, self.transaction(db):
            db.execute("DELETE FROM events WHERE seq<=?", (through,))
            db.execute(
                "UPDATE control SET floor=max(floor,?) WHERE id=1", (max(page["earliest_cursor"], through),)
            )
        return self.events(key, through, 1)

    def consumer(self, key, principal, uid=None, cursor=0):
        self.events(key, cursor, 1)
        with self.db(key) as db, self.transaction(db):
            if uid is None:
                if db.execute("SELECT count(*) FROM consumers").fetchone()[0] >= 100:
                    raise RuntimeFault("quota_exceeded", "Consumer limit reached")
                uid = str(uuid4())
                db.execute("INSERT INTO consumers VALUES(?,?,?)", (uid, principal, cursor))
            else:
                row = db.execute(
                    "SELECT * FROM consumers WHERE id=? AND principal=?", (identifier(uid), principal)
                ).fetchone()
                if row is None:
                    raise RuntimeFault("not_found", "Unknown event consumer")
                if cursor < row["cursor"]:
                    raise RuntimeFault("conflict", "Consumer cursor cannot move backwards")
                db.execute("UPDATE consumers SET cursor=? WHERE id=?", (cursor, uid))
            return {"id": uid, "cursor": cursor}

    def change(self, key, expected, *, mode=None, prepared=None, archive=False):
        self.info(key)
        with self.db(key) as db, self.transaction(db):
            current = loads(db.execute("SELECT context FROM state WHERE id=1").fetchone()[0])
            if current["policy_epoch"] != expected:
                raise RuntimeFault("stale_context", "Owner epoch changed; reload before editing")
            if db.execute("SELECT archived FROM control WHERE id=1").fetchone()[0]:
                raise RuntimeFault("conflict", "Instance is archived")
            if db.execute("SELECT count(*) FROM revisions").fetchone()[0] >= self.limits.queue_items_per_adm:
                raise RuntimeFault("quota_exceeded", "Retained revision limit reached")
            old = self.revision(key)
            context = dict(current)
            if prepared:
                if (
                    prepared["context"]["theory_version"] != current["theory_version"]
                    or prepared["context"]["support_root"] != current["support_root"]
                ):
                    raise RuntimeFault("stale_context", "Validated policy belongs to a different model")
                context["conformance_root"] = prepared["context"]["conformance_root"]
            if mode:
                context["mode"] = mode
            context["policy_epoch"] += 1
            snapshot = prepared["snapshot"] if prepared else old["snapshot"]
            payload = dumps(snapshot)
            revision = str(uuid4())
            self.capacity(len(payload) + 4096)
            db.execute(
                "INSERT INTO revisions(id,context,payload,digest) VALUES(?,?,?,?)",
                (revision, dumps(context), payload, hashlib.sha256(payload).hexdigest()),
            )
            db.execute("UPDATE state SET context=?,mode=? WHERE id=1", (dumps(context), context["mode"]))
            db.execute("UPDATE control SET revision=?,archived=? WHERE id=1", (revision, int(archive)))
            for row in db.execute(
                "SELECT * FROM requests WHERE status IN ('received','evaluating','waiting_for_learning')"
            ).fetchall():
                self._terminal(
                    db,
                    key,
                    row,
                    "cancelled" if archive else "needs_input",
                    error=None
                    if archive
                    else failure("stale_context", "Owner epoch changed; submit a new request"),
                )
            self.emit(
                db,
                key,
                "policy.changed" if prepared else "settings.changed",
                key,
                context=context,
                data={"mode": context["mode"], "archived": archive},
            )
        return self.info(key)

    def reconcile(self):
        super().reconcile()
        for row in self.list():
            if row["status"] == "ready":
                with self.db(row["id"]) as db:
                    for table in ("versions", "revisions"):
                        for item in db.execute(f"SELECT payload,digest FROM {table}"):
                            if hashlib.sha256(item["payload"]).hexdigest() != item["digest"]:
                                raise RuntimeFault("corrupt_store", "Historical model digest mismatch")
                self.ensure_revision(row["id"])
                self.reclaim(row["id"], restart=True)
        with self.db() as db, self.transaction(db):
            for row in db.execute("SELECT * FROM operations WHERE status='running'").fetchall():
                complete = (
                    row["kind"] == "create"
                    and row["adm"]
                    and db.execute(
                        "SELECT 1 FROM instances WHERE id=? AND status='ready'", (row["adm"],)
                    ).fetchone()
                    is not None
                )
                db.execute(
                    "UPDATE operations SET status=?,result=?,error=? WHERE id=?",
                    (
                        "succeeded" if complete else "failed",
                        dumps({"adm_id": row["adm"]}) if complete else None,
                        None if complete else "interrupted",
                        row["id"],
                    ),
                )
