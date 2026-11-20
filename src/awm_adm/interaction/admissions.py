"""Bounded typed views of local admission receipts, never inferred from provider prose."""

from typing import Literal

from pydantic import Field

from ..contracts import ClosedModel
from ..runtime.protocol import loads


class AdmissionView(ClosedModel):
    objective_id: str
    receipt_id: str
    receipt_sequence: int
    status: str
    classification: Literal["accepted", "preservation_conflict", "checked_violation", "unresolved"]
    mode: Literal["backward", "forward"] | None = None
    base_revision: str | None = None
    decision_revision: str | None = None
    accepted_revision: str | None = None
    decision_context: dict | None = None
    accepted_context: dict | None = None
    diagnostic: dict | None = None
    effects: dict | None = None
    evidence: list[str] = Field(default_factory=list)


def admissions(store, key, execution):
    views = []
    with store.db(key) as db:
        for step in execution.get("steps", []):
            episode = step.get("episode_id")
            base = None
            if episode:
                ep = db.execute("SELECT data FROM episodes WHERE id=?", (episode,)).fetchone()
                base = loads(ep[0]).get("base_revision") if ep else None
                rows = db.execute(
                    "SELECT * FROM learning_receipts WHERE episode=? ORDER BY seq", (episode,)
                ).fetchall()
            elif step.get("feed_id"):
                rows = db.execute(
                    "SELECT DISTINCT r.* FROM learning_receipts r JOIN source_episodes s ON s.id=r.id "
                    "JOIN feed_runs f ON f.id=json_extract(s.data,'$.feed_run') "
                    "JOIN feed_items i ON i.run=f.id WHERE i.feed=? ORDER BY r.seq",
                    (step["feed_id"],),
                ).fetchall()
            else:
                continue
            for row in rows:
                data = loads(row["data"])
                decision = data.get("decision") or {}
                report = decision.get("report") or {}
                error = report.get("error") or {}
                context = error.get("context") or {}
                classification = "unresolved"
                if row["status"] == "accepted":
                    classification = "accepted"
                elif (
                    decision.get("mode") == "backward"
                    and context.get("mode") == "backward"
                    and error.get("code") == "admission_rejected"
                ):
                    classification = "preservation_conflict"
                elif error.get("code") == "conformance_failed" or (
                    error.get("code") == "admission_rejected"
                    and all(k in context for k in ("evidence", "expression", "expected", "actual"))
                ):
                    classification = "checked_violation"
                views.append(
                    AdmissionView(
                        objective_id=step["id"],
                        receipt_id=row["id"],
                        receipt_sequence=row["seq"],
                        status=row["status"],
                        classification=classification,
                        mode=decision.get("mode"),
                        base_revision=base,
                        decision_revision=data.get("decision_revision"),
                        accepted_revision=data.get("accepted_revision"),
                        decision_context=data.get("decision_context"),
                        accepted_context=data.get("accepted_context"),
                        diagnostic=error or data.get("diagnostic"),
                        effects=data.get("effects") if classification == "accepted" else None,
                        evidence=report.get("evidence", []) if classification == "accepted" else [],
                    ).model_dump()
                )
    return sorted(views, key=lambda v: v["receipt_sequence"])
