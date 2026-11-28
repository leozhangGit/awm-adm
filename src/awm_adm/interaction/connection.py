"""One tested connection; no price or spending authority is created by activation."""

from datetime import datetime, timedelta, timezone
from typing import get_args
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..contracts import Purpose
from ..learning.service import fault, fingerprint
from ..runtime.protocol import RuntimeFault, dumps, loads
from .models import DisableConnection, EnableConnection


class Connection:
    def __init__(self, learning):
        self.learning, self.store = learning, learning.store

    def control(self, db=None):
        if db is not None:
            return dict(db.execute("SELECT * FROM connection_control WHERE id=1").fetchone())
        with self.store.db() as registry:
            return self.control(registry)

    def view(self):
        control = self.control()
        saved = self.learning.connection(control["connection_id"]) if control["connection_id"] else None
        choices = []
        if not saved:
            choices = [
                {k: c[k] for k in ("id", "provider", "model")}
                for c in self.learning.connections()
                if c["provider"] != "recorded"
            ]
        return {
            "state": control["state"],
            "generation": control["generation"],
            "provider": saved["provider"] if saved else None,
            "model": saved["model"] if saved else None,
            "has_saved_key": bool(saved and saved["credential_mode"] != "none"),
            "operation_id": control["operation_id"],
            "error": control["error"],
            "migration_choices": choices if len(choices) > 1 else [],
            "gateway_key": self.learning.settings()["gateway_key"],
        }

    def active(self, purpose):
        control = self.control()
        if control["state"] != "enabled" or not control["connection_id"]:
            fault("remote_calls_disabled", "Enable the connection in Connections to use Ask or Teach.")
        conn = self.learning.connection(control["connection_id"])
        return self.learning._usable(conn["id"], conn["version"], purpose)

    def permits(self, key, purpose):
        control = self.control()
        return control["connection_id"] == key and (
            control["state"] == "enabled" or (control["state"] == "testing" and purpose == "connection_test")
        )

    def operation(self, uid):
        with self.store.db() as db:
            row = db.execute("SELECT * FROM connection_operations WHERE id=?", (uid,)).fetchone()
        if not row:
            fault("not_found", "Connection operation not found")
        return {"id": row["id"], "status": row["status"], "error": row["error"], "grant_id": row["grant_id"]}

    def replay(self, body, kind):
        digest = fingerprint({"kind": kind, "input": body})
        with self.store.db() as db:
            old = db.execute(
                "SELECT id,digest FROM connection_operations WHERE idem=?", (body["idempotency_key"],)
            ).fetchone()
        if old and old["digest"] != digest:
            fault("conflict", "This connection submission identity has different input")
        return (self.operation(old["id"]) if old else None), digest

    def enable(self, source):
        body = EnableConnection.model_validate(source).model_dump()
        with self.store.lock:
            old, digest = self.replay(body, "enable")
            if old:
                return old
            control = self.control()
            if control["state"] != "disabled":
                fault("conflict", "Disable the connection before changing it")
            if body["expected_generation"] not in (None, control["generation"]):
                fault("stale_context", "The connection changed; refresh before enabling")
            key = body["retained_connection_id"] or control["connection_id"]
            if not key:
                choices = [c for c in self.learning.connections() if c["provider"] != "recorded"]
                if len(choices) > 1:
                    fault("needs_specification", "Choose which saved connection to retain")
                key = choices[0]["id"] if choices else None
            current = self.learning.connection(key) if key else None
            if not body["sealed_credential"] and (
                not current or current["provider"] != body["provider"] or current["credential_mode"] == "none"
            ):
                fault("invalid_input", "Enter a key for the selected provider")
            config = {
                "idempotency_key": body["idempotency_key"],
                "name": "Connection",
                "provider": body["provider"],
                "model": body["model"],
                "enabled": True,
                "purposes": list(get_args(Purpose)),
                "credential_mode": "managed" if body["sealed_credential"] else current["credential_mode"],
                "sealed_credential": body["sealed_credential"],
                "sealing_key_id": body["sealing_key_id"],
            }
            if current:
                config["expected_version"] = current["version"]
            # Saving is idempotent even if a crash separates configuration and operation records.
            saved = self.learning.save_connection(config, key)
            uid = str(uuid4())
            with self.store.db() as db, self.store.transaction(db):
                db.execute(
                    "INSERT INTO connection_operations(id,idem,digest,kind,body,status,created) VALUES(?,?,?,'enable',?,'testing',?)",
                    (
                        uid,
                        body["idempotency_key"],
                        digest,
                        dumps(
                            {
                                "connection_id": saved["id"],
                                "version": saved["version"],
                                "call_limits": self.learning.runtime.settings.call.limits(),
                            }
                        ),
                        self.learning.now(),
                    ),
                )
                db.execute(
                    "UPDATE connection_control SET generation=generation+1,connection_id=?,state='testing',operation_id=?,error=NULL WHERE id=1",
                    (saved["id"], uid),
                )
                db.execute("UPDATE learning_control SET generation=generation+1,enabled=0 WHERE id=1")
            self.learning.wake.set()
            return self.operation(uid)

    def disable(self, source):
        body = DisableConnection.model_validate(source).model_dump()
        with self.store.lock:
            old, digest = self.replay(body, "disable")
            if old:
                return old
            uid = str(uuid4())
            with self.store.db() as db, self.store.transaction(db):
                control = self.control(db)
                if control["state"] == "testing":
                    db.execute(
                        "UPDATE connection_operations SET status='cancelled',error='connection_disabled' WHERE id=? AND status='testing'",
                        (control["operation_id"],),
                    )
                db.execute(
                    "INSERT INTO connection_operations(id,idem,digest,kind,body,status,created) VALUES(?,?,?,'disable',?,'completed',?)",
                    (uid, body["idempotency_key"], digest, dumps({}), self.learning.now()),
                )
                db.execute(
                    "UPDATE connection_control SET generation=generation+1,state='disabled',operation_id=?,error=NULL WHERE id=1",
                    (uid,),
                )
                db.execute("UPDATE learning_control SET generation=generation+1,enabled=0 WHERE id=1")
            self.learning.wake.set()
            return self.operation(uid)

    def tick(self):
        with self.store.lock:
            control = self.control()
            if control["state"] != "testing":
                return False
            with self.store.db() as db:
                row = db.execute(
                    "SELECT * FROM connection_operations WHERE id=?", (control["operation_id"],)
                ).fetchone()
            config = loads(row["body"])
            conn = self.learning.connection(config["connection_id"])
            error = None
            if conn["version"] != config["version"]:
                error = "connection_changed"
            elif conn["status"] == "credential_unavailable":
                error = "credential_unavailable"
            elif not row["grant_id"]:
                if conn["status"] != "ready":
                    if self.learning.now() - row["created"] < 60:
                        return False
                    error = "gateway_unavailable"
                else:
                    try:
                        limits = config.get("call_limits")
                        if limits is None:
                            # A retained Enable may precede policy capture, or have
                            # crashed after reserving its test but before linking it.
                            # Reattach that exact grant; never infer new limits.
                            with self.store.db() as db:
                                retained = db.execute(
                                    "SELECT g.body FROM connection_tests t JOIN grants g ON g.id=t.grant_id WHERE t.idem=?",
                                    ("enable-test:" + row["id"],),
                                ).fetchone()
                            if retained is None:
                                fault(
                                    "stale_context",
                                    "Retained Enable has no captured test limits; enable again",
                                )
                            limits = loads(retained["body"])["limits"]
                        grant = self.learning.test_connection(
                            conn["id"],
                            {
                                "idempotency_key": "enable-test:" + row["id"],
                                "expected_version": conn["version"],
                                "limits": limits,
                            },
                            call_policy=limits,
                        )
                        with self.store.db() as db:
                            db.execute(
                                "UPDATE connection_operations SET grant_id=? WHERE id=?",
                                (grant["id"], row["id"]),
                            )
                        return True
                    except RuntimeFault as exc:
                        error = exc.code
            else:
                grant = self.learning.grant_view(row["grant_id"])
                if not grant["outcome"]:
                    return False
                if grant["outcome"]["status"] != "succeeded":
                    error = grant["outcome"].get("error") or "provider_unavailable"
            enabled = error is None
            with self.store.db() as db, self.store.transaction(db):
                db.execute(
                    "UPDATE connection_operations SET status=?,error=? WHERE id=?",
                    ("completed" if enabled else "failed", error, row["id"]),
                )
                db.execute(
                    "UPDATE connection_control SET state=?,error=? WHERE id=1 AND operation_id=?",
                    ("enabled" if enabled else "disabled", error, row["id"]),
                )
                db.execute("UPDATE learning_control SET enabled=? WHERE id=1", (int(enabled),))
            return True

    def usage(self, zone="UTC", *, now=None):
        try:
            tz = ZoneInfo(zone)
        except (ValueError, ZoneInfoNotFoundError):
            fault("invalid_input", "Use an IANA timezone such as America/New_York")
        instant = datetime.fromtimestamp(self.learning.now() if now is None else now, timezone.utc)
        today = instant.astimezone(tz).date()
        days = {
            str(today - timedelta(days=n)): {"input_tokens": 0, "output_tokens": 0, "missing_usage": 0}
            for n in range(6, -1, -1)
        }
        # Floor in local time, then step in UTC so a DST fold has two distinct buckets.
        end = instant.astimezone(tz).replace(minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        hours = {
            (end - timedelta(hours=n)).timestamp(): {"succeeded": 0, "failed": 0, "unknown": 0, "active": 0}
            for n in range(23, -1, -1)
        }
        with self.store.db() as db:
            rows = db.execute(
                "SELECT * FROM grants WHERE COALESCE(dispatched_at,created)>=? ORDER BY seq",
                ((instant - timedelta(days=8)).timestamp(),),
            ).fetchall()
            for row in rows:
                if not row["calls"] or row["status"] in {"ready", "leased", "not_dispatched"}:
                    continue
                out = loads(row["outcome"]) if row["outcome"] else None
                if out:
                    out = self.learning._account_outcome(db, loads(row["body"]), out)
                timestamp = row["dispatched_at"] if row["dispatched_at"] is not None else row["created"]
                date = str(datetime.fromtimestamp(timestamp, timezone.utc).astimezone(tz).date())
                if date in days:
                    usage = out.get("usage") if out else None
                    if usage:
                        for field in ("input_tokens", "output_tokens"):
                            days[date][field] += usage[field]
                    else:
                        days[date]["missing_usage"] += 1
                bucket = end.timestamp() + ((timestamp - end.timestamp()) // 3600) * 3600
                if bucket in hours:
                    status = out.get("status") if out else None
                    label = (
                        "succeeded"
                        if status == "succeeded"
                        else "failed"
                        if status == "failed"
                        else "unknown"
                        if status == "outcome_unknown"
                        else "active"
                    )
                    hours[bucket][label] += 1
        return {
            "timezone": zone,
            "days": [{"date": date, **value} for date, value in days.items()],
            "hours": [
                {"start": datetime.fromtimestamp(stamp, timezone.utc).astimezone(tz).isoformat(), **value}
                for stamp, value in hours.items()
            ],
        }
