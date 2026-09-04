"""C/D. Agent-provider contracts, normalisation, and demo-mode honesty."""

from __future__ import annotations

import datetime as dt

import pytest

from app.providers.base import NotConfiguredProvider
from app.providers.demo_controls import DemoControls, set_demo_controls
from app.providers.demo_synth import synth
from app.providers.imd.demo import DemoIMDProvider
from app.providers.imd.live import IMDLiveProvider
from app.providers.incois.demo import DemoINCOISProvider
from app.providers.incois.live import INCOISLiveProvider
from app.providers.mosdac.demo import DemoMOSDACProvider
from app.providers.mosdac.live import MOSDACLiveProvider
from app.providers.openmeteo.live import OpenMeteoMarineProvider, OpenMeteoWeatherProvider
from app.schemas.common import DataOrigin, Source, SourceStatus
from app.schemas.geo import GeoPoint
from app.schemas.marine import ProviderQuery

POINT = GeoPoint(lat=9.9312, lon=76.2125)
WHEN = dt.datetime(2026, 9, 3, 1, 30, tzinfo=dt.timezone.utc)


def q(**kw):
    return ProviderQuery(point=POINT, valid_time=WHEN, **kw)


@pytest.mark.parametrize("provider_cls", [DemoIMDProvider, DemoINCOISProvider, DemoMOSDACProvider])
async def test_demo_providers_return_the_envelope_contract(provider_cls):
    result = await provider_cls().fetch(q())
    assert result.provider_id and result.dataset
    assert result.origin is DataOrigin.DEMO
    assert result.retrieved_at is not None
    assert result.latency_ms >= 0
    for m in result.measurements:
        assert m.unit, f"{m.variable} has no unit"
        assert m.valid_time is not None


async def test_demo_values_are_in_canonical_units():
    from app.core.units import CANONICAL
    for provider_cls in (DemoIMDProvider, DemoINCOISProvider, DemoMOSDACProvider):
        result = await provider_cls().fetch(q())
        for m in result.measurements:
            expected = CANONICAL.get(m.variable)
            if expected:
                assert m.unit == expected, f"{m.variable}: {m.unit} != {expected}"


async def test_demo_output_is_deterministic():
    a = await DemoINCOISProvider().fetch(q())
    b = await DemoINCOISProvider().fetch(q())
    assert [(m.variable, m.value) for m in a.measurements] == \
           [(m.variable, m.value) for m in b.measurements]


def test_synthesis_is_physically_coherent():
    """Wave height must follow wind, not wander independently of it."""
    calm = synth(9.93, 76.21, WHEN, "calm")
    rough = synth(9.93, 76.21, WHEN, "rough")
    assert rough.wind_speed_kmh > calm.wind_speed_kmh
    assert rough.wave_height_m > calm.wave_height_m
    assert rough.wave_period_s > calm.wave_period_s
    for state in (calm, rough):
        assert state.wave_height_m >= state.swell_height_m * 0.9
        assert 0 <= state.wind_direction_deg < 360
        assert 0 <= state.cloud_cover_pct <= 100
        assert state.visibility_m > 0


def test_monsoon_makes_the_west_coast_rougher_than_winter():
    monsoon = synth(9.93, 76.21, dt.datetime(2026, 7, 15, 1, 30, tzinfo=dt.timezone.utc))
    winter = synth(9.93, 76.21, dt.datetime(2026, 1, 15, 1, 30, tzinfo=dt.timezone.utc))
    assert monsoon.wind_speed_kmh > winter.wind_speed_kmh


async def test_failure_injection_reports_unavailable_not_a_fake_reading():
    set_demo_controls(DemoControls(fail_sources={"INCOIS"}))
    result = await DemoINCOISProvider().fetch(q())
    assert result.status is SourceStatus.UNAVAILABLE
    assert result.measurements == []
    assert result.error


async def test_slow_injection_is_actually_slow():
    set_demo_controls(DemoControls(slow_sources={"IMD": 150}))
    result = await DemoIMDProvider().fetch(q())
    assert result.latency_ms >= 140


async def test_cloud_blocks_ocean_colour_rather_than_inventing_it():
    """The honest satellite behaviour: no retrieval under cloud, not a guess."""
    set_demo_controls(DemoControls(scenario="rough"))     # heavy monsoon cloud
    result = await DemoMOSDACProvider().fetch(q())
    chl = next(m for m in result.measurements if m.variable == "chlorophyll_a")
    assert chl.value is None
    assert chl.quality.value == "MISSING"
    assert "cloud" in (chl.transformation or "").lower()


async def test_pfz_is_only_produced_when_asked_for():
    without = await DemoINCOISProvider().fetch(q())
    assert without.pfz == []
    with_pfz = await DemoINCOISProvider().fetch(q(extras={"want_pfz": True}))
    assert len(with_pfz.pfz) >= 1
    for advisory in with_pfz.pfz:
        assert advisory.valid_to > advisory.valid_from
        assert advisory.landing_centre
        assert advisory.basis


# ---- live providers ---------------------------------------------------------
@pytest.mark.parametrize("provider_cls", [
    IMDLiveProvider, INCOISLiveProvider, MOSDACLiveProvider,
    OpenMeteoWeatherProvider, OpenMeteoMarineProvider])
def test_live_providers_declare_their_verification_status(provider_cls):
    """No provider may claim verified access without saying how it was verified."""
    descriptor = provider_cls().describe()
    assert descriptor.access_mechanism
    assert descriptor.attribution
    assert descriptor.verification_note or descriptor.verified


