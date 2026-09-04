"""Issue schedules for demo providers.

Real marine products are not continuous: IMD marine bulletins go out on a fixed
cycle, INCOIS ocean-state forecasts are issued daily.  Demo mode reproduces that
rhythm so the freshness layer has something meaningful to classify - a demo
where everything is always 0 seconds old would teach us nothing and would let a
freshness bug ship.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.clock import IST, ensure_utc


def last_issue(now: datetime, ist_hours: tuple[int, ...],
               ist_minute: int = 0) -> datetime:
    """Most recent scheduled issue time at or before *now*."""
    local = ensure_utc(now).astimezone(IST)
    candidates: list[datetime] = []
    for day_offset in (0, -1):
        day = (local + timedelta(days=day_offset)).date()
        for h in ist_hours:
            candidates.append(datetime(day.year, day.month, day.day, h,
                                       ist_minute, tzinfo=IST))
    past = [c for c in candidates if c <= local]
    if not past:                       # defensive: cannot happen with a -1 day window
        past = candidates
    return max(past).astimezone(timezone.utc)


# IMD marine/coastal bulletins: morning and evening cycles, plus 3-hourly nowcast.
IMD_BULLETIN_HOURS = (6, 18)
IMD_NOWCAST_HOURS = (0, 3, 6, 9, 12, 15, 18, 21)
# INCOIS ocean state forecast: issued daily in the morning, updated midday.
INCOIS_OSF_HOURS = (8, 14)
# INCOIS PFZ advisory: issued on working days in the afternoon, valid ~24h.
INCOIS_PFZ_HOURS = (13,)
# INSAT half-hourly imagery; ocean-colour composites once daily.
MOSDAC_INSAT_MINUTES = 30
MOSDAC_OCEANCOLOUR_HOURS = (5,)
