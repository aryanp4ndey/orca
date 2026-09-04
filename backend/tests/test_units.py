"""D. Provider normalisation - unit conversion is where silent errors live."""

from __future__ import annotations

import pytest

from app.core.units import (
    UnitConversionError,
    beaufort,
    douglas_sea_state,
    kmh_to_knots,
    to_canonical,
)


@pytest.mark.parametrize("value,frm,to,expected", [
    (10, "m/s", "km/h", 36.0),
    (36, "km/h", "m/s", 10.0),
    (1, "kn", "km/h", 1.852),
    (20, "kn", "km/h", 37.04),
    (100, "cm", "m", 1.0),
    (1, "ft", "m", 0.3048),
])
def test_conversions(value, frm, to, expected):
    from app.core.units import convert
    assert convert(value, frm, to) == pytest.approx(expected, rel=1e-6)


def test_round_trip_is_lossless():
    from app.core.units import convert
    for v in (0.5, 7.3, 55.9):
        assert convert(convert(v, "km/h", "kn"), "kn", "km/h") == pytest.approx(v)


def test_to_canonical_uses_the_variable_table():
    value, unit = to_canonical("wind_speed_10m", 10.0, "m/s")
    assert unit == "km/h" and value == pytest.approx(36.0)


def test_unknown_unit_raises_rather_than_guessing():
    from app.core.units import convert
    with pytest.raises(UnitConversionError):
        convert(1.0, "furlongs", "km/h")


def test_unknown_variable_passes_through_unchanged():
    value, unit = to_canonical("not_a_variable", 5.0, "widgets")
    assert (value, unit) == (5.0, "widgets")


def test_knots_conversion_matches_definition():
    assert kmh_to_knots(1.852) == pytest.approx(1.0)


@pytest.mark.parametrize("kmh,force", [(0, 0), (10, 2), (25, 4), (45, 6), (74, 8), (75, 9), (130, 12)])
def test_beaufort_scale_boundaries(kmh, force):
    assert beaufort(kmh) == force


@pytest.mark.parametrize("hs,code", [(0.0, 0), (0.3, 2), (1.0, 3), (2.0, 4), (3.5, 5), (12.0, 8)])
def test_douglas_sea_state(hs, code):
    assert douglas_sea_state(hs) == code
