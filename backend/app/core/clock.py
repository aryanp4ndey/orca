"""Single source of time.

Every timestamp in ORCA is timezone-aware UTC.  Tests and the demo mode need a
controllable clock so that fixture freshness is reproducible, so nothing in the
codebase calls ``datetime.now()`` directly - it calls :func:`utcnow`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

_frozen: datetime | None = None


def utcnow() -> datetime:
    return _frozen if _frozen is not None else datetime.now(timezone.utc)


def freeze(at: datetime) -> None:
    """Freeze the clock (tests / reproducible benchmarks only)."""
    global _frozen
    _frozen = at.astimezone(timezone.utc)


def unfreeze() -> None:
    global _frozen
    _frozen = None


def to_ist(dt: datetime) -> datetime:
    return dt.astimezone(IST)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def age_seconds(then: datetime, now: datetime | None = None) -> float:
    return (ensure_utc(now or utcnow()) - ensure_utc(then)).total_seconds()


def iso(dt: datetime | None) -> str | None:
    return None if dt is None else ensure_utc(dt).isoformat().replace("+00:00", "Z")