async def test_unconfigured_live_providers_report_not_configured():
    """An unverified source degrades to 'absent', never to 'made up'."""
    for provider_cls in (IMDLiveProvider, INCOISLiveProvider, MOSDACLiveProvider):
        result = await provider_cls().fetch(q())
        assert result.status is SourceStatus.NOT_CONFIGURED
        assert result.measurements == []
        assert result.error


async def test_not_configured_wrapper_keeps_the_source_visible():
    wrapped = NotConfiguredProvider(IMDLiveProvider(), "disabled in this deployment")
    result = await wrapped.fetch(q())
    assert result.source is Source.IMD
    assert result.status is SourceStatus.NOT_CONFIGURED


def test_openmeteo_variable_map_only_uses_documented_names():
    """Guards against drift into invented API field names."""
    documented_forecast = {
        "wind_speed_10m", "wind_gusts_10m", "wind_direction_10m", "precipitation",
        "visibility", "cloud_cover", "temperature_2m", "cape"}
    documented_marine = {
        "wave_height", "wave_direction", "wave_period", "swell_wave_height",
        "swell_wave_period", "swell_wave_direction", "sea_surface_temperature",
        "ocean_current_velocity", "ocean_current_direction"}
    from app.providers.openmeteo.live import FORECAST_MAP, MARINE_MAP
    assert set(FORECAST_MAP.values()) <= documented_forecast
    assert set(MARINE_MAP.values()) <= documented_marine


def test_provider_capabilities_declare_freshness_policy():
    for provider_cls in (DemoIMDProvider, DemoINCOISProvider, DemoMOSDACProvider,
                         OpenMeteoWeatherProvider, OpenMeteoMarineProvider):
        capability = provider_cls().capability
        assert capability.update_frequency_seconds > 0
        assert capability.max_acceptable_age_seconds >= capability.update_frequency_seconds
        assert capability.cache_ttl_seconds > 0


# ---- OpenWeatherMap: the free stand-in for IMD ------------------------------
async def test_openweathermap_reports_not_configured_without_a_key(monkeypatch):
    """No key means absent, never invented."""
    from app.providers.openweathermap.live import OpenWeatherMapProvider
    from app.config.settings import reset_settings_cache
    monkeypatch.delenv("ORCA_OPENWEATHERMAP_API_KEY", raising=False)
    reset_settings_cache()
    result = await OpenWeatherMapProvider().fetch(q())
    assert result.status is SourceStatus.NOT_CONFIGURED
    assert result.measurements == []
    assert "openweathermap.org" in result.error


def test_openweathermap_declares_its_free_tier_honestly():
    from app.providers.openweathermap.live import OpenWeatherMapProvider
    descriptor = OpenWeatherMapProvider().describe()
    assert "no credit card" in descriptor.access_mechanism
    assert descriptor.attribution
    assert descriptor.source is Source.OPEN_WEATHER_MAP


def test_openweathermap_normalises_a_recorded_payload():
    """Unit conversion is where a free source quietly becomes wrong: OWM reports
    wind in m/s under units=metric, and ORCA's canonical unit is km/h."""
    from datetime import datetime, timezone
    from app.providers.openweathermap.live import OpenWeatherMapProvider
    from app.schemas.common import VariableKind

    provider = OpenWeatherMapProvider()
    valid = datetime(2026, 9, 3, 1, 30, tzinfo=timezone.utc)
    block = {
        "main": {"temp": 28.4},
        "wind": {"speed": 9.7, "deg": 252, "gust": 14.4},
        "clouds": {"all": 88},
        "visibility": 9000,
        "rain": {"3h": 7.2},
        "weather": [{"id": 201, "description": "thunderstorm with rain"}],
    }
    measurements = provider._measurements(
        block, q(), valid, "owm_forecast_3h", VariableKind.FORECAST)
    values = {m.variable: m for m in measurements}

    assert values["wind_speed_10m"].unit == "km/h"
    assert values["wind_speed_10m"].value == pytest.approx(34.92, abs=0.01)   # 9.7 m/s
    assert values["wind_gust_10m"].value == pytest.approx(51.84, abs=0.01)
    assert values["visibility"].unit == "m" and values["visibility"].value == 9000
    assert values["temperature_2m"].value == pytest.approx(28.4)
    assert "m/s -> km/h" in values["wind_speed_10m"].transformation

    # A thunderstorm code becomes an advisory, not a silently folded number.
    advisories = provider._advisories(block, valid, "owm_forecast_3h")
    assert advisories and advisories[0].category == "thunderstorm"


def test_openweathermap_omits_absent_fields_rather_than_zeroing_them():
    """OWM drops `gust` when calm and `rain` when dry. Emitting 0 would be
    inventing an observation."""
    from datetime import datetime, timezone
    from app.providers.openweathermap.live import OpenWeatherMapProvider
    from app.schemas.common import VariableKind

    provider = OpenWeatherMapProvider()
    block = {"main": {"temp": 27.0}, "wind": {"speed": 2.0, "deg": 90},
             "clouds": {"all": 10}, "weather": []}
    measurements = provider._measurements(
        block, q(), datetime(2026, 9, 3, tzinfo=timezone.utc),
        "owm_current", VariableKind.OBSERVED)
    emitted = {m.variable for m in measurements}
    assert "wind_gust_10m" not in emitted
    assert "precipitation" not in emitted
    assert "wind_speed_10m" in emitted
