"""Immutable uploads and bounded append authority over the existing source/feed engine."""

import hashlib
from uuid import uuid4

from ..feeds.service import FINAL as FEED_FINAL
from ..learning.service import fault, fingerprint
from ..runtime.protocol import RuntimeFault, dumps, loads
from .models import AppendInput, Upload


class Intake:
    def __init__(self, conversations):
        self.s, self.rt, self.store = conversations, conversations.runtime, conversations.store
        self.t = conversations.teaching

    @property
    def sources(self):
        return self.rt.sources

    @property
    def execution(self):
        return self.t.execution

    def material(self, key, uid):
        with self.store.db(key) as db:
            row = db.execute("SELECT body FROM intake_material WHERE id=?", (uid,)).fetchone()
        if not row:
            fault("not_found", "Uploaded material is not in this model")
        return loads(row[0])

    def upload(self, key, body):
        body = Upload.model_validate(body).model_dump()
        raw = body["content"].encode()
        digest = fingerprint(body)
        version = "v_" + hashlib.sha256(raw).hexdigest()
        item = body["item_id"] or "file_" + hashlib.sha256(body["name"].encode()).hexdigest()[:24]
        with self.store.db(key) as db, self.store.transaction(db):
            self.s._current(key, self.s.context(key))
            old = db.execute(
                "SELECT k.digest,a.body FROM intake_upload_keys k JOIN chat_attachments a ON a.id=k.attachment WHERE k.idem=?",
                (body["idempotency_key"],),
            ).fetchone()
            if old:
                if old["digest"] != digest:
                    fault("conflict", "Upload identity has different content")
                return loads(old["body"])
            if db.execute("SELECT count(*) FROM intake_upload_keys").fetchone()[0] >= 1000:
                fault("quota_exceeded", "Retained upload identity limit reached")
            if db.execute("SELECT count(*) FROM intake_material").fetchone()[0] >= 100:
                fault("quota_exceeded", "Retained attachment limit reached")
            size = db.execute("SELECT COALESCE(sum(length(body)),0) FROM intake_material").fetchone()[0]
            if size + len(dumps(body)) > 8388608:
                fault("quota_exceeded", "Retained attachment byte limit reached")
            duplicate = db.execute(
                "SELECT id FROM intake_material WHERE source=? AND item=? AND version=?",
                (body["source_id"], item, version),
            ).fetchone()
            if duplicate:
                saved = self.material(key, duplicate[0])
                if any(saved["metadata"][k] != body[k] for k in ("supersedes_version", "name", "media_type")):
                    fault("conflict", "Identical bytes cannot change supersession meaning")
                db.execute(
                    "INSERT INTO intake_upload_keys VALUES(?,?,?)",
                    (body["idempotency_key"], digest, duplicate[0]),
                )
                return saved["metadata"]
            uid = str(uuid4())
            metadata = {
                "id": uid,
                "name": body["name"],
                "media_type": body["media_type"],
                "byte_count": len(raw),
                "content_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "source_id": body["source_id"],
                "item_id": item,
                "version_id": version,
                "supersedes_version": body["supersedes_version"],
                "content_available": True,
            }
            source = {k: body[k] for k in ("source_id", "media_type", "content", "supersedes_version")}
            source.update(item_id=item, version_id=version, origin="attachment:" + body["name"])
            self.store.capacity(len(dumps(source)) + 8192)
            db.execute(
                "INSERT INTO chat_attachments VALUES(?,?,?,?)",
                (uid, body["idempotency_key"], digest, dumps(metadata)),
            )
            db.execute(
                "INSERT INTO intake_material VALUES(?,?,?,?,?)",
                (uid, body["source_id"], item, version, dumps({"metadata": metadata, "source": source})),
            )
            db.execute("INSERT INTO intake_upload_keys VALUES(?,?,?)", (body["idempotency_key"], digest, uid))
            return metadata

    def inputs(self, db, key, turn):
        ids = turn["attachment_ids"]
        if len(set(ids)) != len(ids):
            fault("invalid_input", "Attachment references must be unique")
        return [self.material(key, uid)["metadata"] for uid in ids]

    def disclosed(self, key, task):
        materials = []
        for entry in task["inputs"]:
            for meta in entry.get("attachments", []):
                material = self.material(key, meta["id"])
                if material["metadata"] != meta:
                    fault("stale_context", "Uploaded material binding changed")
                materials.append(
                    {
                        "input_id": entry["id"],
                        **material["source"],
                        "byte_count": meta["byte_count"],
                        "content_digest": meta["content_digest"],
                    }
                )
        return materials

    def attachments(self, key):
        with self.store.db(key) as db:
            result = []
            for row in db.execute("SELECT body FROM intake_material LIMIT 100"):
                meta = loads(row[0])["metadata"]
                head = db.execute(
                    "SELECT version FROM source_heads WHERE source=? AND item=?",
                    (meta["source_id"], meta["item_id"]),
                ).fetchone()
                result.append({**meta, "current_source_version": head[0] if head else None})
            return {"items": result}

    @staticmethod
    def scope_review(task):
        rows = []
        for child in task["specification"]["children"]:
            if not child["material"]:
                continue
            material = child["material"]
            projection = material["projection"]
            rows.append(
                {
                    "sources": [s["source_id"] for s in material["sources"]],
                    "entities": projection["entities"],
                    "predicates": [
                        f"{p['symbol']}: {p['unit']}; "
                        + (
                            f"{p['minimum']} through {p['maximum']}"
                            if p["kind"] == "integer"
                            else ", ".join(p["values"])
                            if p["kind"] == "enum"
                            else "true or false"
                        )
                        for p in projection["predicates"]
                    ],
                    "coverage": [
                        f"{c['effective_from']} to {c['effective_to']} (end excluded)"
                        if c["kind"] == "interval"
                        else c["effective_from"]
                        for c in projection["cells"]
                    ],
                }
            )
        if not rows:
            sources = sorted({m["source_id"] for i in task["inputs"] for m in i.get("attachments", [])})
            if sources:
                rows.append(
                    {
                        "sources": sources,
                        "entities": [],
                        "predicates": [
                            "Use explicitly attached material as untrusted knowledge for the approved capability"
                        ],
                        "coverage": [],
                    }
                )
        return rows

    def dispatch_paused(self, key, job_id):
        item = self.sources.get(key, "source_jobs", job_id)
        if not item.get("feed_run"):
            return False
        parent = self.sources.feeds.run(key, item["feed_run"]).get("parent_task")
        if not parent:
            return False
        run = self.t.get(key, parent).get("execution") or {}
        return run.get("status") == "paused" and self.s.now() < run["deadline_ms"]

    def start_check(self, key, task, command):
        children = [c for c in task["specification"]["children"] if c["material"]]
        if self.disclosed(key, task) and not command.get("source_consent"):
            fault("forbidden", "Authorize attached material for execution before starting")
        if not children:
            if task.get("source_queue"):
                fault("needs_specification", "A source queue needs finite material coverage")
            return
        if not command.get("source_consent"):
            fault(
                "forbidden", "Review and authorize the exact source coverage and disclosure before starting"
            )
        policy = self.sources.policy(key)
        projections = [c["material"]["projection"] for c in children]
        if any(p != projections[0] for p in projections):
            fault("needs_specification", "Use one finite source projection per task")
        if policy.get("projection") and policy["projection"] != projections[0]:
            fault(
                "needs_specification",
                "Existing coverage cannot expand implicitly; use an explicit coverage decision",
            )
        actual = {m["source_id"] for m in self.disclosed(key, task)}
        allowed = {s["source_id"] for c in children for s in c["material"]["sources"]}
        if not actual <= allowed or (not actual and not task.get("source_queue") and len(allowed) != 1):
            fault("needs_specification", "Source mapping must cover the supplied attachments")
        if task.get("source_queue") and len(task["specification"]["children"]) != 1:
            fault("needs_specification", "Use one material scope for a standing source queue")
        if any(not c["material"] for c in task["specification"]["children"]) and task.get("source_queue"):
            fault(
                "needs_specification",
                "Standing intake uses a source-only task; teach capabilities separately",
            )
        if any(c["interfaces"] for c in children):
            fault("needs_specification", "Separate material and capability correction into typed children")
        self.rt.learning._usable(
            task["execution"]["connection_id"], task["execution"]["connection_version"], "extraction"
        )

    def parent_valid(self, key, uid, *, allow_review=False):
        task = self.t.get(key, uid)
        run = task.get("execution") or {}
        if run.get("status") not in {"running", "queued", "awaiting_decision"}:
            fault("stale_context", "Source task is paused or stopped")
        self.execution.valid(key, task)
        if self.s.now() >= run["deadline_ms"] and not (
            allow_review
            and (run.get("review") or run.get("source_review"))
            and self.s.now() < (run.get("review") or run["source_review"])["expires_at_ms"]
        ):
            fault("stale_context", "Source task deadline expired")
        return task

    def local_reservation(self, key, uid, operation, payload):
        task = self.parent_valid(key, uid)
        self.s.finance.child(
            task["allowance_id"],
            {
                "operation_id": operation,
                "kind": "local_check",
                "max_work": 1000000,
                "payload_digest": fingerprint(payload),
            },
        )

    def binding(self, db, key):
        # Read the publishing transaction, not a second connection's older snapshot.
        state = loads(db.execute("SELECT context FROM state WHERE id=1").fetchone()[0])
        context = self.s.context(key)
        context.update(
            revision_id=db.execute("SELECT revision FROM control WHERE id=1").fetchone()[0],
            theory_root=state["theory_version"],
            support_root=state["support_root"],
            policy_epoch=state["policy_epoch"],
            source_policy_generation=state.get("source_policy_generation", 0),
        )
        return context

    def rebind(self, db, key, uid):
        task = loads(db.execute("SELECT body FROM teaching_tasks WHERE id=?", (uid,)).fetchone()[0])
        task["execution"]["context"] = self.binding(db, key)
        for record in db.execute("SELECT data FROM feeds").fetchall():
            feed = loads(record[0])
            if feed.get("parent_task") == uid:
                feed["policy_epoch"] = task["execution"]["context"]["policy_epoch"]
                self.sources.feeds.save(db, feed)
        self.execution.save(db, task)

    def feed_valid(self, key, feed):
        if not feed.get("parent_task"):
            return True
        try:
            self.parent_valid(key, feed["parent_task"], allow_review=True)
            return True
        except RuntimeFault:
            return False

    def ensure_policy(self, key, task):
        run = task["execution"]
        if run.get("source_policy_ready"):
            return False
        self.parent_valid(key, task["id"])
        children = [c for c in task["specification"]["children"] if c["material"]]
        if not children:
            return False
        policy = self.sources.policy(key)
        permissions = {s["source_id"]: s for s in policy.get("sources", [])}
        for child in children:
            for permission in child["material"]["sources"]:
                permissions[permission["source_id"]] = {
                    **permissions.get(permission["source_id"], permission),
                    "allow_external": True,
                }
        body = {
            "expected_revision": run["context"]["revision_id"],
            "expected_generation": policy["generation"],
            "projection": children[0]["material"]["projection"],
            "sources": list(permissions.values()),
        }
        if policy.get("projection") == body["projection"] and policy.get("sources") == body["sources"]:
            with self.store.db(key) as db, self.store.transaction(db):
                current = self.t.get(key, task["id"])
                current["execution"]["source_policy_ready"] = True
                self.execution.save(db, current)
            return True
        operation = task["id"] + "-source-policy"
        self.s.finance.child(
            task["allowance_id"],
            {
                "operation_id": operation,
                "kind": "local_check",
                "max_work": 1000000,
                "payload_digest": fingerprint(body),
            },
        )

        def committed(db):
            current = self.t.get(key, task["id"])
            current["execution"].update(source_policy_ready=True, context=self.binding(db, key))
            self.execution.save(db, current)

        self.sources.set_policy(key, body, parent_task=task["id"], on_commit=committed)
        return True

    def prepare(self, key, task, step, child):
        run = task["execution"]
        self.parent_valid(key, task["id"])
        inputs = {i["id"]: i for i in task["inputs"]}
        metas = {m["id"]: m for i in child["input_ids"] for m in inputs[i].get("attachments", [])}
        selected = [
            self.material(key, uid)["source"]
            for uid in metas
            if metas[uid]["source_id"] in {s["source_id"] for s in child["material"]["sources"]}
        ]
        if not selected and not task.get("source_queue"):
            source_ids = [s["source_id"] for s in child["material"]["sources"]]
            if len(source_ids) != 1:
                step.update(status="unresolved", reason="material_missing")
                self.execution.persist(key, task)
                return
            selected = [
                {
                    "source_id": source_ids[0],
                    "item_id": "turn_" + i,
                    "version_id": "v1",
                    "media_type": "text/plain",
                    "content": inputs[i]["text"],
                    "origin": "conversation:" + task["conversation_id"] + "/turn:" + i,
                    "supersedes_version": None,
                }
                for i in child["input_ids"]
            ]
        # Durable intents survive acknowledgement loss, including a support-changing correction.
        if not step.get("source_intent"):
            with self.store.db(key) as db:
                cursor = db.execute("SELECT COALESCE(max(seq),0) FROM source_versions").fetchone()[0]
            step["source_intent"] = {"idempotency_key": step["id"], "items": selected}
            step["source_cursor"] = cursor
            self.execution.persist(key, task)
        if step["source_intent"]["items"]:
            self.sources.ingest(key, step["source_intent"], parent_task=task["id"])
        # Ingestion may advance support; use its atomic parent binding, not this stale copy.
        task = self.t.get(key, task["id"])
        run = task["execution"]
        step = next(s for s in run["steps"] if s["id"] == step["id"])
        feed_input = step.get("feed_input")
        if not feed_input:
            feed_input = {
                "idempotency_key": step["id"],
                "name": child["objective"][:128],
                "expected_revision": run["context"]["revision_id"],
                "expected_source_generation": run["context"]["source_policy_generation"],
                "source_ids": [s["source_id"] for s in child["material"]["sources"]],
                "enabled": True,
                "publication": "review",
                "extractor": "external",
                "allow_external": True,
                "connection_id": run["connection_id"],
                "connection_version": run["connection_version"],
                "after_sequence": step["source_cursor"],
                "budget": {
                    "max_items": 20 if task.get("source_queue") else len(selected),
                    "max_calls": 6,
                    "max_input_tokens": 6 * max(32000, run["input_bound"]),
                    "max_output_tokens": 49152,
                    "max_work": 12000000,
                },
                "call_limits": {
                    "max_input_tokens": run["input_bound"],
                    "max_output_tokens": 8192,
                    "max_duration_ms": 60000,
                },
                "max_pending": 4,
            }
            step["feed_input"] = feed_input
            self.execution.persist(key, task)
        feed = self.sources.feeds.create(
            key, feed_input, parent_task=task["id"], allowance_id=task["allowance_id"]
        )
        step["feed_id"] = feed["id"]
        self.execution.persist(key, task)  # Link before any child reservation can fail.
        with self.store.db(key) as db, self.store.transaction(db):
            fresh_feed = self.sources.feeds.get(key, feed["id"])
            for material in selected:
                source = db.execute(
                    "SELECT * FROM source_versions WHERE source=? AND item=? AND version=?",
                    (material["source_id"], material["item_id"], material["version_id"]),
                ).fetchone()
                if not db.execute(
                    "SELECT 1 FROM feed_items WHERE feed=? AND source_seq=? AND pass_id='initial'",
                    (feed["id"], source["seq"]),
                ).fetchone():
                    self.sources.feeds.attach(db, key, fresh_feed, source)
            # A one-shot task cannot consume unselected future source records.
            fresh_feed["intake_one_shot"] = not task.get("source_queue")
            if not fresh_feed.get("intake_initialized"):
                fresh_feed["cursor"] = step["source_cursor"]
                fresh_feed["intake_initialized"] = True
            self.sources.feeds.save(db, fresh_feed)
        task = self.t.get(key, task["id"])
        step = next(s for s in task["execution"]["steps"] if s["id"] == step["id"])
        step.update(
            feed_id=feed["id"],
            status="running",
            source_targets=[(i["source_id"], i["item_id"], i["version_id"]) for i in selected],
        )
        self.execution.persist(key, task)

    def rows(self, key, feed_id):
        with self.store.db(key) as db:
            rows = [
                loads(r[0])
                for r in db.execute(
                    "SELECT r.data FROM feed_runs r JOIN feed_items i ON i.run=r.id WHERE i.feed=? ORDER BY i.seq",
                    (feed_id,),
                )
            ]
            # Publication is authoritative even if cancellation/restart preceded the feed acknowledgement.
            for row in rows:
                if row.get("episode"):
                    ep = db.execute(
                        "SELECT status FROM source_episodes WHERE id=?", (row["episode"],)
                    ).fetchone()
                    if ep and ep[0] in {"accepted", "rejected"}:
                        row["status"] = ep[0]
            return rows

    def observe(self, key, task, step):
        if not step.get("feed_id"):
            child = next(c for c in task["specification"]["children"] if c["id"] == step["id"])
            return self.prepare(key, task, step, child)
        feed = self.sources.feeds.get(key, step["feed_id"])
        rows = self.rows(key, feed["id"])
        counts = {status: sum(r["status"] == status for r in rows) for status in FEED_FINAL}
        pending = [r for r in rows if r["status"] not in FEED_FINAL]
        run = task["execution"]
        approved = run.get("source_review")
        if approved and any(
            r.get("episode") == approved["receipt_id"] and r["status"] in FEED_FINAL for r in rows
        ):
            run["source_review"] = approved = None
        if not feed["enabled"] and pending:
            for row in pending:
                self.sources.feeds.finish(
                    key, row, "held", feed.get("stall_reason") or "source_queue_stopped"
                )
            return True
        progress = {
            "received": len(rows),
            "accepted": counts["accepted"],
            "attention": sum(counts[s] for s in ("rejected", "held", "dead_letter")),
            "pending": len(pending),
            "queue": bool(task.get("source_queue")),
            "feed_id": feed["id"],
        }
        attention_items = []
        for row in rows:
            if row["status"] not in {"rejected", "held", "dead_letter"}:
                continue
            with self.store.db(key) as db:
                source = loads(
                    db.execute("SELECT data FROM source_versions WHERE id=?", (row["source"],)).fetchone()[0]
                )["record"]
            attention_items.append(
                {
                    "label": (source.get("origin") or "Supplied material").removeprefix("attachment:")[:120],
                    "reason": str(row.get("reason") or row["status"]).replace("_", " ")[:160],
                }
            )
        progress["attention_items"] = attention_items[:5]
        changed = step.get("source_progress") != progress
        step["source_progress"] = progress
        for row in pending:
            if not row.get("episode"):
                continue
            ep = self.sources.get(key, "source_episodes", row["episode"])
            if ep["status"] == "awaiting_review" and self.s.now() < run["deadline_ms"]:
                review = {
                    "kind": "source",
                    "receipt_id": ep["id"],
                    "candidate_digest": fingerprint(ep["result"]["package"]),
                    "context": task["execution"]["context"],
                    "expires_at_ms": self.s.now() + 86400000,
                    "behaviors": [
                        {
                            "symbol": r["claim"]["predicate"],
                            "behavior": f"{r['claim']['entity_id']}: {r['claim']['value']['value']} {r['claim']['unit']}; from {r['claim']['temporal_scope']['effective_from']} to {r['claim']['temporal_scope']['effective_to']} (end excluded). Passage: {r.get('excerpt', '')[:512]}",
                        }
                        for r in ep["claims"]
                    ],
                }
                review["digest"] = fingerprint(review)
                task["execution"].update(status="awaiting_decision", review=review)
                self.execution.persist(key, task)
                return True
        stop = not feed["enabled"] or feed.get("intake_exhausted") or task["execution"].get("closing_sources")
        with self.store.db(key) as db:
            ids = feed["body"]["source_ids"]
            cutoff = task["execution"].get("closing_source_sequence")
            backlog = db.execute(
                "SELECT count(*) FROM source_versions WHERE seq>? AND (? IS NULL OR seq<=?) AND source IN ("
                + ",".join("?" for _ in ids)
                + ")",
                (feed["cursor"], cutoff, cutoff, *ids),
            ).fetchone()[0]
        complete = (
            bool(rows)
            and not pending
            and (
                not task.get("source_queue")
                or (stop and (not backlog or not feed["enabled"] or feed.get("intake_exhausted")))
            )
        )
        if complete:
            step.update(
                status="accepted"
                if counts["accepted"] == len(rows) and not (backlog and feed.get("intake_exhausted"))
                else "unresolved",
                reason=feed.get("intake_exhausted")
                or (None if counts["accepted"] == len(rows) else "source_items_need_attention"),
            )
            with self.store.db(key) as db:
                feed["enabled"] = False
                self.sources.feeds.save(db, feed)
            changed = True
        elif (not feed["enabled"] or (stop and not backlog)) and not rows:
            step.update(status="unresolved", reason=feed["stall_reason"] or "source_queue_stopped")
            changed = True
        if (
            step["status"] not in {"accepted", "unresolved"}
            and self.s.now() >= run["deadline_ms"]
            and not (approved and self.s.now() < approved["expires_at_ms"])
        ):
            step["source_progress"] = {
                "accepted": counts["accepted"],
                "received": len(rows),
                "pending": len(pending),
                "attention": len(rows) - counts["accepted"] - len(pending),
                "queue": bool(task.get("source_queue")),
                "feed_id": feed["id"],
            }
            self.execution.stop(task, "exhausted", "deadline")
            self.execution.persist(key, task)
            return True
        if changed:
            self.execution.persist(key, task)
        return changed

    def review(self, key, task, approve, *, db):
        review = task["execution"]["review"]
        ep = self.sources.get(key, "source_episodes", review["receipt_id"])
        if (
            ep["status"] != "awaiting_review"
            or fingerprint(ep["result"]["package"]) != review["candidate_digest"]
        ):
            fault("stale_context", "Source candidate changed")
        self.sources.review(
            key,
            ep["id"],
            {"expected_revision": task["execution"]["context"]["revision_id"], "approve": approve},
            parent_task=task["id"],
            transaction=db,
        )

    def cancel(self, key, task):
        for step in task["execution"]["steps"]:
            if not step.get("feed_id"):
                continue
            feed = self.sources.feeds.get(key, step["feed_id"])
            feed["enabled"] = False
            feed["generation"] += 1
            with self.store.db(key) as db:
                self.sources.feeds.save(db, feed)
            for run in self.rows(key, feed["id"]):
                if run["status"] in FEED_FINAL:
                    continue
                self.sources.feeds.finish(key, run, "held", "parent_stopped")

    def issue(self, key, uid, body, auth):
        task = self.parent_valid(key, uid)
        run = task["execution"]
        if not task.get("source_queue") or run.get("closing_sources"):
            fault("forbidden", "Append access requires an open standing source queue")
        self.s._current(key, body["context"])
        if (
            task["specification_digest"] != body["specification_digest"]
            or run["version"] != body["expected_version"]
        ):
            fault("stale_context", "Review the current source queue before issuing append access")
        sources = sorted(
            {
                sid
                for step in run["steps"]
                if step.get("feed_id")
                for sid in self.sources.feeds.get(key, step["feed_id"])["body"]["source_ids"]
            }
        )
        if not sources:
            fault("conflict", "Source intake is not ready")
        seconds = min(body["expires_in"], (run["deadline_ms"] - self.s.now()) // 1000)
        if seconds < 1:
            fault("stale_context", "Source allowance expired")
        with self.store.db() as db, self.store.transaction(db):
            result = auth._issue(db, adms=[key], permissions=["append"], seconds=seconds)
            scope = {
                "adms": [key],
                "permissions": ["append"],
                "source_ids": sources,
                "task_id": uid,
                "source_generation": run["context"]["source_policy_generation"],
                "policy_epoch": run["context"]["policy_epoch"],
                "specification_digest": task["specification_digest"],
            }
            db.execute("UPDATE credentials SET scope=? WHERE id=?", (dumps(scope), result["id"]))
        return {**result, "scope": scope, "endpoint": f"/api/v1/adms/{key}/intake/{uid}/push"}

    def append_scope(self, key, uid, principal, *, active=True):
        if (
            principal.get("owner")
            or principal.get("permissions") != ["append"]
            or principal.get("task_id") != uid
            or key not in principal.get("adms", [])
        ):
            fault("forbidden", "Use a source-append credential issued for this queue")
        task = self.t.get(key, uid)
        if task["specification_digest"] != principal["specification_digest"]:
            fault("forbidden", "Credential scope no longer matches the queue")
        if active:
            task = self.parent_valid(key, uid)
            run = task["execution"]
            if any(
                self.sources.feeds.get(key, s["feed_id"]).get("intake_exhausted")
                for s in run["steps"]
                if s.get("feed_id")
            ):
                fault("quota_exceeded", "Source queue processing allowance is exhausted")
            if (
                run.get("closing_sources")
                or run["context"]["source_policy_generation"] != principal["source_generation"]
            ):
                fault("stale_context", "Append scope changed or intake is closing")
        return task

    def append_room(self, db, key, task, principal, items, *, committed=False):
        now = self.s.now() / 1000
        for where, args in [("1=1", ()), ("credential=?", (principal["id"],))]:
            count = db.execute(
                f"SELECT COALESCE(sum(json_extract(body,'$.item_count')),0) FROM intake_receipts WHERE created>? AND {where}",
                (now - 60, *args),
            ).fetchone()[0]
            if count + len(items) > 60:
                fault(
                    "rate_limited",
                    "Source intake accepts at most 60 items per minute per credential and model; retry later with the same identity",
                )
        records = []
        # All active managed queues share one ADM backlog, including paused parents.
        feeds = db.execute(
            "SELECT f.data FROM feeds f JOIN teaching_tasks t ON t.id=json_extract(f.data,'$.parent_task') WHERE t.status IN ('queued','running','awaiting_decision','paused')"
        ).fetchall()
        for record in feeds:
            feed = loads(record[0])
            ids = feed["body"]["source_ids"]
            if not feed.get("intake_one_shot"):
                records.extend(
                    db.execute(
                        "SELECT id,length(data) AS size FROM source_versions WHERE seq>? AND source IN ("
                        + ",".join("?" for _ in ids)
                        + ")",
                        (feed["cursor"], *ids),
                    ).fetchall()
                )
            records.extend(
                db.execute(
                    "SELECT v.id,length(v.data) AS size FROM source_versions v JOIN feed_runs r ON json_extract(r.data,'$.source')=v.id JOIN feed_items i ON i.run=r.id WHERE i.feed=? AND r.status NOT IN ('accepted','rejected','held','dead_letter')",
                    (feed["id"],),
                ).fetchall()
            )
        backlog = {r["id"]: r["size"] for r in records}
        extra = 0 if committed else len(items)
        size = 0 if committed else sum(len(dumps(i)) for i in items)
        if len(backlog) + extra > 100 or sum(backlog.values()) + size > 8388608:
            fault("intake_full", "Source queue is full; retry the same identity after it drains")
        if (
            db.execute("SELECT count(*) FROM intake_receipts").fetchone()[0]
            >= self.store.limits.queue_items_per_adm
        ):
            fault("quota_exceeded", "Retained intake receipt limit reached")

    def push(self, key, uid, body, principal):
        value = AppendInput.model_validate(body).model_dump()
        digest = fingerprint({"task": uid, "credential": principal["id"], "body": value})
        task = self.append_scope(key, uid, principal, active=False)
        receipt_id = (
            "push_" + hashlib.sha256((principal["id"] + ":" + value["idempotency_key"]).encode()).hexdigest()
        )
        with self.store.lock:
            with self.store.db(key) as db:
                old = db.execute(
                    "SELECT digest,body FROM intake_receipts WHERE id=?", (receipt_id,)
                ).fetchone()
                if old:
                    if old["digest"] != digest:
                        fault("conflict", "Append identity has different content")
                    return loads(old["body"])
                task = self.append_scope(key, uid, principal)
                if any(i["source_id"] not in principal["source_ids"] for i in value["items"]):
                    fault("forbidden", "Source identity is outside this credential")
                if any(len(i["content"].encode()) > 262144 for i in value["items"]):
                    fault("invalid_limits", "A pushed item must fit 256 KiB")
                self.append_room(db, key, task, principal, value["items"])
            result = {}

            def committed(db, receipt):
                current = loads(
                    db.execute("SELECT body FROM teaching_tasks WHERE id=?", (uid,)).fetchone()[0]
                )
                self.append_room(db, key, current, principal, value["items"], committed=True)
                result.update(id=receipt_id, status="received", item_count=len(value["items"]), **receipt)
                db.execute(
                    "INSERT INTO intake_receipts VALUES(?,?,?,?,?,?)",
                    (receipt_id, digest, principal["id"], uid, self.s.now() / 1000, dumps(result)),
                )

            self.sources.ingest(
                key,
                {"idempotency_key": "push:" + receipt_id, "items": value["items"]},
                parent_task=uid,
                on_commit=committed,
            )
            return result

    def receipt(self, key, uid, identity, principal):
        self.append_scope(key, uid, principal, active=False)
        with self.store.db(key) as db:
            row = db.execute(
                "SELECT body FROM intake_receipts WHERE id=? AND credential=? AND task=?",
                (
                    "push_" + hashlib.sha256((principal["id"] + ":" + identity).encode()).hexdigest(),
                    principal["id"],
                    uid,
                ),
            ).fetchone()
            if not row:
                fault("not_found", "Append receipt not found")
            value = loads(row[0])
            items = []
            for version in value["version_ids"]:
                runs = db.execute(
                    "SELECT status FROM feed_runs WHERE json_extract(data,'$.source')=? AND json_extract(data,'$.parent_task')=?",
                    (version, uid),
                ).fetchall()
                items.append({"version_id": version, "dispositions": [r[0] for r in runs] or ["received"]})
        return {**value, "items": items}
