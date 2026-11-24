"""Bounded, safe source failure descriptions; no provider exception text."""

MESSAGES = {
    "empty_extraction": "Extraction returned no claims and supplied no explanation; no facts were saved.",
    "provider_timeout": "Source extraction timed out; provider usage may be unknown. It was not retried.",
    "queue_timeout": "Source extraction exceeded its queue-wait limit before dispatch; no provider call was made.",
    "needs_specification": "Source extraction needs a usable specification; no facts were saved.",
    "needs_evidence_or_coverage": "Extracted claims lack supported evidence or catalog coverage.",
}


def outcome(job):
    code = job.get("error") or job["status"]
    if job["status"] == "needs_specification" and (job.get("result") or {}).get("claims") == []:
        code = "empty_extraction"
    return {
        "stage": "source_extraction",
        "code": code,
        "message": MESSAGES.get(code, "Source processing did not complete (" + code + ")."),
        "job_id": job["id"],
        "grant_id": job.get("grant_id"),
    }
