"""E/F. Freshness classification and stale-data handling."""

from __future__ import annotations

import datetime as dt

import pytest

from app.core.clock import utcnow
from app.providers.demo_controls import DemoControls, set_demo_controls
from app.providers.imd.demo import DemoIMDProvider
from app.reasoning.freshness import annotate, classify, reference_time, worst
from app.schemas.common import Freshness, SourceStatus
from app.schemas.geo import GeoPoint
from app.schemas.marine import ProviderQuery

HOUR = 3600
POINT = GeoPoint(lat=9.9312, lon=76.2125)


def test_classification_bands():
    now = utcnow()
    fresh, _ = classify(now - dt.timedelta(minutes=30), 3 * HOUR, 6 * HOUR, now)
    aging, _ = classify(now - dt.timedelta(hours=4), 3 * HOUR, 6 * HOUR, now)
    stale, _ = classify(now - dt.timedelta(hours=9), 3 * HOUR, 6 * HOUR, now)
    assert (fresh, aging, stale) == (Freshness.FRESH, Freshness.AGING, Freshness.STALE)


def test_missing_reference_is_unavailable_not_fresh():
    assert classify(None, HOUR, HOUR)[0] is Freshness.UNAVAILABLE


def test_clock_skew_does_not_produce_negative_age():
    now = utcnow()
    verdict, age = classify(now + dt.timedelta(minutes=5), HOUR, HOUR, now)
    assert verdict is Freshness.FRESH and age == 0.0


def test_a_future_forecast_is_judged_by_its_issue_time():
    """The distinction most dashboards get wrong, asserted directly."""
    now = utcnow()
    issued_long_ago = now - dt.timedelta(hours=30)
    verdict, _ = classify(issued_long_ago, 12 * HOUR, 24 * HOUR, now)
    assert verdict is Freshness.STALE, (
        "a 30-hour-old forecast is stale even though it describes tomorrow")


async def test_stale_source_is_downgraded_to_degraded():
    set_demo_controls(DemoControls(stale_sources={"IMD"}))
    result = await DemoIMDProvider().fetch(ProviderQuery(point=POINT))
    annotate(result)
    assert result.freshness is Freshness.STALE
    assert result.status is SourceStatus.DEGRADED
    assert "older than acceptable" in (result.error or "")


async def test_reference_time_prefers_issue_time_over_retrieval_time():
    result = await DemoIMDProvider().fetch(ProviderQuery(point=POINT))
    reference = reference_time(result)
    assert reference == max(m.issued_at for m in result.measurements)
    assert reference != result.retrieved_at


def test_worst_of_picks_the_least_fresh():
    assert worst([Freshness.FRESH, Freshness.STALE, Freshness.AGING]) is Freshness.STALE
    assert worst([Freshness.FRESH, Freshness.FRESH]) is Freshness.FRESH
    assert worst([Freshness.STALE, Freshness.UNAVAILABLE]) is Freshness.UNAVAILABLE
