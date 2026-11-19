"""Read-only, time-filtered activity across chat and structured API operations."""

import base64
import json

from ..conversations.presentation import outcome, readable
from ..learning.service import fault, fingerprint
from ..runtime.protocol import loads

TABLES = (
    "chat_work",
    "teaching_tasks",
    "requests",
    "episodes",
    "source_jobs",
    "source_episodes",
    "feed_runs",
)


def cursor(value):
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode()


def history(runtime, key, *, start=None, end=None, after=None, limit=20, kind=None, origin=None):
    store = runtime.store
    store.info(key)
    if start is not None and end is not None and start >= end:
        fault("invalid_input", "The end of the time range must follow its start")
    scope = fingerprint({"adm": key, "start": start, "end": end, "kind": kind, "origin": origin})
    prior = None
    if after:
        try:
            prior = json.loads(base64.urlsafe_b64decode(after))
            if prior["scope"] != scope or set(prior["watermarks"]) != set(TABLES):
                raise ValueError()
            if any(type(v) is not int or v < 0 for v in prior["watermarks"].values()):
                raise ValueError()
            last = prior["last"]
            if (
                not isinstance(last, list)
                or len(last) != 3
                or type(last[0]) is not int
                or any(not isinstance(v, str) for v in last[1:])
            ):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            fault("invalid_input", "This history cursor does not match the selected time range")
    with store.db(key) as db:
        db.execute("BEGIN")
        marks = (
            prior["watermarks"]
            if prior
            else {
                table: db.execute(f"SELECT COALESCE(max(rowid),0) FROM {table}").fetchone()[0]
                for table in TABLES
            }
        )
        records = []
        # Project only labels/links rather than loading source bodies or provider responses.
        queries = {
            "chat_work": """SELECT w.id, json_extract(w.body,'$.flow') kind,
                json_extract(w.body,'$.created_at_ms') created, w.status,
                substr(json_extract(w.body,'$.text'),1,1000) title,
                json_extract(w.body,'$.request_id') request_id,
                json_extract(w.body,'$.context.revision_id') revision_id,
                coalesce(d.origin,'legacy_chat') origin
                FROM chat_work w LEFT JOIN direct_interactions d ON d.id=w.id
                WHERE w.seq<=? AND json_extract(w.body,'$.flow')='ask'""",
            "teaching_tasks": """SELECT t.id, 'teach' kind,
                json_extract(t.body,'$.created_at_ms') created, t.status,
                substr(json_extract(t.body,'$.objective'),1,1000) title, NULL request_id,
                json_extract(t.body,'$.context.revision_id') revision_id,
                coalesce(d.origin,'legacy_chat') origin
                FROM teaching_tasks t LEFT JOIN direct_interactions d ON d.id=t.id WHERE t.seq<=?""",
            "requests": """SELECT r.id, 'request' kind, cast(r.created*1000 AS INTEGER) created, r.status,
                json_extract(r.envelope,'$.query.op') title, r.id request_id, r.revision revision_id, 'api' origin
                FROM requests r WHERE r.seq<=? AND NOT EXISTS
                (SELECT 1 FROM chat_work w WHERE json_extract(w.body,'$.request_id')=r.id)
                AND NOT EXISTS (SELECT 1 FROM teaching_tasks t WHERE json_extract(t.body,'$.execution.followup.request_id')=r.id)""",
            "episodes": """SELECT id, 'learning' kind, cast(json_extract(data,'$.created')*1000 AS INTEGER) created,
                json_extract(data,'$.status') status, substr(json_extract(data,'$.body.task.description'),1,1000) title,
                NULL request_id, json_extract(data,'$.base_revision') revision_id, 'api' origin
                FROM episodes WHERE seq<=? AND json_extract(data,'$.parent_task') IS NULL""",
            "source_jobs": """SELECT id, 'extraction' kind, cast(json_extract(data,'$.created')*1000 AS INTEGER) created,
                status, json_extract(data,'$.body.item_id') title, NULL request_id,
                json_extract(data,'$.body.expected_revision') revision_id, 'api' origin
                FROM source_jobs WHERE seq<=? AND json_extract(data,'$.feed_run') IS NULL""",
            "source_episodes": """SELECT id, 'source_admission' kind, cast(json_extract(data,'$.created')*1000 AS INTEGER) created,
                status, 'Supplied facts' title, NULL request_id, json_extract(data,'$.body.expected_revision') revision_id,
                'api' origin FROM source_episodes WHERE seq<=? AND json_extract(data,'$.feed_run') IS NULL""",
        }
        queries["feed_runs"] = """SELECT r.id, 'source_intake' kind,
            cast(json_extract(r.data,'$.created')*1000 AS INTEGER) created, r.status,
            coalesce(v.item,'Incoming source material') title, NULL request_id,
            NULL revision_id, 'api' origin FROM feed_runs r
            LEFT JOIN source_versions v ON v.id=json_extract(r.data,'$.source')
            WHERE r.rowid<=? AND json_extract(r.data,'$.parent_task') IS NULL"""
        for table, sql in queries.items():
            records.extend(dict(r) for r in db.execute(sql, (marks[table],)))
    records = [
        r for r in records if (not kind or r["kind"] == kind) and (not origin or r["origin"] == origin)
    ]
    undated = sum(r["created"] is None for r in records)
    ordered = sorted(records, key=lambda r: (r["created"] or 0, r["kind"], r["id"]), reverse=True)
    selected = []
    for row in ordered:
        order = [row["created"] or 0, row["kind"], row["id"]]
        if prior and order >= prior["last"]:
            continue
        if (start is not None or end is not None) and row["created"] is None:
            continue
        if start is not None and row["created"] < start:
            continue
        if end is not None and row["created"] >= end:
            continue
        selected.append(row)
        if len(selected) > limit:
            break
    items = []
    for row in selected[:limit]:
        item = {
            **row,
            "created_at_ms": row["created"],
            "summary": None,
            "resource_id": row["id"],
            "id": row["kind"] + ":" + row["id"],
        }
        item.pop("created", None)
        if row["kind"] in {"ask", "teach"}:
            with store.db(key) as db:
                direct = db.execute("SELECT 1 FROM direct_interactions WHERE id=?", (row["id"],)).fetchone()
                table, field = ("chat_work", "body") if row["kind"] == "ask" else ("teaching_tasks", "body")
                original = loads(
                    db.execute(f"SELECT {field} FROM {table} WHERE id=?", (row["id"],)).fetchone()[0]
                )
            if direct:
                view = runtime.interactions.get(key, row["id"])
                item.update(
                    status=view["status"],
                    summary=view["outcome_text"] or view["reply"],
                    request_id=view["request_id"],
                    result_id=view["result_id"],
                )
            else:
                item["summary"] = original.get("summary") or "Retained conversation activity"
            item["binding"] = original.get("context")
        if row["request_id"]:
            request = store.request(key, row["request_id"])
            item.update(
                summary=readable(outcome(request)),
                binding=request["pinned_context"],
                result_id=(request.get("result") or {}).get("result_id"),
            )
        items.append(item)
    next_cursor = None
    if len(selected) > limit:
        last = items[-1]
        next_cursor = cursor(
            {
                "scope": scope,
                "watermarks": marks,
                "last": [last["created_at_ms"] or 0, last["kind"], last["resource_id"]],
            }
        )
    return {"items": items, "next_cursor": next_cursor, "undated_legacy_items": undated}
