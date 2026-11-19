"""Shared representation guidance and application-owned civil-time resolution."""

import os
import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MEANING = """Separate meaning from representation. Resolve references from the supplied context,
preserve identity, units, scope and precision, then encode the supported typed fields.
A formatting requirement is not missing domain knowledge. Never fabricate a fact,
boundary or finer precision to satisfy a format. Clarify genuinely missing meaning;
report unsupported representation when the requested meaning cannot be preserved.
For temporal meaning use the user's explicit relevant timezone, otherwise
temporal_context.system_timezone. This supplied default is not an unsupported
assumption and does not require confirmation. Preserve explicit source timezones.
UTC wire encoding does not mean that an unspecified user timezone is UTC.
"""

INSTANT = (
    "Canonical UTC instant: YYYY-MM-DDTHH:MM:SSZ, with seconds and literal Z; "
    "a bare date is not this field's representation. Convert the intended instant "
    "from its explicit timezone or the supplied system timezone, preserving meaning."
)
SCOPE = (
    "A point uses effective_from and effective_to null. An interval uses inclusive "
    "effective_from and exclusive effective_to; projection intervals must be bounded. "
    "Unknown source time uses kind unknown with both bounds null. Granularity describes "
    "the UTC carrier: day requires midnight UTC boundaries; year also requires January 1. "
    "Use second when converted boundaries are not UTC day/year aligned; this carrier "
    "encoding does not justify claiming finer evidence precision. Preserve the full "
    "supplied period, never replace it with an arbitrary instant."
)


def timezone_name(value):
    if not isinstance(value, str) or len(value) > 128 or not value or value.startswith(("/", ".")):
        raise ValueError("Expected an IANA timezone")
    try:
        ZoneInfo(value)  # Never silently fall back after an explicit setting.
    except ZoneInfoNotFoundError as error:
        raise ValueError("Unknown IANA timezone") from error
    return value


def system_timezone():
    """Resolve the service system default, including the Docker host setup handoff."""
    if value := os.environ.get("TZ"):
        return timezone_name(value.removeprefix(":"))
    if path := os.environ.get("AWM_ADM_TIMEZONE_FILE"):
        return timezone_name(Path(path).read_text().strip())
    path = Path("/etc/localtime").resolve().as_posix()
    if "/zoneinfo/" in path:
        return timezone_name(path.split("/zoneinfo/", 1)[1])
    if Path("/etc/timezone").is_file():
        return timezone_name(Path("/etc/timezone").read_text().strip())
    # UTC is a real system default only if the system reports it; don't freeze a DST offset.
    if datetime.now().astimezone().tzname() in {"UTC", "GMT"}:
        return "UTC"
    raise ValueError("System timezone is unavailable; configure TZ with an IANA timezone")


def context():
    return {"system_timezone": system_timezone()}


def civil_instant(value, zone):
    """Reject skipped/repeated wall times instead of choosing a DST fold silently."""
    tz = ZoneInfo(timezone_name(zone))
    candidates = {
        value.replace(tzinfo=tz, fold=fold).astimezone(UTC)
        for fold in (0, 1)
        if value.replace(tzinfo=tz, fold=fold).astimezone(UTC).astimezone(tz).replace(tzinfo=None) == value
    }
    if len(candidates) != 1:
        raise ValueError("The local time is skipped or repeated in this timezone; specify an offset")
    return candidates.pop().isoformat(timespec="seconds").replace("+00:00", "Z")


def day_bounds(value, zone):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Expected a calendar date YYYY-MM-DD")
    day = date.fromisoformat(value)
    try:
        return (
            civil_instant(datetime.combine(day, time()), zone),
            civil_instant(datetime.combine(day + timedelta(days=1), time()), zone),
        )
    except OverflowError as error:
        raise ValueError("The civil day exceeds the supported datetime range") from error
