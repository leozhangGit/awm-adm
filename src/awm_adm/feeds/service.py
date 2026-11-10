"""One-item micro-batches, durable cursors and conservative lifetime reservations.

The source scheduler owns execution. This controller only creates bounded intents;
all extraction, projection and admission remain in the existing checked path.
"""

from uuid import uuid4

from ..learning.service import fault, fingerprint
from ..runtime.protocol import RuntimeFault, dumps, loads
from .models import FeedControl, FeedInput, Reprocess

FINAL = {"accepted", "rejected", "dead_letter", "held"}
FIELDS = ("items", "calls", "input_tokens", "output_tokens", "work")


class FeedService:
    def __init__(self, sources):
        self.sources, self.runtime, self.store = sources, sources.runtime, sources.store
        self.position = 0
        self.recover()

    def now(self):
        return self.sources.learning.now()

    def get(self, key, identity):
        with self.store.db(key) as db:
            row = db.execute("SELECT data FROM feeds WHERE id=?", (identity,)).fetchone()
        if not row:
            fault("not_found", "Feed not found")
        return loads(row[0])

    def save(self, db, feed):
        db.execute("UPDATE feeds SET data=? WHERE id=?", (dumps(feed), feed["id"]))

    def run(self, key, identity):
        with self.store.db(key) as db:
            row = db.execute("SELECT data FROM feed_runs WHERE id=?", (identity,)).fetchone()
        if not row:
            fault("not_found", "Feed run not found")
        return loads(row[0])

    def save_run(self, db, run):
        db.execute("UPDATE feed_runs SET status=?,data=? WHERE id=?", (run["status"], dumps(run), run["id"]))

    def valid(self, key, feed):
        info = self.store.info(key)
        return (
            (
                not feed.get("parent_task")
                or (
                    getattr(self.runtime, "conversations", None) is not None
                    and self.runtime.conversations.intake.feed_valid(key, feed)
                )
            )
            and feed["enabled"]
            and not info["archived"]
            and feed["body"]["expected_source_generation"] == self.sources.policy(key)["generation"]
            and feed["policy_epoch"] == info["policy_epoch"]
        )

    def interests(self, key, run):
        if self.run(key, run)["status"] in FINAL:
            return []
        with self.store.db(key) as db:
            rows = db.execute(
                "SELECT DISTINCT f.data FROM feeds f JOIN feed_items i ON i.feed=f.id WHERE i.run=?", (run,)
            ).fetchall()
        return [loads(r[0]) for r in rows if self.valid(key, loads(r[0]))]

    def require_interest(self, key, item):
        if item.get("feed_run") and not self.interests(key, item["feed_run"]):
            fault("stale_context", "No enabled current feed interest remains")

    def charge_work(self, key, item):
        if not item.get("feed_run"):
            return
        with self.store.db(key) as db, self.store.transaction(db):
            self.require_interest(key, item)
            run = self.run(key, item["feed_run"])
            amount = self.sources.managed_limits(parent=run.get("parent_task"))["max_work"]
            if run["work"] + amount > run["reservation"]["work"]:
                fault("resource_exhausted", "Feed item local work reservation exhausted")
            run["work"] += amount
            self.save_run(db, run)

    def create(self, key, body, *, parent_task=None, allowance_id=None):
        body = FeedInput.model_validate(body).model_dump()
        with self.store.lock:
            with self.store.db(key) as db:
                old = db.execute(
                    "SELECT id,digest FROM feeds WHERE idem=?", (body["idempotency_key"],)
                ).fetchone()
            if old:
                if old["digest"] != fingerprint(body):
                    fault("conflict", "Feed idempotency mismatch")
                return self.get(key, old["id"])
            info = self.sources.current(key, body["expected_revision"], body["expected_source_generation"])
            policy = self.sources.policy(key)
            if not policy.get("projection"):
                fault("needs_specification", "Install finite projection coverage before enabling a feed")
            for sid in body["source_ids"]:
                permission = self.sources.permission(key, sid)
                if not permission or (body["allow_external"] and not permission["allow_external"]):
                    fault("forbidden", "Feed source or disclosure is not permitted")
            for name, limit in body["call_limits"].items():
                if limit > getattr(self.runtime.config.learning.call, name):
                    fault("invalid_limits", "Feed call exceeds configured cap")
            if body["extractor"] == "external":
                self.sources.learning._usable(body["connection_id"], body["connection_version"], "extraction")
        if body["publication"] == "checked_auto":
            requirements = {p["symbol"]: p for p in body["requirements"]}
            if len(requirements) != len(body["requirements"]) or set(requirements) != {
                p["symbol"] for p in policy["projection"]["predicates"]
            }:
                fault(
                    "needs_specification",
                    "Checked automatic publication requires owner fact requirements for every predicate",
                )
            for predicate in policy["projection"]["predicates"]:
                req = requirements[predicate["symbol"]]
                if req["kind"] != predicate["kind"] or req["unit"] != predicate["unit"]:
                    fault("needs_specification", "Owner requirement kind/unit must match the projection")
        with self.store.db(key) as db, self.store.transaction(db):
            old = db.execute(
                "SELECT id,digest FROM feeds WHERE idem=?", (body["idempotency_key"],)
            ).fetchone()
            if old:
                if old["digest"] != fingerprint(body):
                    fault("conflict", "Feed idempotency mismatch")
                return self.get(key, old["id"])
            self.sources.current(key, body["expected_revision"], body["expected_source_generation"])
            if (
                body["after_sequence"]
                > db.execute("SELECT COALESCE(max(seq),0) FROM source_versions").fetchone()[0]
            ):
                fault("invalid_input", "Feed cursor exceeds received source history")
            if db.execute("SELECT count(*) FROM feeds").fetchone()[0] >= 100:
                fault("quota_exceeded", "Retained feed policy limit reached")
            self.sources.room(db, len(dumps(body)) + 4096)
            feed = {
                **({"parent_task": parent_task, "allowance_id": allowance_id} if parent_task else {}),
                "id": str(uuid4()),
                "body": body,
                "generation": 1,
                "enabled": body["enabled"],
                "cursor": body["after_sequence"],
                "policy_epoch": info["policy_epoch"],
                "reserved": dict.fromkeys(FIELDS, 0),
                "failures": 0,
                "stall_reason": None,
            }
            db.execute(
                "INSERT INTO feeds(id,idem,digest,data) VALUES(?,?,?,?)",
                (feed["id"], body["idempotency_key"], fingerprint(body), dumps(feed)),
            )
        self.sources.wake.set()
        return feed

    def control(self, key, identity, body):
        body = FeedControl.model_validate(body).model_dump()
        with self.store.db(key) as db, self.store.transaction(db):
            feed = self.get(key, identity)
            if feed.get("parent_task"):
                fault("forbidden", "Control this feed through its teaching task")
            self.sources.current(
                key,
                body["expected_revision"],
                feed["body"]["expected_source_generation"] if body["enabled"] else None,
            )
            if feed["generation"] != body["expected_generation"]:
                fault("stale_context", "Feed generation changed")
            feed.update(
                enabled=body["enabled"],
                generation=feed["generation"] + 1,
                policy_epoch=self.store.info(key)["policy_epoch"],
                failures=0,
                stall_reason=None,
            )
            self.save(db, feed)
        self.sources.wake.set()
        return feed

    def attach(self, db, key, feed, source, pass_id="initial"):
        body = feed["body"]
        reservation = {
            "items": 1,
            "calls": int(body["extractor"] == "external"),
            "input_tokens": body["call_limits"]["max_input_tokens"] if body["extractor"] == "external" else 0,
            "output_tokens": body["call_limits"]["max_output_tokens"]
            if body["extractor"] == "external"
            else 0,
            "work": 3 * self.sources.managed_limits(parent=feed.get("parent_task"))["max_work"],
        }
        if any(feed["reserved"][f] + reservation[f] > body["budget"]["max_" + f] for f in FIELDS):
            fault(
                "quota_exceeded",
                "Feed lifetime allowance exhausted; create a new explicit policy to authorize more",
            )
        pipeline = fingerprint(
            {
                "source": source["id"],
                "source_generation": body["expected_source_generation"],
                "extractor": body["extractor"],
                "connection": body["connection_id"],
                "connection_version": body["connection_version"],
                "limits": body["call_limits"],
                "pass": pass_id,
            }
        )
        if feed.get("parent_task"):
            pipeline = fingerprint(
                {"pipeline": pipeline, "parent": feed["parent_task"], "allowance": feed["allowance_id"]}
            )
        old = db.execute("SELECT id FROM feed_runs WHERE pipeline=?", (pipeline,)).fetchone()
        rid = old[0] if old else str(uuid4())
        if feed.get("allowance_id"):
            self.sources.learning.allowances.child(
                feed["allowance_id"],
                {
                    "operation_id": "source-item:" + pipeline,
                    "kind": "extraction",
                    "max_work": reservation["work"],
                    "payload_digest": pipeline,
                },
            )
        self.sources.room(db, 8192, additional_items=2)
        if not old:
            run = {
                **(
                    {"parent_task": feed["parent_task"], "allowance_id": feed["allowance_id"]}
                    if feed.get("parent_task")
                    else {}
                ),
                "id": rid,
                "source_seq": source["seq"],
                "source": source["id"],
                "status": "queued",
                "body": body,
                "pass_id": pass_id,
                "job": None,
                "episode": None,
                "work": 0,
                "reservation": reservation,
                "attempts": 0,
                "next_attempt": 0,
                "reason": None,
                "created": self.now(),
                "seen": False,
            }
            db.execute("INSERT INTO feed_runs VALUES(?,?,?,?)", (rid, pipeline, "queued", dumps(run)))
        db.execute(
            "INSERT INTO feed_items(feed,source_seq,pass_id,run,data) VALUES(?,?,?,?,?)",
            (
                feed["id"],
                source["seq"],
                pass_id,
                rid,
                dumps({"reservation": reservation, "created": self.now()}),
            ),
        )
        for field in FIELDS:
            feed["reserved"][field] += reservation[field]
        self.save(db, feed)
        return rid

    def reprocess(self, key, identity, body):
        body = Reprocess.model_validate(body).model_dump()
        with self.store.db(key) as db, self.store.transaction(db):
            old = db.execute(
                "SELECT digest,data FROM feed_controls WHERE idem=?", (body["idempotency_key"],)
            ).fetchone()
            digest = fingerprint({"feed": identity, **body})
            if old:
                if old[0] != digest:
                    fault("conflict", "Reprocessing idempotency mismatch")
                return loads(old[1])
            feed = self.get(key, identity)
            if feed.get("parent_task"):
                fault("forbidden", "Reprocessing needs a fresh conversational task and allowance")
            if feed["generation"] != body["expected_generation"] or not self.valid(key, feed):
                fault("stale_context", "Reprocessing requires an enabled current feed")
            source = db.execute(
                "SELECT * FROM source_versions WHERE seq=?", (body["source_sequence"],)
            ).fetchone()
            if not source or source["source"] not in feed["body"]["source_ids"]:
                fault("not_found", "Source is outside this feed")
            self.pending_room(db, feed)
            rid = self.attach(db, key, feed, source, "reprocess:" + body["idempotency_key"])
            result = {
                "run_id": rid,
                "source_sequence": source["seq"],
                "reprocess_id": body["idempotency_key"],
            }
            db.execute(
                "INSERT INTO feed_controls VALUES(?,?,?)", (body["idempotency_key"], digest, dumps(result))
            )
        return result

    def pending_room(self, db, feed):
        count = db.execute(
            "SELECT count(*) FROM feed_items i JOIN feed_runs r ON r.id=i.run WHERE i.feed=? AND r.status NOT IN ('accepted','rejected','held','dead_letter')",
            (feed["id"],),
        ).fetchone()[0]
        if count >= feed["body"]["max_pending"]:
            fault("busy", "Feed pending allowance is full")

    def schedule(self, key, feed):
        if feed.get("intake_exhausted"):
            return False
        if feed.get("parent_task"):
            self.runtime.conversations.intake.parent_valid(key, feed["parent_task"])
        if feed.get("intake_one_shot"):
            return False
        if feed.get("parent_task"):
            task = self.runtime.conversations.teaching.get(key, feed["parent_task"])
            cutoff = task["execution"].get("closing_source_sequence")
        else:
            cutoff = None
        with self.store.db(key) as db, self.store.transaction(db):
            self.pending_room(db, feed)
            # A bounded scan advances past unrelated sources without retaining fake work.
            rows = db.execute(
                "SELECT * FROM source_versions WHERE seq>? AND (? IS NULL OR seq<=?) ORDER BY seq LIMIT 32",
                (feed["cursor"], cutoff, cutoff),
            ).fetchall()
            for row in rows:
                if row["source"] in feed["body"]["source_ids"]:
                    if db.execute(
                        "SELECT 1 FROM feed_items WHERE feed=? AND source_seq=? AND pass_id='initial'",
                        (feed["id"], row["seq"]),
                    ).fetchone():
                        feed["cursor"] = row["seq"]
                        continue
                    self.attach(db, key, feed, row)
                    feed["cursor"] = row["seq"]
                    feed["stall_reason"] = None
                    self.save(db, feed)
                    return True
                feed["cursor"] = row["seq"]
            feed["stall_reason"] = None
            self.save(db, feed)
            return bool(rows)

    def finish(self, key, run, status, reason=None):
        with self.store.db(key) as db, self.store.transaction(db):
            run.update(status=status, reason=reason)
            self.save_run(db, run)
            if status in ("held", "dead_letter"):
                for table in ("source_jobs", "source_episodes"):
                    for row in db.execute(
                        f"SELECT data FROM {table} WHERE status IN ('queued','checking','awaiting_provider','preparing','awaiting_review','approved','validating')"
                    ).fetchall():
                        item = loads(row[0])
                        if item.get("feed_run") == run["id"]:
                            item.update(status="cancelled", error=reason)
                            self.sources.save(db, table, item)
                            db.execute(
                                "UPDATE learning_receipts SET status='cancelled' WHERE id=?", (item["id"],)
                            )
            for row in db.execute(
                "SELECT DISTINCT feed FROM feed_items WHERE run=?", (run["id"],)
            ).fetchall():
                feed = self.get(key, row[0])
                feed["failures"] = 0 if status == "accepted" else feed["failures"] + 1
                if feed["failures"] >= feed["body"]["max_failures"]:
                    feed["enabled"] = False
                    feed["generation"] += 1
                    feed["stall_reason"] = "no_progress_limit"
                self.save(db, feed)

    def advance(self, key, run):
        if run["status"] in FINAL or not self.interests(key, run["id"]) or self.now() < run["next_attempt"]:
            return False
        body = run["body"]
        if run.get("parent_task"):
            execution = self.runtime.conversations.teaching.get(key, run["parent_task"])["execution"]
            if self.runtime.conversations.now() >= execution["deadline_ms"] and run.get("episode") != (
                execution.get("source_review") or {}
            ).get("receipt_id"):
                return False
        try:
            if run["job"] is None:
                with self.store.db(key) as db:
                    source = db.execute(
                        "SELECT * FROM source_versions WHERE id=?", (run["source"],)
                    ).fetchone()
                item = self.sources.create_job(
                    key,
                    {
                        **({"allowance_id": run["allowance_id"]} if run.get("allowance_id") else {}),
                        "idempotency_key": run["id"],
                        "expected_revision": self.store.info(key)["revision_id"],
                        "expected_generation": body["expected_source_generation"],
                        "source_id": source["source"],
                        "item_id": source["item"],
                        "version_id": source["version"],
                        "extractor": body["extractor"],
                        "connection_id": body["connection_id"],
                        "connection_version": body["connection_version"],
                        "call_limits": body["call_limits"],
                        "reprocess_id": run["pass_id"] if run["pass_id"] != "initial" else None,
                    },
                    feed_run=run["id"],
                )
                run.update(job=item["id"], status="extracting")
                with self.store.db(key) as db:
                    self.save_run(db, run)
                return True
            job = self.sources.get(key, "source_jobs", run["job"])
            if job["status"] in ("failed", "stopped", "cancelled"):
                self.finish(key, run, "dead_letter", job.get("error") or job["status"])
                return True
            if job["status"] in ("needs_specification", "proposed_schema"):
                self.finish(key, run, "held", "needs_specification")
                return True
            if job["status"] != "extracted":
                return False
            if run["episode"] is None:
                claims = [
                    r["claim"]["claim_id"]
                    for r in job["result"]["claims"]
                    if r["claim"]["status"] == "candidate"
                ]
                # All-or-hold: a partially resolved extraction never silently drops records.
                if not claims or len(claims) != len(job["result"]["claims"]):
                    self.finish(key, run, "held", "needs_evidence_or_coverage")
                    return True
                ep = self.sources.create_projection(
                    key,
                    {
                        "idempotency_key": run["id"],
                        "expected_revision": self.store.info(key)["revision_id"],
                        "expected_generation": body["expected_source_generation"],
                        "claim_ids": claims,
                    },
                    feed_run=run["id"],
                )
                run.update(episode=ep["id"], status="projecting")
                with self.store.db(key) as db:
                    self.save_run(db, run)
                return True
            ep = self.sources.get(key, "source_episodes", run["episode"])
            if ep["status"] in ("accepted", "rejected"):
                self.finish(key, run, ep["status"])
                return True
            if ep["status"] in ("failed", "stopped", "cancelled"):
                self.finish(key, run, "dead_letter", ep.get("error") or ep["status"])
                return True
            if ep["status"] == "awaiting_review":
                active = self.interests(key, run["id"])
                for feed in active:
                    if feed["body"]["publication"] == "checked_auto" and self.meets(feed, ep):
                        self.sources.review(
                            key,
                            ep["id"],
                            {"expected_revision": self.store.info(key)["revision_id"], "approve": True},
                            automatic_feed=feed,
                        )
                        return True
            return False
        except RuntimeFault as error:
            # Only undispatched orchestration may retry. Source jobs themselves are one-shot.
            if error.code in ("busy", "quota_exceeded") and run["attempts"] < body["retry_limit"]:
                run["attempts"] += 1
                run["reason"] = error.code
                run["next_attempt"] = self.now() + body["backoff_seconds"] * 2 ** (run["attempts"] - 1)
                with self.store.db(key) as db:
                    self.save_run(db, run)
            else:
                self.finish(key, run, "held", error.code)
            return True

    @staticmethod
    def meets(feed, episode):
        requirements = {p["symbol"]: p for p in feed["body"]["requirements"]}
        for row in episode["claims"]:
            fact = row["claim"]
            req = requirements.get(fact["predicate"])
            if not req or fact["unit"] != req["unit"] or fact["value"]["kind"] != req["kind"]:
                return False
            value = fact["value"]["value"]
            if req["kind"] == "integer" and not req["minimum"] <= value <= req["maximum"]:
                return False
            if req["kind"] == "enum" and value not in req["values"]:
                return False
        return True

    def approval_valid(self, key, item):
        approval = item.get("automatic_feed")
        if not approval:
            return True
        feed = self.get(key, approval["id"])
        return (
            self.valid(key, feed) and feed["generation"] == approval["generation"] and self.meets(feed, item)
        )

    def recover(self):
        for row in self.store.list():
            if row["status"] != "ready":
                continue
            key = row["id"]
            with self.store.db(key) as db, self.store.transaction(db):
                for table in ("source_jobs", "source_episodes"):
                    for record in db.execute(f"SELECT data FROM {table}").fetchall():
                        item = loads(record[0])
                        if not item.get("feed_run") or item["status"] not in (
                            "queued",
                            "checking",
                            "preparing",
                            "validating",
                            "awaiting_provider",
                            "awaiting_review",
                            "approved",
                        ):
                            # Completed/held outcomes retain their original audit metadata.
                            continue
                        with self.store.db() as registry:
                            grants = registry.execute(
                                "SELECT body FROM grants WHERE adm=?", (key,)
                            ).fetchall()
                        orphan = any(loads(g[0]).get("source_job_id") == item["id"] for g in grants)
                        if orphan and item["status"] == "queued":
                            item.update(
                                status="stopped", error="reserved_call_requires_explicit_reprocessing"
                            )
                        if item["status"] in (
                            "checking",
                            "preparing",
                            "validating",
                            "awaiting_provider",
                        ) or item.get("grant_id"):
                            if item["status"] not in (
                                "extracted",
                                "accepted",
                                "rejected",
                                "awaiting_review",
                                "failed",
                                "cancelled",
                                "stopped",
                            ):
                                item.update(status="stopped", error="restart_requires_explicit_reprocessing")
                                db.execute(
                                    "UPDATE learning_receipts SET status='cancelled' WHERE id=?",
                                    (item["id"],),
                                )
                        elif item["status"] == "approved":
                            item["status"] = "awaiting_review"
                            db.execute(
                                "UPDATE learning_receipts SET status='awaiting_review' WHERE id=?",
                                (item["id"],),
                            )
                        if item["status"] in ("queued", "awaiting_review"):
                            item["generation"] = self.store.generation
                            item["deadline"] = self.now() + 120
                        self.sources.save(db, table, item)

    def tick(self):
        pairs = []
        for row in self.store.list():
            if row["status"] == "ready":
                with self.store.db(row["id"]) as db:
                    pairs.extend(
                        (row["id"], loads(r[0])) for r in db.execute("SELECT data FROM feeds ORDER BY seq")
                    )
        if not pairs:
            return False
        self.position %= len(pairs)
        pairs = pairs[self.position :] + pairs[: self.position]
        self.position += 1
        for key, feed in pairs:
            if not self.valid(key, feed):
                continue
            with self.store.db(key) as db:
                runs = db.execute(
                    "SELECT DISTINCT r.data FROM feed_runs r JOIN feed_items i ON i.run=r.id WHERE i.feed=? AND r.status NOT IN ('accepted','rejected','held','dead_letter') ORDER BY i.seq LIMIT 32",
                    (feed["id"],),
                ).fetchall()
            for row in runs:
                if self.advance(key, loads(row[0])):
                    return True
            try:
                if self.schedule(key, self.get(key, feed["id"])):
                    return True
            except RuntimeFault as error:
                with self.store.db(key) as db:
                    fresh = self.get(key, feed["id"])
                    fresh["stall_reason"] = "pending_limit" if error.code == "busy" else error.code
                    if fresh.get("parent_task") and error.code in {
                        "quota_exceeded",
                        "resource_exhausted",
                        "invalid_limits",
                    }:
                        fresh["intake_exhausted"] = error.code
                    self.save(db, fresh)
        return False

    def overview(self, key, after=0, limit=50):
        if not 1 <= limit <= 100 or after < 0:
            fault("invalid_input", "Invalid feed page")
        with self.store.db(key) as db:
            feeds = []
            for row in db.execute("SELECT data FROM feeds ORDER BY seq LIMIT 100"):
                feed = loads(row[0])
                body = feed["body"]
                counts = dict(
                    db.execute(
                        "SELECT r.status,count(*) FROM feed_items i JOIN feed_runs r ON r.id=i.run WHERE i.feed=? GROUP BY r.status",
                        (feed["id"],),
                    ).fetchall()
                )
                backlog = db.execute(
                    "SELECT count(*) FROM source_versions WHERE seq>? AND source IN ("
                    + ",".join("?" for _ in body["source_ids"])
                    + ")",
                    (feed["cursor"], *body["source_ids"]),
                ).fetchone()[0]
                run_rows = db.execute(
                    "SELECT r.data FROM feed_items i JOIN feed_runs r ON r.id=i.run WHERE i.feed=?",
                    (feed["id"],),
                ).fetchall()
                extracted = 0
                unresolved = 0
                for record in run_rows:
                    run = loads(record[0])
                    if run["job"]:
                        job = self.sources.get(key, "source_jobs", run["job"])
                        extracted += int(job["status"] == "extracted")
                        if job.get("grant_id"):
                            unresolved += int(self.sources.learning.grant_view(job["grant_id"])["unresolved"])
                feed.update(
                    received=db.execute(
                        "SELECT count(*) FROM source_versions WHERE seq>? AND source IN ("
                        + ",".join("?" for _ in body["source_ids"])
                        + ")",
                        (body["after_sequence"], *body["source_ids"]),
                    ).fetchone()[0],
                    extracted=extracted,
                    admitted=counts.get("accepted", 0),
                    unknown_calls=unresolved,
                    counts=counts,
                    backlog=backlog,
                    remaining={f: body["budget"]["max_" + f] - feed["reserved"][f] for f in FIELDS},
                )
                if not feed["enabled"]:
                    feed["stall_reason"] = (
                        "no_progress_limit" if feed["failures"] >= body["max_failures"] else "paused"
                    )
                elif (
                    feed.get("parent_task")
                    and self.runtime.conversations.teaching.get(key, feed["parent_task"])["status"]
                    == "paused"
                ):
                    feed["stall_reason"] = "parent_paused"
                elif not self.valid(key, feed):
                    feed["stall_reason"] = "policy_changed_requires_owner_review"
                elif sum(n for status, n in counts.items() if status not in FINAL) >= body["max_pending"]:
                    feed["stall_reason"] = "pending_limit"
                elif counts.get("projecting", 0) and any(
                    self.sources.get(key, "source_episodes", loads(r[0])["episode"])["status"]
                    == "awaiting_review"
                    for r in run_rows
                    if loads(r[0]).get("episode")
                ):
                    feed["stall_reason"] = "awaiting_review"
                elif backlog and (
                    feed["remaining"]["items"] < 1
                    or feed["remaining"]["work"]
                    < 3 * self.sources.managed_limits(parent=feed.get("parent_task"))["max_work"]
                    or (body["extractor"] == "external" and feed["remaining"]["calls"] < 1)
                ):
                    feed["stall_reason"] = "lifetime_allowance_exhausted"
                else:
                    feed["stall_reason"] = None
                feeds.append(feed)
            rows = db.execute(
                "SELECT i.seq,i.feed,i.source_seq,i.pass_id,r.data FROM feed_items i JOIN feed_runs r ON r.id=i.run WHERE i.seq>? ORDER BY i.seq LIMIT ?",
                (after, limit),
            ).fetchall()
            items = []
            for row in rows:
                run = loads(row["data"])
                item = {k: row[k] for k in ("seq", "feed", "source_seq", "pass_id")}
                item.update(
                    {
                        k: run[k]
                        for k in (
                            "id",
                            "status",
                            "job",
                            "episode",
                            "reason",
                            "attempts",
                            "next_attempt",
                            "work",
                        )
                    }
                )
                if run["episode"]:
                    ep = self.sources.get(key, "source_episodes", run["episode"])
                    item.update(episode_status=ep["status"], receipt_sequence=ep.get("receipt_sequence"))
                    if ep["status"] == "awaiting_review":
                        item["reason"] = "owner_review_or_fact_requirements"
                    elif ep["status"] == "approved":
                        item["reason"] = "waiting_for_receipt_order"
                items.append(item)
        return {
            "feeds": feeds,
            "items": items,
            "next_cursor": rows[-1]["seq"] if rows else after,
            "provider_usage": self.sources.learning.usage(adm=key),
            "lifetime_reservations": True,
        }
