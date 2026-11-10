"""Registry-owned allowance accounting, committed with provider reservations.

The registry and an ADM inbox are different transactions. A child reservation is
retained before its inbox write; an interrupted handoff is not permission to retry.
"""

import base64
from uuid import uuid4

from ..engine.artifacts import digest
from ..runtime.protocol import dumps, loads
from .errors import AllowanceFault
from .models import AllowanceInput, ChildInput, PriceInput, SpendingInput
from .pricing import INTERACTION, LEARNING, MAX_BILLABLE_INPUT, amount, check_wire, profile


def fail(code, message):
    raise AllowanceFault(code, message)


class Allowances:
    def __init__(self, learning):
        self.learning, self.store = learning, learning.store

    def now(self):
        with self.store.db() as db:
            persisted = db.execute("SELECT clock FROM learning_control WHERE id=1").fetchone()[0]
        return int(max(self.learning.now(), persisted) * 1000)

    def checkpoint(self, db):
        db.execute("UPDATE learning_control SET clock=max(clock,?) WHERE id=1", (self.learning.now(),))

    @staticmethod
    def one(db, table, key):
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (key,)).fetchone()
        if row is None:
            fail("not_found", "Unknown priced resource")
        return row

    def settings(self):
        with self.store.db() as db:
            row = db.execute("SELECT * FROM spending_control WHERE id=1").fetchone()
            legacy = db.execute("SELECT count(*) FROM legacy_spending").fetchone()[0]
            return {
                "generation": row["generation"],
                "enabled": False,
                **loads(row["body"]),
                "legacy_grants": legacy,
                "legacy_valuation": "unpriced_legacy" if legacy else "not_applicable",
                "usage": self.installation_usage(db),
                "suspended_lanes": [
                    r[0] for r in db.execute("SELECT lane FROM provider_lanes WHERE suspended=1")
                ],
            }

    def configure(self, body):
        value = SpendingInput.model_validate(body).model_dump()
        if value["enabled"] and (
            self.learning.config.runtime.provider_concurrency < 2
            or self.learning.config.runtime.provider_concurrency_per_adm < 2
        ):
            fail("unsupported", "Priced lanes require at least two provider slots globally and per ADM")
        with self.store.lock, self.store.db() as db, self.store.transaction(db):
            self.checkpoint(db)
            old = db.execute("SELECT * FROM spending_control WHERE id=1").fetchone()
            if old["generation"] != value.pop("expected_generation"):
                fail("stale_context", "Installation spending settings changed")
            previous = loads(old["body"])
            # A legacy hold is a conservative owner allocation, not retroactive billing.
            if (previous.get("legacy_hold_micro_usd") or 0) > (value["legacy_hold_micro_usd"] or 0):
                fail("conflict", "Legacy uncertainty cannot be refunded by changing settings")
            if (
                value["enabled"]
                and db.execute("SELECT 1 FROM legacy_spending LIMIT 1").fetchone()
                and not value["legacy_hold_micro_usd"]
            ):
                fail(
                    "conflict",
                    "Historic unpriced calls require a positive conservative legacy hold before paid dispatch",
                )
            used = self.installation_usage(db)
            if any(used[k] > value[k + "_micro_usd"] for k in ("interaction", "learning")):
                fail("quota_exceeded", "New installation cap is below committed allowances")
            if db.execute("SELECT count(*) FROM spending_history").fetchone()[0] >= 1000:
                fail("quota_exceeded", "Retained spending settings limit reached")
            for selected in value["resume_lanes"]:
                db.execute("UPDATE provider_lanes SET suspended=0 WHERE lane=?", (selected,))
            db.execute("INSERT INTO spending_history VALUES(?,?)", (old["generation"] + 1, dumps(value)))
            db.execute(
                "UPDATE spending_control SET generation=generation+1,body=? WHERE id=1", (dumps(value),)
            )
        return self.settings()

    def save_price(self, body):
        value = PriceInput.model_validate(body).model_dump()
        identity = digest(dumps(value))
        with self.store.lock, self.store.db() as db, self.store.transaction(db):
            self.checkpoint(db)
            old = db.execute("SELECT * FROM prices WHERE idem=?", (value["idempotency_key"],)).fetchone()
            if old:
                if old["digest"] != identity:
                    fail("conflict", "Price idempotency key has different content")
                return loads(old["body"])
            c = self.learning.connection(value["connection_id"])
            if (c["version"], c["configuration_digest"]) != (
                value["connection_version"],
                value["configuration_digest"],
            ):
                fail("stale_context", "Price must bind the current exact connection version")
            bound = profile(value, c)
            if not self.now() < value["valid_until_ms"] <= self.now() + 30 * 86400000:
                fail("invalid_input", "Price validity must be within the next 30 days")
            # Audited context/rate evidence expires; owner input cannot extend it.
            if not bound["synthetic"] and value["valid_until_ms"] > 1796688000000:
                fail(
                    "unsupported", "Audited provider profile requires renewed evidence after 8 December 2026"
                )
            if db.execute("SELECT count(*) FROM prices").fetchone()[0] >= 1000:
                fail("quota_exceeded", "Retained price limit reached")
            value.update(
                id=str(uuid4()), valid_from_ms=self.now(), provider=c["provider"], model=c["model"], **bound
            )
            # A new version invalidates old dispatch authority, never old valuation.
            for row in db.execute("SELECT id,body FROM prices WHERE revoked=0").fetchall():
                if loads(row["body"])["connection_id"] == c["id"]:
                    db.execute("UPDATE prices SET revoked=1 WHERE id=?", (row["id"],))
            db.execute(
                "INSERT INTO prices(id,idem,digest,body) VALUES(?,?,?,?)",
                (value["id"], value["idempotency_key"], identity, dumps(value)),
            )
        return value

    def price_options(self, connection_id):
        """Expose only existing audited profiles; never infer prices from a model name."""
        conn = self.learning.connection(connection_id)
        choices = []
        for name, inputs, outputs, expiry in (
            ("recorded-test/1", 2_000_000, 4_000_000, self.now() + 86400000),
            (
                "openai-4o-context/2026-11-08",
                2_500_000,
                10_000_000,
                min(self.now() + 86400000, 1796688000000),
            ),
            (
                "openai-5.6-luna-context/2026-11-09",
                500_000,
                1_800_000,
                min(self.now() + 86400000, 1796688000000),
            ),
        ):
            value = {
                "bound_profile": name,
                "input_micro_usd_per_million": inputs,
                "output_micro_usd_per_million": outputs,
                "valid_until_ms": expiry,
            }
            try:
                bound = profile(value, conn)
            except AllowanceFault:
                continue
            if expiry > self.now():
                choices.append({**value, **bound})
        return {
            "connection_id": conn["id"],
            "connection_version": conn["version"],
            "configuration_digest": conn["configuration_digest"],
            "items": choices,
        }

    def price(self, db, key, *, active=True):
        row = self.one(db, "prices", key)
        value = loads(row["body"])
        if active:
            c = self.learning.connection(value["connection_id"])
            if (
                row["revoked"]
                or not value["valid_from_ms"] <= self.now() < value["valid_until_ms"]
                or (c["version"], c["configuration_digest"])
                != (value["connection_version"], value["configuration_digest"])
            ):
                fail(
                    "stale_context",
                    "Pinned price expired, was replaced or no longer matches the connection; authorize a new allowance",
                )
        return value

    def totals(self, db, key):
        rows = db.execute("SELECT * FROM charges WHERE allowance_id=?", (key,)).fetchall()
        return {
            "settled_micro_usd": sum(int(r["settled"]) if r["settled"] is not None else 0 for r in rows),
            "reserved_micro_usd": sum(r["reserved"] for r in rows if r["settled"] is None),
            "unresolved_calls": sum(r["settled"] is None for r in rows),
            "unknown_micro_usd": sum(
                r["reserved"] for r in rows if r["settled"] is None and r["state"] == "unknown"
            ),
        }

    def installation_usage(self, db):
        totals = {"interaction": 0, "learning": 0}
        for row in db.execute("SELECT * FROM allowances").fetchall():
            value = loads(row["body"])
            used = self.totals(db, row["id"])
            amount_used = used["settled_micro_usd"] + used["reserved_micro_usd"]
            # Full allocated cap remains protected while usable. Expiry/close only
            # releases provably unspent room, never a call's retained reservation.
            if row["state"] == "active" and value["expires_at_ms"] > self.now():
                amount_used = max(amount_used, value["cap_micro_usd"])
            totals[value["lane"]] += amount_used
        return totals

    def create(self, body):
        value = AllowanceInput.model_validate(body).model_dump()
        identity = digest(dumps(value))
        with self.store.lock, self.store.db() as db, self.store.transaction(db):
            self.checkpoint(db)
            old = db.execute("SELECT * FROM allowances WHERE idem=?", (value["idempotency_key"],)).fetchone()
            if old:
                if old["digest"] != identity:
                    fail("conflict", "Allowance idempotency key has different content")
                return self.view_in(db, old["id"])
            if value["adm_id"]:
                if self.store.info(value["adm_id"])["archived"]:
                    fail("stale_context", "Cannot fund an archived ADM")
            price = self.price(db, value["price_id"])
            scope = value["scope"]
            max_duration = 86400000 if scope in ("interaction", "source") else 3600000
            if (
                not self.now()
                < value["expires_at_ms"]
                <= min(self.now() + max_duration, price["valid_until_ms"])
            ):
                fail("invalid_input", "Allowance expiry exceeds its scope or pinned price validity")
            value["lane"] = "interaction" if scope == "interaction" else "learning"
            settings = loads(db.execute("SELECT body FROM spending_control WHERE id=1").fetchone()[0])
            if not settings.get("enabled"):
                fail("remote_calls_disabled", "Explicit installation spending configuration is required")
            used = self.installation_usage(db)
            if used[value["lane"]] + value["cap_micro_usd"] > settings[value["lane"] + "_micro_usd"]:
                fail("quota_exceeded", "Installation lane cannot reserve this allowance")
            summary = scope in ("task", "source")
            value["completion"] = (
                {
                    "calls": 1,
                    "input_tokens": price["input_bound"],
                    "output_tokens": 4096,
                    "micro_usd": amount(price["input_bound"], 4096, price),
                }
                if summary
                else None
            )
            if summary and (
                value["max_calls"] < 2
                or value["max_input_tokens"] <= price["input_bound"]
                or value["max_output_tokens"] <= 4096
                or value["cap_micro_usd"] <= value["completion"]["micro_usd"]
                or value["max_children"] < 2
            ):
                fail(
                    "invalid_limits",
                    "Learning allowance must include protected completion capacity and room for work",
                )
            if db.execute("SELECT count(*) FROM allowances").fetchone()[0] >= 10000:
                fail("quota_exceeded", "Retained allowance limit reached")
            if value["completion"]:
                for scope in ("installation", "per_adm"):
                    adm = value["adm_id"] if scope == "per_adm" else None
                    used = self.learning.usage_snapshot(db, adm=adm)
                    held = self.summary_holds(db, adm=adm)
                    lane_used = self.learning.usage_snapshot(db, adm=adm, lane="learning")
                    for field in ("calls", "input_tokens", "output_tokens"):
                        cap = getattr(self.learning.config.learning.quotas, field + "_" + scope)
                        n = value["completion"][field]
                        if used[field] + held[field] + n > cap or lane_used[field] + held[field] + n > max(
                            1, cap * 60 // 100
                        ):
                            fail(
                                "quota_exceeded", "Installation cannot protect completion token/call capacity"
                            )
            value.update(id=str(uuid4()), created_at_ms=self.now(), synthetic=price["synthetic"])
            db.execute(
                "INSERT INTO allowances(id,idem,digest,body) VALUES(?,?,?,?)",
                (value["id"], value["idempotency_key"], identity, dumps(value)),
            )
            return self.view_in(db, value["id"])

    def summary_holds(self, db, *, adm=None, lane=None, consuming=None):
        held = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        if lane == "interaction":
            return held
        for row in db.execute("SELECT * FROM allowances WHERE state='active'").fetchall():
            a = loads(row["body"])
            if (
                not a["completion"]
                or a["expires_at_ms"] <= self.now()
                or row["id"] == consuming
                or (adm is not None and a["adm_id"] != adm)
            ):
                continue
            calls = db.execute(
                "SELECT g.body FROM grants g JOIN charges c ON c.grant_id=g.id WHERE c.allowance_id=?",
                (row["id"],),
            ).fetchall()
            if any(loads(r[0])["purpose"] == "task_narration" for r in calls):
                continue
            for field in held:
                held[field] += a["completion"][field]
        return held

    def view_in(self, db, key):
        row = self.one(db, "allowances", key)
        value = loads(row["body"])
        state = (
            "expired" if row["state"] == "active" and self.now() >= value["expires_at_ms"] else row["state"]
        )
        return {
            **value,
            "state": state,
            **self.totals(db, key),
            "valuation": "synthetic_test_estimate" if value["synthetic"] else "estimated_token_charges",
        }

    def view(self, key):
        with self.store.db() as db:
            return self.view_in(db, key)

    def listing(self, table, after=0, limit=20):
        with self.store.db() as db:
            rows = db.execute(
                f"SELECT * FROM {table} WHERE seq>? ORDER BY seq LIMIT ?", (after, limit)
            ).fetchall()
            return {
                "items": [
                    self.view_in(db, r["id"])
                    if table == "allowances"
                    else {**loads(r["body"]), "revoked": bool(r["revoked"])}
                    for r in rows
                ],
                "next_cursor": rows[-1]["seq"] if rows else after,
            }

    def close(self, key, expected):
        with self.store.lock, self.store.db() as db, self.store.transaction(db):
            self.checkpoint(db)
            row = self.one(db, "allowances", key)
            if row["state"] != expected:
                fail("stale_context", "Allowance state changed")
            db.execute("UPDATE allowances SET state='closed' WHERE id=?", (key,))
            return self.view_in(db, key)

    def valid(self, db, key):
        row = self.one(db, "allowances", key)
        value = loads(row["body"])
        settings = loads(db.execute("SELECT body FROM spending_control WHERE id=1").fetchone()[0])
        if row["state"] != "active" or self.now() >= value["expires_at_ms"] or not settings.get("enabled"):
            fail("stale_context", "Allowance is closed, suspended, expired or paid work is disabled")
        if db.execute("SELECT suspended FROM provider_lanes WHERE lane=?", (value["lane"],)).fetchone()[0]:
            fail("quota_exceeded", "Spending lane requires owner review after a usage overrun")
        used = self.installation_usage(db)
        if used[value["lane"]] > settings[value["lane"] + "_micro_usd"]:
            fail("quota_exceeded", "Installation lane commitments exceed the configured cap")
        price = self.price(db, value["price_id"])
        return value, price

    def child(self, key, body):
        """Reserve bounded child work BEFORE per-ADM creation; replay same identity only."""
        value = ChildInput.model_validate(body).model_dump()
        identity = digest(dumps(value))
        with self.store.lock, self.store.db() as db, self.store.transaction(db):
            self.checkpoint(db)
            old = db.execute(
                "SELECT * FROM budget_children WHERE allowance_id=? AND operation_id=?",
                (key, value["operation_id"]),
            ).fetchone()
            if old:
                if old["digest"] != identity:
                    fail("conflict", "Child identity has different work")
                return loads(old["body"])
            allowance, _ = self.valid(db, key)
            count, work = db.execute(
                "SELECT count(*),COALESCE(sum(COALESCE(used_work,json_extract(body,'$.max_work'))),0) FROM budget_children WHERE allowance_id=?",
                (key,),
            ).fetchone()
            if count >= allowance["max_children"] or work + value["max_work"] > allowance["max_work"]:
                fail("quota_exceeded", "Parent child/work allowance exhausted")
            value["reserved_at_ms"] = self.now()
            db.execute(
                "INSERT INTO budget_children VALUES(?,?,?,?,NULL)",
                (key, value["operation_id"], identity, dumps(value)),
            )
        return value

    def settle_work(self, key, operation, used):
        with self.store.lock, self.store.db() as db, self.store.transaction(db):
            self.checkpoint(db)
            row = db.execute(
                "SELECT * FROM budget_children WHERE allowance_id=? AND operation_id=?", (key, operation)
            ).fetchone()
            if not row or type(used) is not int or not 0 <= used <= loads(row["body"])["max_work"]:
                fail("invalid_input", "Invalid child work settlement")
            if row["used_work"] is not None and row["used_work"] != used:
                fail("conflict", "Child work already settled")
            db.execute(
                "UPDATE budget_children SET used_work=? WHERE allowance_id=? AND operation_id=?",
                (used, key, operation),
            )

    def prepare(self, body, adm):
        """Compute bound before token reservation. No ledger mutation here."""
        c = self.learning.connection(body["connection_id"])
        key = body.get("allowance_id")
        if not key:
            if c["provider"] != "recorded":
                fail(
                    "forbidden",
                    "Paid provider work needs an explicit priced allowance; token-only limits are not a dollar authorization",
                )
            return None  # Clearly unpriced, no-egress recorded rehearsal.
        with self.store.db() as db:
            allowance, price = self.valid(db, key)
        purpose = body["purpose"]
        allowed = (
            INTERACTION
            if allowance["scope"] == "interaction"
            else ({"connection_test"} if allowance["scope"] == "control" else LEARNING)
        )
        if (
            purpose not in allowed
            or allowance["adm_id"] != adm
            or (body["connection_id"], body["connection_version"], body["configuration_digest"])
            != (price["connection_id"], price["connection_version"], price["configuration_digest"])
        ):
            fail("forbidden", "Purpose, ADM or connection is outside this allowance")
        if any(
            body["limits"][k] > v
            for k, v in {
                "max_input_tokens": MAX_BILLABLE_INPUT,
                "max_output_tokens": 16384,
                "max_duration_ms": 120000,
            }.items()
        ):
            fail("invalid_limits", "Priced call exceeds hard caps")
        check_wire(
            base64.b64decode(body["wire"], validate=True), c, price, body["limits"]["max_output_tokens"]
        )
        if price["input_bound"] > body["limits"]["max_input_tokens"]:
            fail(
                "invalid_limits",
                "Verified billable input bound exceeds call cap; authorize sufficient input tokens or use another audited counting profile",
            )
        body["input_estimate"] = price["input_bound"]
        body["deadline"] = min(body["deadline"], allowance["expires_at_ms"] / 1000)
        return price

    def reserve(self, db, body, price):
        if price is None:
            return
        key = body["allowance_id"]
        allowance, current_price = self.valid(db, key)
        if current_price != price:
            fail("stale_context", "Pinned price changed")
        rows = db.execute(
            "SELECT g.* FROM grants g JOIN charges c ON c.grant_id=g.id WHERE c.allowance_id=?", (key,)
        ).fetchall()
        is_summary = body["purpose"] == "task_narration"
        # One completion reservation is protected from every other paid step.
        summary_used = any(loads(r["body"])["purpose"] == "task_narration" for r in rows)
        if is_summary and summary_used:
            fail("conflict", "Completion narration already reserved; do not repeat completed work")
        hold = (
            allowance["completion"]
            if allowance["completion"] and not summary_used and not is_summary
            else None
        )
        if is_summary and body["limits"]["max_output_tokens"] > 4096:
            fail("invalid_limits", "Completion narration exceeds protected output capacity")
        cost = amount(body["input_estimate"], body["limits"]["max_output_tokens"], price)
        totals = self.totals(db, key)
        if (
            totals["settled_micro_usd"]
            + totals["reserved_micro_usd"]
            + cost
            + (hold["micro_usd"] if hold else 0)
            > allowance["cap_micro_usd"]
        ):
            fail("quota_exceeded", "Learning or interaction dollar allowance exhausted")
        proposed = {
            "calls": 1,
            "input_tokens": body["input_estimate"],
            "output_tokens": body["limits"]["max_output_tokens"],
        }
        for field, n in proposed.items():
            if sum(r[field] for r in rows) + n + (hold[field] if hold else 0) > allowance["max_" + field]:
                fail("quota_exceeded", "Parent token/call allowance exhausted")
        body["spending_generation"] = db.execute(
            "SELECT generation FROM spending_control WHERE id=1"
        ).fetchone()[0]
        body["price_binding"] = {
            "price_id": price["id"],
            "allowance_id": key,
            "reserved_micro_usd": cost,
            "input_bound": body["input_estimate"],
            "synthetic": price["synthetic"],
        }
        db.execute(
            "INSERT INTO charges VALUES(?,?,?,NULL,'reserved',?)", (body["id"], key, cost, dumps(price))
        )

    def settle(self, db, grant, usage=None, *, not_dispatched=False):
        row = db.execute("SELECT * FROM charges WHERE grant_id=?", (grant,)).fetchone()
        if row is None or row["settled"] is not None:
            return
        if not_dispatched:
            cost, state = 0, "not_dispatched"
        elif usage is None:
            db.execute("UPDATE charges SET state='unknown' WHERE grant_id=?", (grant,))
            return
        else:
            cost = amount(usage["input_tokens"], usage["output_tokens"], loads(row["price"]))
            state = "settled_estimate"
        db.execute("UPDATE charges SET settled=?,state=? WHERE grant_id=?", (str(cost), state, grant))
        if cost > row["reserved"]:
            db.execute("UPDATE allowances SET state='suspended' WHERE id=?", (row["allowance_id"],))

    def reconcile(self, db):
        for row in db.execute(
            "SELECT g.* FROM grants g JOIN charges c ON c.grant_id=g.id WHERE c.settled IS NULL"
        ).fetchall():
            outcome = loads(row["outcome"]) if row["outcome"] else None
            if row["status"] == "not_dispatched":
                self.settle(db, row["id"], not_dispatched=True)
            elif outcome:
                assessed = self.learning._account_outcome(db, loads(row["body"]), outcome)
                self.settle(db, row["id"], assessed.get("usage"))
