"""Owner-only bounded diagnostics and retention previews; no raw content export."""

import time
from pathlib import Path

from .. import __version__
from ..runtime.protocol import dumps

TABLES = (
    "requests",
    "attempts",
    "events",
    "revisions",
    "versions",
    "runs",
    "episodes",
    "learning_receipts",
    "source_versions",
    "source_jobs",
    "source_claims",
    "source_episodes",
    "source_support",
    "feeds",
    "feed_items",
    "feed_runs",
)
STATES = {
    "received",
    "queued",
    "evaluating",
    "succeeded",
    "failed",
    "cancelled",
    "inconclusive",
    "needs_input",
    "waiting_for_learning",
    "interrupted",
    "ready",
    "leased",
    "dispatched",
    "outcome_unknown",
    "not_dispatched",
    "completed",
    "accepted",
    "rejected",
    "held",
    "dead_letter",
    "extracting",
    "extracted",
    "needs_specification",
    "needs_evidence",
    "proposed_schema",
    "approved",
    "invalid",
    "partial",
    "projecting",
    "awaiting_review",
    "stopped",
    "pending",
    "running",
    "checking",
    "preparing",
    "validating",
    "awaiting_provider",
}


def statuses(db, table):
    result = {}
    for state, count in db.execute(f"SELECT status,count(*) FROM {table} GROUP BY status"):
        label = state if state in STATES else "other"
        result[label] = result.get(label, 0) + count
    return result


def file_bytes(root):
    return sum(p.stat().st_size for p in Path(root).iterdir() if p.is_file() and not p.is_symlink())


def retention(runtime):
    result = {
        "profile": "awm-adm-retention/1",
        "automatic_cleanup": False,
        "event_days": runtime.config.retention.event_days,
        "retained_until_explicit_future_dependency_aware_deletion": [
            "source_text_and_claims",
            "models_policies_and_support",
            "proof_results",
            "request_and_source_idempotency",
            "private_drafts_and_diagnostics",
            "dispatch_ledger_and_unknown_reservations",
            "feed_cursors_and_items",
        ],
        "age_settings_are_review_thresholds_not_deletion_promises": True,
        "instances": [],
    }
    cutoff = time.time() - runtime.config.retention.event_days * 86400
    with runtime.store.lock:
        for item in runtime.store.list():
            if item["status"] != "ready":
                continue
            with runtime.store.db(item["id"]) as db:
                # Only a contiguous old prefix is eligible; wall clocks may go backward.
                first_recent = db.execute(
                    "SELECT min(seq) FROM events WHERE created>=?", (cutoff,)
                ).fetchone()[0]
                row = db.execute(
                    "SELECT count(*),COALESCE(max(seq),0) FROM events WHERE created<? AND (? IS NULL OR seq<?)",
                    (cutoff, first_recent, first_recent),
                ).fetchone()
                result["instances"].append(
                    {
                        "adm_id": item["id"],
                        "eligible_event_count": row[0],
                        "prune_through": row[1],
                        "requires_owner_command": True,
                    }
                )
    return result


def diagnostic(runtime):
    start = time.monotonic()
    store = runtime.store
    # One process lock prevents concurrent mutations across this bounded read. No
    # external calls and no raw blobs/queries/names/messages/credentials are exported.
    with store.lock:
        report = {
            "profile": "awm-adm-diagnostics/1",
            "version": __version__,
            "created_at_ms": int(time.time() * 1000),
            "generation": store.generation,
            "content_included": False,
            "status": runtime.status(),
            "storage": {
                "bytes": file_bytes(store.root),
                "limit_bytes": runtime.config.runtime.installation_storage_bytes,
            },
            "compute": {
                "serving": runtime.supervisor.metrics.snapshot(),
                "background": runtime.learning.supervisor.metrics.snapshot(),
            },
            "instances": [],
            "retention": retention(runtime),
        }
        with store.db() as db:
            report["provider"] = {
                "accounted_current_window": runtime.learning.usage(),
                "retained_grants_by_status": statuses(db, "grants"),
            }
            # Usage columns preserve reservations for unknowns and actual usage for
            # measured terminal calls. Do not imply these are provider billing totals.
            measured = db.execute(
                "SELECT count(*), COALESCE(sum(json_extract(outcome,'$.usage.input_tokens')),0), COALESCE(sum(json_extract(outcome,'$.usage.output_tokens')),0) FROM grants WHERE unresolved=0 AND json_type(outcome,'$.usage.input_tokens')='integer' AND json_type(outcome,'$.usage.output_tokens')='integer'"
            ).fetchone()
            report["provider"]["retained_measured_usage"] = {
                "calls": measured[0],
                "input_tokens": measured[1],
                "output_tokens": measured[2],
                "billing_total": False,
            }
            report["operations"] = statuses(db, "operations")
        for item in store.list():
            if item["status"] != "ready":
                continue
            with store.db(item["id"]) as db:
                row = {
                    "adm_id": item["id"],
                    "archived": bool(db.execute("SELECT archived FROM control WHERE id=1").fetchone()[0]),
                    "storage_bytes": sum(
                        p.stat().st_size for p in store.root.glob(item["id"] + ".db*") if p.is_file()
                    ),
                    "rows": {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES},
                    "requests": statuses(db, "requests"),
                    "local_attempts": statuses(db, "attempts"),
                    "source_jobs": statuses(db, "source_jobs"),
                    "source_episodes": statuses(db, "source_episodes"),
                    "feed_runs": statuses(db, "feed_runs"),
                }
                report["instances"].append(row)
        report["collection_seconds"] = round(time.monotonic() - start, 6)
    # max_adms <= 100 and fixed label cardinality keep the export within 1 MiB.
    if len(dumps(report)) > 1_048_576:
        raise ValueError("Diagnostic export exceeded its byte envelope")
    return report
