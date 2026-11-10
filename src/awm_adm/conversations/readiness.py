"""Read-only, application-authored prerequisite explanations. Never grants authority."""

from ..runtime.protocol import RuntimeFault, loads


def issue(code, message, action="setup"):
    return {"code": code, "message": message, "action": action}


def connection(service, conn, purpose):
    if not conn["enabled"] or conn["status"] != "ready":
        return issue("connection_unavailable", "This connection is disabled or not ready.", "connections")
    if purpose not in conn["purposes"]:
        return issue(
            "purpose_unavailable", "Enable this connection's required purpose in Connections.", "connections"
        )
    if conn["provider"] != "recorded" and not service.learning.settings()["remote_calls_enabled"]:
        return issue(
            "remote_calls_disabled",
            "Remote AI calls are disabled. Your model remains available in Local debug.",
            "connections",
        )
    return None


def conversation(service, record):
    prefs = record.get("preferences")
    if not prefs:
        return []
    purpose = {"ask": "ask_interpretation", "teach": "task_preparation"}.get(
        prefs.get("purpose"), "clarification"
    )
    issues = []
    try:
        with service.store.db() as db:
            row = service.finance.one(db, "allowances", prefs["allowance_id"])
            allowance = loads(row["body"])
            price = loads(service.finance.one(db, "prices", allowance["price_id"])["body"])
            conn = service.learning.connection(price["connection_id"])
            blocked = connection(service, conn, purpose)
            if blocked:
                issues.append(blocked)
            if service.now() >= allowance["expires_at_ms"]:
                issues.append(
                    issue(
                        "allowance_expired",
                        "This conversation's allowance has expired. Review a new allowance to continue.",
                    )
                )
            elif row["state"] != "active":
                issues.append(
                    issue(
                        "allowance_closed",
                        "This conversation's allowance is closed. Review a new allowance to continue.",
                    )
                )
            if not service.finance.settings()["enabled"]:
                issues.append(
                    issue(
                        "spending_disabled",
                        "Installation spending is disabled. Review its limits in Connections.",
                        "connections",
                    )
                )
            if allowance["lane"] in service.finance.settings()["suspended_lanes"]:
                issues.append(
                    issue(
                        "spending_suspended",
                        "This spending lane needs owner review after a usage overrun.",
                        "connections",
                    )
                )
            try:
                service.finance.price(db, allowance["price_id"])
            except RuntimeFault:
                issues.append(
                    issue(
                        "price_unavailable",
                        "This allowance's price expired or its connection changed. Review current pricing and a new allowance.",
                        "connections",
                    )
                )
            usage = service.finance.totals(db, allowance["id"])
            counts = db.execute(
                "SELECT COALESCE(sum(g.calls),0),COALESCE(sum(g.input_tokens),0),COALESCE(sum(g.output_tokens),0) FROM grants g JOIN charges c ON c.grant_id=g.id WHERE c.allowance_id=?",
                (allowance["id"],),
            ).fetchone()
            if (
                any(
                    counts[i] >= allowance[k]
                    for i, k in enumerate(("max_calls", "max_input_tokens", "max_output_tokens"))
                )
                or usage["settled_micro_usd"] + usage["reserved_micro_usd"] >= allowance["cap_micro_usd"]
            ):
                issues.append(
                    issue(
                        "allowance_exhausted",
                        "This conversation's call, token or cost allowance is used up. Review a new allowance to continue.",
                    )
                )
            if not issues:
                try:
                    service.finance.valid(db, allowance["id"])
                except RuntimeFault:
                    issues.append(
                        issue(
                            "allowance_unavailable",
                            "This allowance cannot currently reserve work. Review spending limits in Connections.",
                            "connections",
                        )
                    )
    except RuntimeFault:
        issues.append(
            issue(
                "allowance_unavailable",
                "This conversation's provider or allowance is unavailable. Review setup before sending.",
            )
        )
    return issues


def require(service, record):
    issues = conversation(service, record)
    if issues:
        raise RuntimeFault(issues[0]["code"], " ".join(i["message"] for i in issues))
