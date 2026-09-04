"""Deterministic unit handling.

Marine sources disagree about units far more often than they disagree about
values: Open-Meteo reports wind in km/h, IMD bulletins in knots, most ocean
models in m/s.  Comparing them numerically without normalising is one of the
easiest ways to produce a confidently wrong safety answer, so all conversion
lives here and is unit-tested.
"""

from __future__ import annotations

# ---- canonical units used internally ------------------------------------
CANONICAL: dict[str, str] = {
    "wind_speed_10m": "km/h",
    "wind_gust_10m": "km/h",
    "wind_direction_10m": "deg",
    "precipitation": "mm",
    "visibility": "m",
    "cloud_cover": "%",
    "temperature_2m": "degC",
    "cape": "J/kg",
    "thunderstorm_probability": "%",
    "wave_height_significant": "m",
    "wave_period": "s",
    "wave_direction": "deg",
    "swell_height": "m",
    "swell_period": "s",
    "swell_direction": "deg",
    "sea_surface_temperature": "degC",
    "current_speed": "km/h",
    "current_direction": "deg",
    "sea_level_height_msl": "m",
    "chlorophyll_a": "mg/m^3",
    "tide_height": "m",
}

_SPEED_TO_KMH = {
    "km/h": 1.0,
    "kmh": 1.0,
    "kph": 1.0,
    "m/s": 3.6,
    "mps": 3.6,
    "kn": 1.852,
    "kt": 1.852,
    "knot": 1.852,
    "knots": 1.852,
    "mph": 1.609344,
}
_LENGTH_TO_M = {"m": 1.0, "metre": 1.0, "meters": 1.0, "cm": 0.01, "ft": 0.3048, "km": 1000.0}
_TEMP = {"degc", "c", "°c", "celsius"}


class UnitConversionError(ValueError):
    pass


def _norm(u: str) -> str:
    return u.strip().lower().replace("°", "").replace(" ", "")


def convert(value: float, frm: str, to: str) -> float:
    """Convert *value* from unit *frm* to unit *to*, exactly and explicitly."""
    if value is None:
        raise UnitConversionError("cannot convert None")
    f, t = _norm(frm), _norm(to)
    if f == t:
        return float(value)

    if f in _SPEED_TO_KMH and t in _SPEED_TO_KMH:
        return float(value) * _SPEED_TO_KMH[f] / _SPEED_TO_KMH[t]
    if f in _LENGTH_TO_M and t in _LENGTH_TO_M:
        return float(value) * _LENGTH_TO_M[f] / _LENGTH_TO_M[t]
    if f in _TEMP and t in _TEMP:
        return float(value)
    if f in ("degf", "f", "fahrenheit") and t in _TEMP:
        return (float(value) - 32.0) * 5.0 / 9.0
    if f in _TEMP and t in ("degf", "f", "fahrenheit"):
        return float(value) * 9.0 / 5.0 + 32.0
    if f in ("deg", "degrees", "°") and t in ("deg", "degrees", "°"):
        return float(value)
    if f == "%" and t == "%":
        return float(value)
    if f in ("mm", "mm/h") and t in ("mm", "mm/h"):
        return float(value)
    raise UnitConversionError(f"no conversion rule from {frm!r} to {to!r}")


def to_canonical(variable: str, value: float, unit: str) -> tuple[float, str]:
    target = CANONICAL.get(variable)
    if target is None:
        return float(value), unit
    return convert(value, unit, target), target


def kmh_to_knots(v: float) -> float:
    return convert(v, "km/h", "kn")


def beaufort(wind_kmh: float) -> int:
    """Beaufort force from wind speed in km/h (WMO scale boundaries)."""
    # Upper bound of each force, inclusive (WMO): F8 ends at 74 km/h, F9 at 88.
    bounds = [0.99, 5, 11, 19, 28, 38, 49, 61, 74, 88, 102, 117]
    for i, b in enumerate(bounds):
        if wind_kmh <= b:
            return i
    return 12


def douglas_sea_state(hs_m: float) -> int:
    """Douglas sea-state code from significant wave height in metres."""
    bounds = [0.0, 0.1, 0.5, 1.25, 2.5, 4.0, 6.0, 9.0, 14.0]
    for i, b in enumerate(bounds):
        if hs_m <= b:
            return i
    return 9
