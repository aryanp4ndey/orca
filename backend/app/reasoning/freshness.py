"""Freshness classification.

The distinction that matters, and that most dashboards get wrong: a forecast for
07:00 tomorrow is not "fresh" because 07:00 tomorrow is in the future.  It is
fresh or stale according to **when the issuing centre produced it**.  A 30-hour
old forecast for tomorrow morning is stale no matter how future-dated its valid
time is.

So freshness is measured against ``issued_at`` where a source gives one, falling
back to ``retrieved_at``, and compared with that provider's own declared update
cycle:

    age <= update_frequency          -> FRESH
    age <= max_acceptable_age        -> AGING
    age >  max_acceptable_age        -> STALE
    nothing usable                   -> UNAVAILABLE
"""

from __future__ import annotations

from datetime import datetime

from app.core.clock import age_seconds, utcnow
from app.schemas.common import Freshness, SourceStatus
from app.schemas.marine import ProviderResult

# How much of the acceptable age budget a value may burn before we call it AGING.
AGING_FRACTION = 1.0


def classify(reference: datetime | None, update_frequency_seconds: int,
             max_acceptable_age_seconds: int,
             now: datetime | None = None) -> tuple[Freshness, float]:
    if reference is None:
        return Freshness.UNAVAILABLE, float("inf")
    age = age_seconds(reference, now or utcnow())
    if age < 0:                      # clock skew - treat as just issued
        age = 0.0
    if age <= update_frequency_seconds:
        return Freshness.FRESH, age
    if age <= max_acceptable_age_seconds * AGING_FRACTION:
        return Freshness.AGING, age
    return Freshness.STALE, age


def reference_time(result: ProviderResult) -> datetime | None:
    """The timestamp freshness should be measured from, for a whole result."""
    issued = [m.issued_at for m in result.measurements if m.issued_at]
    if issued:
        return max(issued)
    if result.advisories:
        adv = [a.issued_at for a in result.advisories if a.issued_at]
        if adv:
            return max(adv)
    return result.retrieved_at


def annotate(result: ProviderResult, now: datetime | None = None) -> ProviderResult:
    """Attach a freshness verdict to a provider result, in place."""
    if not result.ok or (not result.measurements and not result.advisories
                         and not result.pfz):
        result.freshness = Freshness.UNAVAILABLE
        return result
    fresh, _age = classify(
        reference_time(result),
        result.update_frequency_seconds or 3600,
        result.max_acceptable_age_seconds or 21600,
        now,
    )
    result.freshness = fresh
    if fresh is Freshness.STALE and result.status is SourceStatus.OK:
        result.status = SourceStatus.DEGRADED
        result.error = (result.error or "") + \
            ("; " if result.error else "") + "data older than acceptable age"
    return result


def worst(freshnesses: list[Freshness]) -> Freshness:
    order = [Freshness.FRESH, Freshness.AGING, Freshness.STALE, Freshness.UNAVAILABLE]
    out = Freshness.FRESH
    for f in freshnesses:
        if order.index(f) > order.index(out):
            out = f
    return out
