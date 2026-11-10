"""Durable bounded acquisition. The app owns authority; the gateway owns dispatch."""

import base64
import hashlib
import sqlite3
import threading
import time
from uuid import uuid4

from ..providers.diagnostics import account_outcome
from ..providers.wire import make_wire, provenance, specification
from ..runtime.protocol import RuntimeFault, dumps, loads
from ..runtime.supervisor import Supervisor
from .models import ConnectionInput, EpisodeInput, TestConnection

FINAL = {"accepted", "stopped", "cancelled", "rejected"}
RECEIPT_FINAL = {"accepted", "rejected", "invalid", "partial", "cancelled", "inconclusive"}


def uid():
    return str(uuid4())


def fingerprint(value):
    return "sha256:" + hashlib.sha256(dumps(value)).hexdigest()


def fault(code, message):
    raise RuntimeFault(code, message)


class LearningService:
    def __init__(self, runtime, *, start=True):
        self.runtime, self.store = runtime, runtime.store
        self.config = runtime.config
        self.supervisor = Supervisor(self.config.runtime.background_processes)
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.position = 0
        with self.store.db() as db:
            if self.config.learning.remote_calls_enabled:
                db.execute("UPDATE learning_control SET enabled=1,generation=1 WHERE generation=0")
            self.clock_base = max(
                time.time(), db.execute("SELECT clock FROM learning_control WHERE id=1").fetchone()[0]
            )
        self.clock_start = time.monotonic()
        from ..allowances.service import Allowances

        self.allowances = Allowances(self)
        self.recover()
        if start:
            self.thread = threading.Thread(target=self.loop, name="adm-learning", daemon=True)
            self.thread.start()

    def now(self):
        return max(time.time(), self.clock_base + time.monotonic() - self.clock_start)

    def settings(self):
        with self.store.db() as db:
            row = db.execute("SELECT * FROM learning_control WHERE id=1").fetchone()
        return {
            "generation": row["generation"],
            "remote_calls_enabled": bool(row["enabled"]),
            "gateway_key": loads(row["public_key"]) if row["public_key"] else None,
            "call_caps": self.config.learning.call.model_dump(),
            "episode_caps": self.config.learning.episode.model_dump(),
            "quotas": self.config.learning.quotas.model_dump(),
        }

    def configure(self, body):
        with self.store.db() as db, self.store.transaction(db):
            n = db.execute(
                "UPDATE learning_control SET generation=generation+1,enabled=? WHERE id=1 AND generation=?",
                (int(body["remote_calls_enabled"]), body["expected_generation"]),
            ).rowcount
            if not n:
                fault("stale_context", "Learning settings changed")
        self.wake.set()
        return self.settings()

    def connections(self, *, private=False):
        with self.store.db() as db:
            rows = db.execute(
                "SELECT c.* FROM connections c JOIN (SELECT id,max(version) AS version FROM connections GROUP BY id) v USING(id,version) ORDER BY seq"
            ).fetchall()
        return [self._connection(row, private=private) for row in rows]

    @staticmethod
    def _connection(row, *, private=False):
        value = loads(row["config"])
        value.update(
            id=row["id"], version=row["version"], configuration_digest=row["digest"], status=row["status"]
        )
        if not private:
            value["recorded_response_count"] = len(value.pop("recorded_responses", []))
            value.pop("sealed_credential", None)
            value.pop("sealing_key_id", None)
        return value

    def connection(self, key, version=None, *, private=False):
        with self.store.db() as db:
            row = db.execute(
                "SELECT * FROM connections WHERE id=? AND (? IS NULL OR version=?) ORDER BY version DESC LIMIT 1",
                (key, version, version),
            ).fetchone()
        if row is None:
            fault("not_found", "Connection not found")
        return self._connection(row, private=private)

    def save_connection(self, body, key=None):
        expected = body.pop("expected_version", None) if isinstance(body, dict) else None
        body = ConnectionInput.model_validate(body).model_dump()
        raw, digest = dumps(body), fingerprint(body)
        if len(raw) > self.config.server.max_body_bytes - 8192:
            fault("resource_exhausted", "Connection configuration exceeds byte allowance")
        with self.store.db() as db, self.store.transaction(db):
            old = db.execute("SELECT * FROM connections WHERE idem=?", (body["idempotency_key"],)).fetchone()
            if old:
                if old["digest"] != digest or (key is not None and old["id"] != key):
                    fault("conflict", "Idempotency key has different configuration")
                return self._connection(old)
            if db.execute("SELECT count(*) FROM connections").fetchone()[0] >= 1000:
                fault("quota_exceeded", "Retained connection allowance exhausted")
            version = 1
            if key:
                current = self.connection(key)
                if current["version"] != expected:
                    fault("stale_context", "Connection version changed")
                version += current["version"]
            else:
                key = uid()
            self.store.capacity(len(raw) + 4096)
            db.execute(
                "INSERT INTO connections(id,version,idem,digest,config,status) VALUES(?,?,?,?,?,'pending')",
                (key, version, body["idempotency_key"], digest, raw),
            )
        self.wake.set()
        return self.connection(key)

    def synchronize(self, public_key, acknowledgments, deletion_acknowledgments=()):
        if (
            set(public_key) != {"key_id", "algorithm", "spki"}
            or public_key["algorithm"] != "RSA-OAEP-256"
            or len(dumps(public_key)) > 4096
        ):
            fault("invalid_input", "Invalid gateway sealing key")
        with self.store.db() as db, self.store.transaction(db):
            db.execute("UPDATE learning_control SET public_key=? WHERE id=1", (dumps(public_key),))
            for ack in acknowledgments:
                if ack.get("status") not in ("ready", "credential_unavailable"):
                    fault("invalid_input", "Invalid connection acknowledgment")
                db.execute(
                    "UPDATE connections SET status=? WHERE id=? AND version=? AND digest=?",
                    (ack["status"], ack["id"], ack["version"], ack["configuration_digest"]),
                )
        # Include all retained versions: a version may depend on its preceding encrypted key.
        with self.store.db() as db:
            rows = db.execute(
                "SELECT * FROM connections WHERE status='pending' ORDER BY seq LIMIT 1"
            ).fetchall()
        return {
            "connections": [self._connection(r, private=True) for r in rows],
            "deletions": self.runtime.lifecycle.gateway_cleanup(deletion_acknowledgments),
        }

    def _caps(self, body):
        for group, limits in (
            ("limits", self.config.learning.episode),
            ("call_limits", self.config.learning.call),
        ):
            for key, value in body[group].items():
                if value > getattr(limits, key):
                    fault("invalid_limits", "Learning limits exceed configured caps")

    def _usable(self, key, version, purpose):
        c = self.connection(key, private=True)
        if (
            c["version"] != version
            or not c["enabled"]
            or c["status"] != "ready"
            or purpose not in c["purposes"]
        ):
            fault("stale_context", "Connection is disabled, changed or unavailable")
        if c["provider"] != "recorded" and not self.settings()["remote_calls_enabled"]:
            fault("remote_calls_disabled", "Remote calls are disabled")
        return c

    def create(self, key, body, *, parent_task=None):
        body = EpisodeInput.model_validate(body).model_dump()
        if body.get("allowance_id") is None:
            body.pop("allowance_id", None)
        self._caps(body)
        raw, digest = dumps(body), fingerprint(body)
        with self.store.lock:
            with self.store.db(key) as db:
                old = db.execute(
                    "SELECT digest,data FROM episodes WHERE idem=?", (body["idempotency_key"],)
                ).fetchone()
                if old:
                    if old["digest"] != digest:
                        fault("conflict", "Idempotency key has different episode input")
                    saved = loads(old["data"])
                    if saved.get("parent_task") != parent_task:
                        fault("conflict", "Episode has another parent owner")
                    return saved
            current = self.store.info(key)
            if current["revision_id"] != body["expected_revision"] or current["archived"]:
                fault("stale_context", "Displayed ADM revision changed or is archived")
            self._usable(body["connection_id"], body["connection_version"], "acquisition")
            # Policy eligibility is checked from the receiver's own snapshot in a
            # bounded child before checked-auto can publish, never provider input.
            if body.get("allowance_id"):
                self.allowances.child(
                    body["allowance_id"],
                    {
                        "operation_id": "episode:" + body["idempotency_key"],
                        "kind": "episode",
                        "max_work": body["limits"]["max_work"],
                        "payload_digest": digest,
                    },
                )
            now = self.now()
            ep = {
                "id": uid(),
                "adm_id": key,
                "body": body,
                "status": "queued",
                "reason": None,
                "base_revision": current["revision_id"],
                "draft": None,
                "feedback": [],
                "history": [],
                "work": 0,
                "no_progress": 0,
                "fingerprint": None,
                "grant_id": None,
                "created": now,
                "deadline": now + body["limits"]["max_duration_ms"] / 1000,
                "parent_task": parent_task,
                "generation": self.store.generation,
                "authority_generation": self.settings()["generation"],
            }
            with self.store.db(key) as db, self.store.transaction(db):
                count, size = db.execute(
                    "SELECT count(*),COALESCE(sum(length(data)),0) FROM episodes"
                ).fetchone()
                if (
                    count >= self.config.runtime.queue_items_per_adm
                    or size + len(raw) > self.config.runtime.queue_bytes_per_adm
                ):
                    fault("quota_exceeded", "Learning history allowance exhausted")
                for request in body["request_ids"]:
                    row = db.execute("SELECT * FROM requests WHERE id=?", (request,)).fetchone()
                    if (
                        row is None
                        or row["status"] not in ("needs_input", "waiting_for_learning")
                        or loads(row["context"])["policy_epoch"] != current["policy_epoch"]
                    ):
                        fault("conflict", "Only pending requests under this owner epoch can join learning")
                    db.execute("INSERT INTO interests VALUES(?,?)", (ep["id"], request))
                    db.execute(
                        "UPDATE requests SET status='waiting_for_learning',updated=? WHERE id=?",
                        (now, request),
                    )
                    self.store.emit(
                        db,
                        key,
                        "request.waiting_for_learning",
                        request,
                        context=current,
                        data={"episode_id": ep["id"]},
                    )
                self.store.capacity(len(raw) + 4096)
                db.execute(
                    "INSERT INTO episodes(id,idem,digest,data) VALUES(?,?,?,?)",
                    (ep["id"], body["idempotency_key"], digest, dumps(ep)),
                )
                self.store.emit(db, key, "episode.queued", ep["id"], context=current)
        self.wake.set()
        return ep

    def episodes(self, key):
        self.store.info(key)
        with self.store.db(key) as db:
            return [
                self._summary(loads(r[0]))
                for r in db.execute("SELECT data FROM episodes ORDER BY seq DESC LIMIT 100")
            ]

    @staticmethod
    def _summary(ep):
        return {
            k: ep[k]
            for k in (
                "id",
                "adm_id",
                "status",
                "reason",
                "work",
                "no_progress",
                "created",
                "deadline",
                "base_revision",
                "grant_id",
            )
        }

    def episode(self, key, episode):
        with self.store.db(key) as db:
            row = db.execute("SELECT data FROM episodes WHERE id=?", (episode,)).fetchone()
            if not row:
                fault("not_found", "Unknown episode")
            ep = loads(row[0])
            ep["receipts"] = [
                dict(r, data=loads(r["data"]))
                for r in db.execute(
                    "SELECT * FROM learning_receipts WHERE episode=? ORDER BY seq", (episode,)
                )
            ]
        ep["usage"] = self.usage(episode=episode)
        ep["provider_failure"] = self.provider_failure(ep.get("grant_id"))
        return ep

    def _get(self, key, episode):
        with self.store.db(key) as db:
            row = db.execute("SELECT data FROM episodes WHERE id=?", (episode,)).fetchone()
            return loads(row[0]) if row else None

    def _save(self, db, ep):
        raw = dumps(ep)
        if len(raw) > self.config.runtime.queue_bytes_per_adm:
            fault("quota_exceeded", "Episode exceeds retained byte allowance")
        self.store.capacity(len(raw))
        db.execute("UPDATE episodes SET data=? WHERE id=?", (raw, ep["id"]))

    def _stop(self, key, ep, reason, status="stopped"):
        with self.store.db(key) as db, self.store.transaction(db):
            ep.update(status=status, reason=reason)
            self._save(db, ep)
            db.execute(
                "UPDATE learning_receipts SET status='cancelled' WHERE episode=? AND status IN ('received','complete','awaiting_review','approved','validating')",
                (ep["id"],),
            )
            self.store.emit(db, key, "episode.stopped", ep["id"], data={"reason": reason, "status": status})
            for row in db.execute(
                "SELECT r.* FROM requests r JOIN interests i ON r.id=i.request WHERE i.episode=? AND r.status='waiting_for_learning'",
                (ep["id"],),
            ).fetchall():
                other = db.execute(
                    "SELECT e.data FROM episodes e JOIN interests i ON e.id=i.episode WHERE i.request=? AND e.id<>?",
                    (row["id"], ep["id"]),
                ).fetchall()
                if not any(loads(r[0])["status"] not in FINAL for r in other):
                    self.store._terminal(db, key, row, "needs_input")
        return ep

    def cancel(self, key, episode):
        with self.store.lock:
            ep = self._get(key, episode)
            if ep is None:
                fault("not_found", "Unknown episode")
            if ep["status"] not in FINAL:
                self._stop(key, ep, "owner_cancelled", "cancelled")
        return self.episode(key, episode)

    def _interested(self, key, ep):
        if not ep["body"]["request_ids"]:
            return True  # Explicit manually initiated episode owns its interest.
        with self.store.db(key) as db:
            return bool(
                db.execute(
                    "SELECT 1 FROM requests r JOIN interests i ON i.request=r.id WHERE i.episode=? AND r.status IN ('waiting_for_learning','received','evaluating','needs_input')",
                    (ep["id"],),
                ).fetchone()
            )

    def usage(self, *, episode=None, adm=None, lane=None):
        with self.store.db() as db:
            now = max(self.now(), db.execute("SELECT clock FROM learning_control WHERE id=1").fetchone()[0])
            db.execute("UPDATE learning_control SET clock=? WHERE id=1", (now,))
            rows = db.execute("SELECT * FROM grants").fetchall()
        selected = [
            r
            for r in rows
            if (episode is None or r["episode"] == episode)
            and (adm is None or r["adm"] == adm)
            and (lane is None or r["lane"] == lane)
            and (
                episode is not None
                or r["unresolved"]
                or r["created"] >= now - self.config.learning.quotas.period_seconds
            )
        ]
        return {
            "calls": sum(r["calls"] for r in selected),
            "input_tokens": sum(r["input_tokens"] for r in selected),
            "output_tokens": sum(r["output_tokens"] for r in selected),
            "unresolved": sum(r["unresolved"] for r in selected),
        }

    def usage_snapshot(self, db, *, adm=None, lane=None):
        """Read counters inside a caller transaction without taking a second write lock."""
        now = max(self.now(), db.execute("SELECT clock FROM learning_control WHERE id=1").fetchone()[0])
        rows = db.execute("SELECT * FROM grants").fetchall()
        selected = [
            r
            for r in rows
            if (adm is None or r["adm"] == adm)
            and (lane is None or r["lane"] == lane)
            and (r["unresolved"] or r["created"] >= now - self.config.learning.quotas.period_seconds)
        ]
        return {
            field: sum(r[field] for r in selected) for field in ("calls", "input_tokens", "output_tokens")
        }

    def reserve(self, body, *, adm=None, episode=None, test_intent=None):
        """Reserve before an external worker can see a call. Never refund uncertainty."""
        from ..allowances.pricing import lane

        with self.store.lock:
            if adm:
                self.store.info(adm)
            body = dict(body)
            if body.get("operation_id"):
                with self.store.db() as db:
                    prior = db.execute(
                        "SELECT id,body FROM grants WHERE json_extract(body,'$.operation_id')=? AND json_extract(body,'$.allowance_id')=?",
                        (body["operation_id"], body.get("allowance_id")),
                    ).fetchone()
                if prior:
                    old = loads(prior["body"])
                    if (
                        any(
                            old.get(k) != body.get(k)
                            for k in (
                                "purpose",
                                "wire",
                                "connection_id",
                                "connection_version",
                                "base_revision",
                                "limits",
                            )
                        )
                        or old["adm"] != adm
                    ):
                        fault("conflict", "Provider child identity has different content")
                    return prior["id"]
            price = self.allowances.prepare(body, adm)
            body["lane"] = lane(body["purpose"])
            reserve = {
                "calls": 1,
                "input_tokens": body["input_estimate"],
                "output_tokens": body["limits"]["max_output_tokens"],
            }
            if reserve["input_tokens"] > body["limits"]["max_input_tokens"]:
                fault("invalid_limits", "Exact wire estimate exceeds the call input cap")
            for scope, usage in (("installation", self.usage()), ("per_adm", self.usage(adm=adm))):
                if scope == "per_adm" and adm is None:
                    continue
                with self.store.db() as registry:
                    held = self.allowances.summary_holds(
                        registry,
                        adm=adm if scope == "per_adm" else None,
                        consuming=body.get("allowance_id") if body["purpose"] == "task_narration" else None,
                    )
                for field, amount in reserve.items():
                    if usage[field] + held[field] + amount > getattr(
                        self.config.learning.quotas, field + "_" + scope
                    ):
                        fault("quota_exceeded", "Provider reservation exceeds aggregate allowance")
            # Independently protected lane shares within the unchanged total quotas.
            for scope in ("installation", "per_adm"):
                if scope == "per_adm" and adm is None:
                    continue
                used = self.usage(adm=adm if scope == "per_adm" else None, lane=body["lane"])
                with self.store.db() as registry:
                    held = self.allowances.summary_holds(
                        registry,
                        adm=adm if scope == "per_adm" else None,
                        lane=body["lane"],
                        consuming=body.get("allowance_id") if body["purpose"] == "task_narration" else None,
                    )
                share = 40 if body["lane"] == "interaction" else 60
                for field, n in reserve.items():
                    cap = max(1, getattr(self.config.learning.quotas, field + "_" + scope) * share // 100)
                    if used[field] + held[field] + n > cap:
                        fault("quota_exceeded", "Provider lane quota exhausted")
            if episode:
                ep = self._get(adm, episode)
                used = self.usage(episode=episode)
                for field, amount in reserve.items():
                    if used[field] + amount > ep["body"]["limits"]["max_" + field]:
                        fault("quota_exceeded", "Episode provider allowance exhausted")
            body = {
                **body,
                "id": uid(),
                "adm": adm,
                "episode": episode,
                "generation": self.store.generation,
                "settings_generation": self.settings()["generation"],
                "lease": uid(),
                "expires": None,
            }
            with self.store.db() as db, self.store.transaction(db):
                if db.execute("SELECT count(*) FROM grants").fetchone()[0] >= 10000:
                    fault("quota_exceeded", "Retained grant allowance exhausted")
                if body["purpose"] not in {"acquisition", "interpretation", "extraction", "connection_test"}:
                    self._grant_valid(body)
                self.allowances.reserve(db, body, price)
                self.store.capacity(len(dumps(body)) + 4096)
                db.execute(
                    "INSERT INTO grants(id,adm,episode,status,body,created,input_tokens,output_tokens,lane) VALUES(?,?,?,'ready',?,?,?,?,?)",
                    (
                        body["id"],
                        adm,
                        episode,
                        dumps(body),
                        self.now(),
                        reserve["input_tokens"],
                        reserve["output_tokens"],
                        body["lane"],
                    ),
                )
                if test_intent:
                    db.execute(
                        "INSERT INTO connection_tests VALUES(?,?,?,?)",
                        (uid(), test_intent[0], test_intent[1], body["id"]),
                    )
            return body["id"]

    def test_connection(self, key, body):
        body = TestConnection.model_validate(body).model_dump()
        if body.get("allowance_id") is None:
            body.pop("allowance_id", None)
        for field, value in body["limits"].items():
            if value > getattr(self.config.learning.call, field):
                fault("invalid_limits", "Connection-test cap exceeds configured allowance")
        with self.store.lock:
            with self.store.db() as db:
                old = db.execute(
                    "SELECT * FROM connection_tests WHERE idem=?", (body["idempotency_key"],)
                ).fetchone()
                identity = fingerprint({"connection": key, **body})
                if old:
                    if old["digest"] != identity:
                        fault("conflict", "Test idempotency key has different input")
                    return self.grant_view(old["grant_id"])
            c = self._usable(key, body["expected_version"], "connection_test")
            spec = specification(connection_test=True)
            raw, estimate = make_wire(c, spec, body["limits"]["max_output_tokens"])
            grant = self.reserve(
                {
                    "purpose": "connection_test",
                    "allowance_id": body.get("allowance_id"),
                    "connection_id": key,
                    "connection_version": c["version"],
                    "configuration_digest": c["configuration_digest"],
                    "wire": base64.b64encode(raw).decode(),
                    "input_estimate": estimate,
                    "limits": body["limits"],
                    "provenance": provenance(spec, raw),
                    "recorded_index": 0,
                    "deadline": self.now() + body["limits"]["max_duration_ms"] / 1000,
                },
                test_intent=(body["idempotency_key"], identity),
            )
        return self.grant_view(grant)

    def grant_view(self, grant):
        with self.store.db() as db:
            row = db.execute("SELECT * FROM grants WHERE id=?", (grant,)).fetchone()
        if not row:
            fault("not_found", "Unknown dispatch")
        out = loads(row["outcome"]) if row["outcome"] else None
        if out:
            with self.store.db() as db:
                out = self._account_outcome(db, loads(row["body"]), out)
            out.pop("text", None)
        return {
            "id": grant,
            "status": row["status"],
            "outcome": out,
            "calls": row["calls"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "unresolved": bool(row["unresolved"]),
            "lane": row["lane"],
            "price_binding": loads(row["body"]).get("price_binding"),
        }

    @staticmethod
    def _account_outcome(db, body, outcome):
        config = db.execute(
            "SELECT config FROM connections WHERE id=? AND version=?",
            (body["connection_id"], body["connection_version"]),
        ).fetchone()
        provider = loads(config[0])["provider"] if config else "unknown"
        return account_outcome(outcome, provider)

    def provider_failure(self, grant):
        if not grant:
            return None
        view = self.grant_view(grant)
        outcome = view["outcome"]
        return view if outcome and outcome["status"] in ("failed", "outcome_unknown") else None

    def _parent_active(self, key, ep):
        if not ep.get("parent_task"):
            return True
        conversations = getattr(self.runtime, "conversations", None)
        return bool(conversations and conversations.teaching.execution.parent(key, ep))

    def _grant_valid(self, body):
        from ..allowances.pricing import lane

        if body.get("adm"):
            self.store.info(body["adm"])

        with self.store.db() as registry:
            if registry.execute(
                "SELECT suspended FROM provider_lanes WHERE lane=?", (lane(body["purpose"]),)
            ).fetchone()[0]:
                fault("quota_exceeded", "Provider lane suspended after a usage overrun")
            if body.get("allowance_id"):
                self.allowances.valid(registry, body["allowance_id"])
                if (
                    body.get("spending_generation") is not None
                    and body["spending_generation"]
                    != registry.execute("SELECT generation FROM spending_control WHERE id=1").fetchone()[0]
                ):
                    fault("stale_context", "Installation spending authority changed")
            if body["purpose"] not in {"acquisition", "interpretation", "extraction", "connection_test"}:
                child = registry.execute(
                    "SELECT body FROM budget_children WHERE allowance_id=? AND operation_id=?",
                    (body.get("allowance_id"), body.get("operation_id")),
                ).fetchone()
                if not child or loads(child[0])["payload_digest"] != body["provenance"]["request_hash"]:
                    fault("forbidden", "Provider step lacks its exact parent child reservation")
                if self.store.info(body["adm"])["revision_id"] != body["base_revision"]:
                    fault("stale_context", "Provider step context changed")
        if body["generation"] != self.store.generation or self.now() >= body["deadline"]:
            fault("stale_context", "Dispatch expired or belongs to a previous app generation")
        self._usable(body["connection_id"], body["connection_version"], body["purpose"])
        if body["settings_generation"] != self.settings()["generation"]:
            fault("stale_context", "Learning authority changed")
        if body.get("teaching_task_id"):
            self.runtime.conversations.teaching.execution.narration_valid(body)
        if body.get("conversation_work_id"):
            self.runtime.conversations.grant_valid(body)
        if body["purpose"] == "extraction":
            self.runtime.sources.grant_valid(body)
        if body["purpose"] == "interpretation":
            self.runtime.language.grant_valid(body)
        if body["episode"]:
            ep = self._get(body["adm"], body["episode"])
            if not self._parent_active(body["adm"], ep):
                fault("stale_context", "Parent task is paused or not ready")
            if (
                ep["status"] != "acquiring"
                or ep["grant_id"] != body["id"]
                or not self._interested(body["adm"], ep)
            ):
                fault("stale_context", "Episode no longer owns this dispatch")
            if self.store.info(body["adm"])["revision_id"] != body["base_revision"]:
                fault("stale_context", "Construction context changed before dispatch")

    def claim(self):
        with self.store.lock, self.store.db() as db, self.store.transaction(db):
            active = db.execute(
                "SELECT count(*) FROM grants WHERE status IN ('leased','dispatched')"
            ).fetchone()[0]
            if active >= self.config.runtime.provider_concurrency:
                return None
            rows = db.execute("SELECT * FROM grants WHERE status='ready' ORDER BY seq").fetchall()
            lanes = db.execute("SELECT * FROM provider_lanes ORDER BY last_claim,lane").fetchall()
            ordered = []
            for selected in lanes:
                queue = [r for r in rows if r["lane"] == selected["lane"]]
                adms = sorted({r["adm"] or "" for r in queue})
                last = selected["last_adm"] or ""
                adms = [a for a in adms if a > last] + [a for a in adms if a <= last]
                if selected["last_adm"] is None and queue:
                    initial = adms.index(queue[0]["adm"] or "")
                    adms = adms[initial:] + adms[:initial]
                for adm in adms:
                    ordered.extend(r for r in queue if (r["adm"] or "") == adm)
            rows = ordered  # Lane and ADM round-robin, FIFO inside each ADM.
            for row in rows:
                # Fixed protected lane slots also bound background work to one.
                if db.execute(
                    "SELECT 1 FROM grants WHERE lane=? AND status IN ('leased','dispatched') LIMIT 1",
                    (row["lane"],),
                ).fetchone():
                    continue
                body = loads(row["body"])
                if (
                    body["adm"]
                    and db.execute(
                        "SELECT count(*) FROM grants WHERE adm=? AND status IN ('leased','dispatched')",
                        (body["adm"],),
                    ).fetchone()[0]
                    >= self.config.runtime.provider_concurrency_per_adm
                ):
                    continue
                try:
                    if (
                        body.get("source_job_id")
                        and getattr(self.runtime, "conversations", None)
                        and self.runtime.conversations.intake.dispatch_paused(
                            body["adm"], body["source_job_id"]
                        )
                    ):
                        continue
                    if body.get("episode") and not self._parent_active(
                        body["adm"], self._get(body["adm"], body["episode"])
                    ):
                        continue
                    self._grant_valid(body)
                except RuntimeFault:
                    self.allowances.settle(db, row["id"], not_dispatched=True)
                    db.execute(
                        "UPDATE grants SET status='not_dispatched',calls=0,input_tokens=0,output_tokens=0,unresolved=0,outcome=? WHERE id=?",
                        (
                            dumps(
                                {
                                    "status": "not_dispatched",
                                    "error": "authority_changed",
                                    "usage": None,
                                    "text": None,
                                }
                            ),
                            row["id"],
                        ),
                    )
                    continue
                body["expires"] = min(body["deadline"], self.now() + body["limits"]["max_duration_ms"] / 1000)
                db.execute("UPDATE grants SET status='leased',body=? WHERE id=?", (dumps(body), row["id"]))
                db.execute(
                    "UPDATE provider_lanes SET last_adm=?,last_claim=(SELECT max(last_claim)+1 FROM provider_lanes) WHERE lane=?",
                    (body["adm"], row["lane"]),
                )
                return {
                    "grant_id": body["id"],
                    "lease": body["lease"],
                    "timeout_ms": body["limits"]["max_duration_ms"],
                }
        return None

    def authorize(self, grant, lease):
        with self.store.db() as db, self.store.transaction(db):
            row = db.execute("SELECT * FROM grants WHERE id=?", (grant,)).fetchone()
            if row is None:
                fault("not_found", "Unknown grant")
            body = loads(row["body"])
            if (
                row["status"] not in ("leased", "dispatched")
                or body["lease"] != lease
                or body["expires"] <= self.now()
            ):
                fault("stale_context", "Dispatch lease is stale")
            self._grant_valid(body)
            db.execute("UPDATE grants SET status='dispatched' WHERE id=?", (grant,))
            from ..application.store import context_binding
            from ..contracts import DispatchGrant

            connection = self.connection(body["connection_id"], body["connection_version"])
            context = (
                context_binding(self.store.revision(body["adm"], body["base_revision"])["context"])
                if body["adm"]
                else None
            )
            body["grant"] = DispatchGrant(
                grant_id=grant,
                reservation_id=grant,
                gateway_id="provider-gateway",
                lease={
                    "job_id": body["episode"] or grant,
                    "attempt_id": grant,
                    "worker_id": "learning-worker",
                    "lease_token": lease,
                    "purpose": body["purpose"],
                    "context": context,
                    "control_scope_id": None if context else "installation",
                    "input_digest": body["provenance"]["request_hash"],
                    "issued_at_ms": int(self.now() * 1000),
                    "expires_at_ms": int(body["expires"] * 1000),
                },
                provider_configuration={
                    k: connection[k] for k in ("configuration_digest", "provider", "model")
                }
                | {"connection_id": connection["id"]},
                request_digest=body["provenance"]["request_hash"],
                limits=body["limits"],
            ).model_dump()
            return body

    def outcome(self, grant, lease, outcome):
        with self.store.lock:
            return self._outcome(grant, lease, outcome)

    def _outcome(self, grant, lease, outcome):
        from .models import Outcome

        outcome = Outcome.model_validate(outcome).model_dump()
        with self.store.db() as db, self.store.transaction(db):
            row = db.execute("SELECT * FROM grants WHERE id=?", (grant,)).fetchone()
            if row is None or loads(row["body"])["lease"] != lease:
                fault("stale_context", "Outcome does not own a grant")
            if row["outcome"] and row["status"] not in ("outcome_unknown",):
                return {"recorded": True}
            body = loads(row["body"])
            if row["status"] not in ("dispatched", "leased", "outcome_unknown"):
                fault("stale_context", "Grant has not been dispatched")
            outcome = self._account_outcome(db, body, outcome)
            deleted = body.get("model_deleted") or (
                body.get("adm")
                and db.execute(
                    "SELECT 1 FROM instances WHERE id=? AND status IN ('deleting','deleted')", (body["adm"],)
                ).fetchone()
            )
            if deleted:
                from ..lifecycle.service import accounting_outcome

                outcome = accounting_outcome(outcome)
            known = outcome["usage"]
            # Missing usage retains the full reservation, including across periods.
            inputs = known["input_tokens"] if known else row["input_tokens"]
            outputs = known["output_tokens"] if known else row["output_tokens"]
            if known and (inputs > row["input_tokens"] or outputs > row["output_tokens"]):
                outcome.update(status="failed", error="provider_usage_exceeded_reservation", text=None)
                db.execute("UPDATE provider_lanes SET suspended=1 WHERE lane=?", (row["lane"],))
            self.allowances.settle(db, grant, known)
            if body["purpose"] == "connection_test" and outcome["status"] == "succeeded":
                try:
                    from ..wire import decode

                    test_output = decode(outcome["text"].encode())
                    if (
                        not isinstance(test_output, dict)
                        or set(test_output) != {"ok"}
                        or test_output["ok"] is not True
                    ):
                        raise ValueError
                except (ValueError, AttributeError):
                    outcome.update(status="failed", error="invalid_connection_test", text=None)
            if not deleted and body["episode"] and body.get("receipt_sequence") is None:
                ep = self._get(body["adm"], body["episode"])
                if (
                    ep["status"] == "acquiring"
                    and ep["grant_id"] == grant
                    and body["generation"] == self.store.generation
                    and body["expires"] > self.now()
                ):
                    body["receipt_sequence"] = self.next_receipt_sequence(body["adm"])
            db.execute(
                "UPDATE grants SET status=?,outcome=?,input_tokens=?,output_tokens=?,unresolved=?,body=? WHERE id=?",
                (outcome["status"], dumps(outcome), inputs, outputs, int(known is None), dumps(body), grant),
            )
        # Receipt priority is durably allocated with accounting at the receiver.
        # Copying into the per-ADM inbox can retry without changing that priority.
        if not deleted and body.get("receipt_sequence"):
            self._receive(body["adm"], self._get(body["adm"], body["episode"]), body, outcome)
        self.wake.set()
        return {"recorded": True}

    def _receive(self, key, ep, grant, outcome):
        with self.store.db(key) as db, self.store.transaction(db):
            if db.execute("SELECT 1 FROM learning_receipts WHERE id=?", (grant["id"],)).fetchone():
                return
            data = {
                "grant": grant,
                "outcome": outcome,
                "base_revision": grant["base_revision"],
                "approval_revision": None,
            }
            active = ep["status"] not in FINAL
            seq = db.execute(
                "INSERT INTO learning_receipts(seq,id,episode,status,data) VALUES(?,?,?,?,?)",
                (
                    grant.get("receipt_sequence"),
                    grant["id"],
                    ep["id"],
                    "received" if active else "cancelled",
                    dumps(data),
                ),
            ).lastrowid
            if active:
                ep.update(status="received")
            self._save(db, ep)
            self.store.emit(
                db,
                key,
                "candidate.received",
                grant["id"],
                data={"episode_id": ep["id"], "receipt_sequence": seq, "classification": "pending"},
            )

    def review(self, key, receipt, body):
        with self.store.lock, self.store.db(key) as db, self.store.transaction(db):
            if self.store.info(key)["revision_id"] != body["expected_revision"]:
                fault("stale_context", "Review context changed")
            row = db.execute("SELECT * FROM learning_receipts WHERE id=?", (receipt,)).fetchone()
            if row is None:
                fault("not_found", "Unknown candidate")
            if row["status"] not in ("awaiting_review", "approved"):
                fault("conflict", "Candidate cannot be reviewed in this state")
            ep = self._get(key, row["episode"])
            if ep.get("parent_task"):
                fault("forbidden", "Review this candidate through its teaching task")
            data = loads(row["data"])
            data["approval_revision"] = body["expected_revision"] if body["approve"] else None
            db.execute(
                "UPDATE learning_receipts SET status=?,data=? WHERE id=?",
                ("approved" if body["approve"] else "rejected", dumps(data), receipt),
            )
            ep = self._get(key, row["episode"])
            ep.update(
                status="ready" if body["approve"] else "rejected",
                reason=None if body["approve"] else "owner_declined",
            )
            self._save(db, ep)
        if not body["approve"]:
            self._stop(key, ep, "owner_declined", "rejected")
        self.wake.set()
        return self.episode(key, row["episode"])

    def recover(self):
        with self.store.db() as db:
            # Old binaries settled remote 0/0 reports. Retain the original
            # outcome as evidence, but restore its original reservation. This
            # is idempotent, keeps terminal status, and never redispatches.
            for row in db.execute("SELECT * FROM grants WHERE outcome IS NOT NULL").fetchall():
                outcome, body = loads(row["outcome"]), loads(row["body"])
                if outcome.get("usage") == {"input_tokens": 0, "output_tokens": 0} and row["calls"]:
                    assessed = self._account_outcome(db, body, outcome)
                    if assessed["diagnostics"].get("usage_assessment") == "zero_unverified":
                        db.execute(
                            "UPDATE grants SET unresolved=1,input_tokens=?,output_tokens=? WHERE id=?",
                            (
                                max(row["input_tokens"], body["input_estimate"]),
                                max(row["output_tokens"], body["limits"]["max_output_tokens"]),
                                row["id"],
                            ),
                        )
            unknown = dumps(
                {"status": "outcome_unknown", "error": "app_restarted", "usage": None, "text": None}
            )
            db.execute(
                "UPDATE grants SET status='outcome_unknown',outcome=? WHERE status IN ('leased','dispatched')",
                (unknown,),
            )
            db.execute(
                "UPDATE grants SET status='not_dispatched',calls=0,input_tokens=0,output_tokens=0,unresolved=0,outcome=? WHERE status='ready'",
                (dumps({"status": "not_dispatched", "error": "app_restarted", "usage": None, "text": None}),),
            )
            self.allowances.reconcile(db)
        for item in self.store.list():
            if item["status"] != "ready":
                continue
            with self.store.db(item["id"]) as db:
                eps = [loads(r[0]) for r in db.execute("SELECT data FROM episodes")]
            for ep in eps:
                if ep["status"] not in FINAL:
                    if ep.get("parent_task") and ep["status"] in {
                        "queued",
                        "received",
                        "awaiting_review",
                        "ready",
                    }:
                        continue
                    self._stop(item["id"], ep, "app_restarted")

    def close(self):
        self.stop_event.set()
        self.wake.set()
        self.supervisor.close()
        if self.thread:
            self.thread.join(timeout=self.config.request.max_duration_ms / 1000 + 4)

    def loop(self):
        while not self.stop_event.is_set():
            try:
                progress = self.tick()
            except (RuntimeFault, ValueError, OSError, sqlite3.Error):
                progress = False
            if not progress:
                self.wake.wait(0.25)
                self.wake.clear()

    def _compute(self, key, ep, operation, extra):
        with self.store.lock:
            fresh = self._get(key, ep["id"])
            if fresh["status"] in FINAL:
                fault("stale_context", "Episode stopped")
            remaining = fresh["body"]["limits"]["max_work"] - fresh["work"]
            if remaining <= 0:
                fault("resource_exhausted", "Episode local-work allowance exhausted")
            caps = self.runtime.limits()
            if ep.get("parent_task"):
                caps["max_work"] = min(caps["max_work"], 1000000)
                caps["max_duration_ms"] = min(caps["max_duration_ms"], 5000)
            caps["max_work"] = min(caps["max_work"], remaining)
            if operation != "learning_admit":
                caps["max_duration_ms"] = min(
                    caps["max_duration_ms"], max(1, int((ep["deadline"] - self.now()) * 1000))
                )
            fresh["work"] += caps["max_work"]  # crashes keep the whole reservation
            with self.store.db(key) as db:
                self._save(db, fresh)
        task = {
            "operation": operation,
            "limits": caps,
            "body": ep["body"],
            "snapshot": self.store.revision(key, ep["base_revision"])["snapshot"],
            "draft": ep["draft"],
            "feedback": ep["feedback"],
            **extra,
        }
        value = self.supervisor.run(task, cancel=self.stop_event, scope=key)
        used = value["work"]
        if type(used) is not int or not 0 <= used <= caps["max_work"]:
            fault("invalid_result", "Invalid local-work accounting")
        with self.store.lock:
            fresh = self._get(key, ep["id"])
            fresh["work"] -= caps["max_work"] - used
            with self.store.db(key) as db:
                self._save(db, fresh)
        return value

    def next_receipt_sequence(self, key):
        self.store.info(key)
        """Called with the store lock: one receiver order for every candidate source."""
        with self.store.db() as db:
            values = [
                loads(r[0]).get("receipt_sequence", 0)
                for r in db.execute("SELECT body FROM grants WHERE adm=?", (key,))
            ]
            values.append(
                db.execute("SELECT COALESCE(max(seq),0) FROM source_arrivals WHERE adm=?", (key,)).fetchone()[
                    0
                ]
            )
        with self.store.db(key) as db:
            values.append(db.execute("SELECT COALESCE(max(seq),0) FROM learning_receipts").fetchone()[0])
        return max(values) + 1

    def reconcile_receipts(self, key):
        with self.store.lock:
            with self.store.db() as db:
                incoming = [
                    (loads(r["body"]), loads(r["outcome"]))
                    for r in db.execute(
                        "SELECT body,outcome FROM grants WHERE adm=? AND outcome IS NOT NULL", (key,)
                    )
                    if loads(r["body"]).get("receipt_sequence")
                ]
            for grant, outcome in sorted(incoming, key=lambda pair: pair[0]["receipt_sequence"]):
                self._receive(key, self._get(key, grant["episode"]), grant, outcome)
            sources = getattr(self.runtime, "sources", None)
            if sources is not None:
                sources.reconcile(key)
            else:
                with self.store.db() as db:
                    if db.execute("SELECT 1 FROM source_arrivals WHERE adm=? LIMIT 1", (key,)).fetchone():
                        fault("busy", "Source receipt recovery is initializing")

    def tick(self):
        # Timeouts retain reservations; expired dispatched calls are never reissued.
        with self.store.db() as db:
            for row in db.execute("SELECT * FROM grants WHERE status IN ('leased','dispatched')").fetchall():
                if loads(row["body"])["expires"] <= self.now():
                    db.execute(
                        "UPDATE grants SET status='outcome_unknown',outcome=? WHERE id=?",
                        (
                            dumps(
                                {
                                    "status": "outcome_unknown",
                                    "error": "lease_expired",
                                    "usage": None,
                                    "text": None,
                                }
                            ),
                            row["id"],
                        ),
                    )
        keys = [r["id"] for r in self.store.list() if r["status"] == "ready"]
        if not keys:
            return False
        self.position %= len(keys)
        keys = keys[self.position :] + keys[: self.position]
        self.position += 1
        for key in keys:
            self.reconcile_receipts(key)
            with self.store.db(key) as db:
                eps = [loads(r[0]) for r in db.execute("SELECT data FROM episodes ORDER BY seq")]
            for ep in eps:
                if ep["status"] in FINAL:
                    continue
                with self.store.lock:
                    ep = self._get(key, ep["id"])
                    info = self.store.info(key)
                    try:
                        if not self._parent_active(key, ep):
                            continue
                        self._usable(
                            ep["body"]["connection_id"], ep["body"]["connection_version"], "acquisition"
                        )
                        if (
                            info["archived"]
                            or ep.get("authority_generation") != self.settings()["generation"]
                            or not self._interested(key, ep)
                        ):
                            fault(
                                "stale_context", "Episode no longer has an active owner or request interest"
                            )
                    except RuntimeFault as error:
                        self._stop(key, ep, error.code)
                        return True
                    if ep["status"] not in ("awaiting_review", "ready") and self.now() >= ep["deadline"]:
                        self._stop(key, ep, "deadline")
                        return True
                    if ep["status"] == "acquiring":
                        with self.store.db() as db:
                            grant = db.execute(
                                "SELECT * FROM grants WHERE id=?", (ep["grant_id"],)
                            ).fetchone()
                        if grant["status"] in ("outcome_unknown", "not_dispatched"):
                            self._stop(key, ep, grant["status"])
                            return True
                        if grant["outcome"]:
                            body = loads(grant["body"])
                            if body["expires"] and body["expires"] > self.now():
                                self._receive(key, ep, body, loads(grant["outcome"]))
                                return True
                    if ep["status"] == "queued":
                        if ep["base_revision"] != info["revision_id"]:
                            ep.update(
                                base_revision=info["revision_id"], draft=None, feedback=[], fingerprint=None
                            )
                        ep["status"] = "preparing"
                        with self.store.db(key) as db:
                            self._save(db, ep)
                        action = ("prepare", ep, None)
                        break
                    if ep["status"] == "received":
                        with self.store.db(key) as db:
                            row = db.execute(
                                "SELECT * FROM learning_receipts WHERE episode=? AND status='received' ORDER BY seq LIMIT 1",
                                (ep["id"],),
                            ).fetchone()
                        if row:
                            action = ("decode", ep, dict(row, data=loads(row["data"])))
                            break
                # Reviews block admission, not the rest of exploration or local serving.
            else:
                action = None
            if action:
                try:
                    if action[0] == "prepare":
                        self._prepare(key, action[1])
                    else:
                        self._decode(key, action[1], action[2])
                except RuntimeFault as error:
                    with self.store.lock:
                        ep = self._get(key, action[1]["id"])
                        if ep["status"] not in FINAL:
                            self._stop(key, ep, error.code)
                return True
            with self.store.lock, self.store.db(key) as db:
                head = db.execute(
                    "SELECT * FROM learning_receipts WHERE status NOT IN ('accepted','rejected','invalid','partial','cancelled','inconclusive') ORDER BY seq LIMIT 1"
                ).fetchone()
                if (
                    head
                    and head["status"] in ("complete", "approved")
                    and loads(head["data"]).get("kind") != "source_projection"
                ):
                    ep = self._get(key, head["episode"])
                    receipt = dict(head, data=loads(head["data"]))
                else:
                    continue
            try:
                with self.store.lock:
                    if not self._parent_active(key, ep):
                        continue
                self._admit(key, ep, receipt)
            except RuntimeFault as error:
                with self.store.lock:
                    ep = self._get(key, ep["id"])
                    if ep["status"] not in FINAL:
                        self._stop(key, ep, error.code)
            return True
        return False

    def _prepare(self, key, ep):
        c = self.connection(ep["body"]["connection_id"], private=True)
        value = self._compute(key, ep, "learning_prepare", {"connection": c})
        with self.store.lock:
            ep = self._get(key, ep["id"])
            if ep["status"] != "preparing":
                return
            if not self._parent_active(key, ep):
                ep["status"] = "queued"
                with self.store.db(key) as db:
                    self._save(db, ep)
                return
            if self.store.info(key)["revision_id"] != ep["base_revision"]:
                ep.update(status="queued", draft=None, feedback=[])
                with self.store.db(key) as db:
                    self._save(db, ep)
                return
            if self.now() >= ep["deadline"]:
                self._stop(key, ep, "deadline")
                return
            self._usable(c["id"], c["version"], "acquisition")
            grant = self.reserve(
                {
                    "purpose": "acquisition",
                    "allowance_id": ep["body"].get("allowance_id"),
                    "connection_id": c["id"],
                    "connection_version": c["version"],
                    "configuration_digest": c["configuration_digest"],
                    "wire": value["wire"],
                    "input_estimate": value["input_estimate"],
                    "limits": ep["body"]["call_limits"],
                    "provenance": value["provenance"],
                    "recorded_index": len(ep["history"]),
                    "deadline": ep["deadline"],
                    "base_revision": ep["base_revision"],
                },
                adm=key,
                episode=ep["id"],
            )
            ep.update(status="acquiring", grant_id=grant, draft=value["draft"])
            with self.store.db(key) as db, self.store.transaction(db):
                self._save(db, ep)
                self.store.emit(
                    db, key, "episode.started", ep["id"], data={"grant_id": grant, "state": "awaiting_worker"}
                )

    def _decode(self, key, ep, receipt):
        data = receipt["data"]
        if data["outcome"]["status"] != "succeeded":
            with self.store.lock:
                self._stop(key, self._get(key, ep["id"]), data["outcome"].get("error") or "provider_failed")
            return
        grant = data["grant"]
        provenance = {
            **grant["provenance"],
            "connection_id": grant["connection_id"],
            "connection_version": grant["connection_version"],
            "configuration_digest": grant["configuration_digest"],
            "requested_model": self.connection(grant["connection_id"], grant["connection_version"])["model"],
            "returned_model": data["outcome"].get("returned_model"),
            "response_id": data["outcome"].get("response_id"),
            "grant_id": grant["id"],
            "usage": data["outcome"]["usage"],
        }
        value = self._compute(
            key,
            ep,
            "learning_decode",
            {"outcome": data["outcome"], "provenance": provenance, "candidate_id": receipt["id"]},
        )
        with self.store.lock:
            ep = self._get(key, ep["id"])
            if ep["status"] in FINAL or not self._parent_active(key, ep):
                return
            if self.now() >= ep["deadline"]:
                self._stop(key, ep, "deadline")
                return
            data.update({k: v for k, v in value.items() if k != "draft"})
            data["outcome"].pop("text", None)
            ep["history"].append(
                {
                    "grant_id": receipt["id"],
                    "receipt_sequence": receipt["seq"],
                    "status": value["status"],
                    "diagnostic": value.get("diagnostic"),
                    "provenance": provenance,
                }
            )
            if value.get("draft") is not None:
                if len(dumps(value["draft"])) > ep["body"]["limits"]["private_draft_bytes"]:
                    fault("resource_exhausted", "Private draft exceeds episode cap")
                ep["draft"] = value["draft"]
            if value["status"] == "complete":
                review = ep["body"]["publication"] == "review"
                state = "awaiting_review" if review else "complete"
                ep["status"] = "awaiting_review" if review else "ready"
            else:
                state = "partial" if value["status"] == "partial" else "invalid"
                self._feedback(ep, value.get("diagnostic") or {"error": value["status"]})
            with self.store.db(key) as db, self.store.transaction(db):
                db.execute(
                    "UPDATE learning_receipts SET status=?,data=? WHERE id=?",
                    (state, dumps(data), receipt["id"]),
                )
                self._save(db, ep)
                if state == "awaiting_review":
                    self.store.emit(
                        db, key, "candidate.awaiting_review", receipt["id"], data={"episode_id": ep["id"]}
                    )
            if value["status"] == "needs_evidence":
                self._stop(key, ep, "needs_evidence")
            elif ep["no_progress"] >= ep["body"]["limits"]["no_progress_attempts"]:
                self._stop(key, ep, "no_progress")

    def _feedback(self, ep, diagnostic):
        from ..engine.diagnostics import bounded

        # Only local bounded diagnostics go into the next unchanged acquisition contract.
        feedback = bounded(diagnostic)
        content = diagnostic.get("content_digest") or fingerprint(
            {"draft": ep["draft"], "error": diagnostic.get("error")}
        )
        ep["no_progress"] = ep["no_progress"] + 1 if ep["fingerprint"] == content else 0
        ep.update(fingerprint=content, feedback=[feedback], status="queued", grant_id=None)

    def _admit(self, key, ep, receipt):
        with self.store.lock:
            if not self._parent_active(key, ep):
                return
            current = self.store.revision(key)
            data = receipt["data"]
            if ep["body"]["publication"] == "review" and data["approval_revision"] != current["revision_id"]:
                with self.store.db(key) as db, self.store.transaction(db):
                    db.execute(
                        "UPDATE learning_receipts SET status='awaiting_review' WHERE id=?", (receipt["id"],)
                    )
                    ep["status"] = "awaiting_review"
                    self._save(db, ep)
                return
            settings_generation = self.settings()["generation"]
        value = self._compute(
            key,
            ep,
            "learning_admit",
            {
                "current_snapshot": current["snapshot"],
                "context": current["context"],
                "package": data["package"],
                "receipt_sequence": receipt["seq"],
            },
        )
        with self.store.lock:
            ep = self._get(key, ep["id"])
            if ep["status"] in FINAL or not self._parent_active(key, ep):
                return
            if self.store.info(key)["revision_id"] != current["revision_id"]:
                return  # Work was charged; recheck current context, never publish stale output.
            self._usable(ep["body"]["connection_id"], ep["body"]["connection_version"], "acquisition")
            if settings_generation != self.settings()["generation"] or not self._interested(key, ep):
                self._stop(key, ep, "authority_changed")
                return
            status = value["status"]
            data["decision"] = value["decision"]
            with self.store.db(key) as db, self.store.transaction(db):
                db.execute(
                    "UPDATE learning_receipts SET status=?,data=? WHERE id=?",
                    (status, dumps(data), receipt["id"]),
                )
                if status == "accepted":
                    if (
                        db.execute("SELECT count(*) FROM revisions").fetchone()[0]
                        >= self.config.runtime.queue_items_per_adm
                    ):
                        fault("quota_exceeded", "Retained revision allowance exhausted")
                    context = {**value["context"], "persistence": "sqlite", "background_learning": True}
                    if "source_policy_generation" in current["context"]:
                        context["source_policy_generation"] = current["context"]["source_policy_generation"]
                    payload, revision = dumps(value["snapshot"]), uid()
                    self.store.capacity(len(payload) + 4096)
                    db.execute(
                        "INSERT INTO revisions(id,context,payload,digest) VALUES(?,?,?,?)",
                        (revision, dumps(context), payload, hashlib.sha256(payload).hexdigest()),
                    )
                    db.execute(
                        "INSERT OR IGNORE INTO versions VALUES(?,?,?)",
                        (context["theory_version"], payload, hashlib.sha256(payload).hexdigest()),
                    )
                    db.execute(
                        "UPDATE state SET context=?,active=? WHERE id=1",
                        (dumps(context), context["theory_version"]),
                    )
                    db.execute("UPDATE control SET revision=? WHERE id=1", (revision,))
                    ep.update(status="accepted", reason=None)
                    if ep.get("parent_task"):
                        self.runtime.conversations.teaching.execution.published(
                            db, key, ep, revision, context
                        )
                    # Explicit learning interests authorize a NEW local attempt under
                    # the new theory. Existing attempts/revisions remain immutable.
                    for row in db.execute(
                        "SELECT DISTINCT r.* FROM requests r JOIN interests i ON i.request=r.id WHERE r.status='waiting_for_learning'"
                    ).fetchall():
                        if loads(row["context"])["policy_epoch"] != context["policy_epoch"]:
                            continue
                        db.execute(
                            "UPDATE requests SET revision=?,context=?,status='received',attempt=NULL,result=NULL,result_id=NULL,error=NULL,updated=? WHERE id=?",
                            (revision, dumps(context), self.now(), row["id"]),
                        )
                        self.store.emit(
                            db,
                            key,
                            "request.received",
                            row["id"],
                            context=context,
                            data={"after_learning": receipt["id"]},
                        )
                else:
                    error = value["decision"].get("report", {}).get("error", {})
                    backward = (
                        value["decision"].get("mode") == "backward"
                        and error.get("context", {}).get("mode") == "backward"
                    )
                    if status == "inconclusive" or backward:
                        ep.update(
                            status="rejected", reason="backward_precedence" if backward else "inconclusive"
                        )
                    else:
                        self._feedback(
                            ep,
                            {
                                "error": value["decision"],
                                "content_digest": ep["history"][-1]["diagnostic"].get("content_digest"),
                            },
                        )
                self._save(db, ep)
                self.store.emit(
                    db,
                    key,
                    "candidate.accepted" if status == "accepted" else "candidate.rejected",
                    receipt["id"],
                    data={"episode_id": ep["id"], "decision": value["decision"]},
                )
            if ep["status"] == "rejected":
                self._stop(key, ep, ep["reason"], "rejected")
            elif ep["no_progress"] >= ep["body"]["limits"]["no_progress_attempts"]:
                self._stop(key, ep, "no_progress")
            self.runtime.coordinator.wake.set()
