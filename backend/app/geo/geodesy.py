"""WGS84 geodesy - pure Python, deterministic, no I/O.

Why not Shapely/PostGIS in the prototype?
  * every function here is closed-form and exact enough for marine decision
    support (Vincenty inverse converges to ~1 mm on the ellipsoid);
  * it runs in microseconds with no database round-trip, which matters because
    latency on a coastal network is the problem we were told to solve;
  * it has no native dependency, so ``git clone && python -m app`` works.

``app/geo/engine.py`` defines the seam.  When the boundary datasets get big
enough that an R-tree/PostGIS actually wins, that implementation swaps in and
nothing above it changes.

Nothing in this module is ever produced by a language model.  The LLM may decide
*which* spatial question to ask; these functions decide the answer.
"""

from __future__ import annotations

import math

from app.schemas.geo import BBox, GeoPoint

# WGS84 ellipsoid
A = 6378137.0
F = 1 / 298.257223563
B = A * (1 - F)
EARTH_MEAN_RADIUS_KM = 6371.0088
NM_IN_KM = 1.852


def haversine_km(p1: GeoPoint, p2: GeoPoint) -> float:
    """Great-circle distance. Fast path; ~0.3% error vs the ellipsoid."""
    phi1, phi2 = math.radians(p1.lat), math.radians(p2.lat)
    dphi = phi2 - phi1
    dlam = math.radians(p2.lon - p1.lon)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return 2 * EARTH_MEAN_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def vincenty_km(p1: GeoPoint, p2: GeoPoint, max_iter: int = 200,
                tol: float = 1e-12) -> float:
    """Ellipsoidal (Vincenty inverse) distance in km.

    Falls back to haversine for the near-antipodal case where Vincenty is known
    not to converge - we would rather return a slightly less precise number than
    hang or raise inside a safety path.
    """
    lat1, lat2 = math.radians(p1.lat), math.radians(p2.lat)
    L = math.radians(p2.lon - p1.lon)
    U1, U2 = math.atan((1 - F) * math.tan(lat1)), math.atan((1 - F) * math.tan(lat2))
    sinU1, cosU1 = math.sin(U1), math.cos(U1)
    sinU2, cosU2 = math.sin(U2), math.cos(U2)

    lam = L
    for _ in range(max_iter):
        sin_lam, cos_lam = math.sin(lam), math.cos(lam)
        sin_sigma = math.sqrt((cosU2 * sin_lam) ** 2
                              + (cosU1 * sinU2 - sinU1 * cosU2 * cos_lam) ** 2)
        if sin_sigma == 0:
            return 0.0
        cos_sigma = sinU1 * sinU2 + cosU1 * cosU2 * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cosU1 * cosU2 * sin_lam / sin_sigma
        cos_sq_alpha = 1 - sin_alpha ** 2
        cos2sigma_m = (cos_sigma - 2 * sinU1 * sinU2 / cos_sq_alpha
                       if cos_sq_alpha != 0 else 0.0)
        C = F / 16 * cos_sq_alpha * (4 + F * (4 - 3 * cos_sq_alpha))
        lam_prev = lam
        lam = L + (1 - C) * F * sin_alpha * (
            sigma + C * sin_sigma * (cos2sigma_m + C * cos_sigma
                                     * (-1 + 2 * cos2sigma_m ** 2)))
        if abs(lam - lam_prev) < tol:
            break
    else:
        return haversine_km(p1, p2)

    u_sq = cos_sq_alpha * (A ** 2 - B ** 2) / (B ** 2)
    Acoef = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq)))
    Bcoef = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))
    delta_sigma = Bcoef * sin_sigma * (
        cos2sigma_m + Bcoef / 4 * (
            cos_sigma * (-1 + 2 * cos2sigma_m ** 2)
            - Bcoef / 6 * cos2sigma_m * (-3 + 4 * sin_sigma ** 2)
            * (-3 + 4 * cos2sigma_m ** 2)))
    return (B * Acoef * (sigma - delta_sigma)) / 1000.0


def distance_km(p1: GeoPoint, p2: GeoPoint, precise: bool = False) -> float:
    return vincenty_km(p1, p2) if precise else haversine_km(p1, p2)


def distance_nm(p1: GeoPoint, p2: GeoPoint, precise: bool = False) -> float:
    return distance_km(p1, p2, precise) / NM_IN_KM


def initial_bearing_deg(p1: GeoPoint, p2: GeoPoint) -> float:
    phi1, phi2 = math.radians(p1.lat), math.radians(p2.lat)
    dlam = math.radians(p2.lon - p1.lon)
    y = math.sin(dlam) * math.cos(phi2)
    x = (math.cos(phi1) * math.sin(phi2)
         - math.sin(phi1) * math.cos(phi2) * math.cos(dlam))
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def destination_point(p: GeoPoint, bearing_deg: float, distance_km_: float) -> GeoPoint:
    """Point reached by travelling *distance_km_* from *p* on *bearing_deg*."""
    delta = distance_km_ / EARTH_MEAN_RADIUS_KM
    theta = math.radians(bearing_deg)
    phi1, lam1 = math.radians(p.lat), math.radians(p.lon)
    phi2 = math.asin(math.sin(phi1) * math.cos(delta)
                     + math.cos(phi1) * math.sin(delta) * math.cos(theta))
    lam2 = lam1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2))
    return GeoPoint(lat=math.degrees(phi2),
                    lon=((math.degrees(lam2) + 540) % 360) - 180)


def midpoint(p1: GeoPoint, p2: GeoPoint) -> GeoPoint:
    return destination_point(p1, initial_bearing_deg(p1, p2),
                             distance_km(p1, p2) / 2.0)


def interpolate(p1: GeoPoint, p2: GeoPoint, fraction: float) -> GeoPoint:
    """Point a given fraction along the great circle from p1 to p2."""
    fraction = max(0.0, min(1.0, fraction))
    return destination_point(p1, initial_bearing_deg(p1, p2),
                             distance_km(p1, p2) * fraction)


def densify(p1: GeoPoint, p2: GeoPoint, n: int) -> list[GeoPoint]:
    """*n* evenly spaced points inclusive of both ends (n >= 2)."""
    n = max(2, n)
    return [interpolate(p1, p2, i / (n - 1)) for i in range(n)]


# --- local planar helpers (accurate for the few-hundred-km scale we use) ----

def _local_xy(origin: GeoPoint, p: GeoPoint) -> tuple[float, float]:
    """Equirectangular projection in km around *origin*."""
    k = math.cos(math.radians(origin.lat))
    return ((p.lon - origin.lon) * 111.320 * k, (p.lat - origin.lat) * 110.574)


def point_to_segment_km(p: GeoPoint, a: GeoPoint, b: GeoPoint) -> float:
    """Shortest distance from *p* to segment *a-b*, in km."""
    ax, ay = _local_xy(p, a)
    bx, by = _local_xy(p, b)
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(ax, ay)
    t = -(ax * dx + ay * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(cx, cy)


def cross_track_km(p: GeoPoint, a: GeoPoint, b: GeoPoint) -> float:
    """Signed distance from *p* to the great circle through *a* and *b*."""
    d13 = distance_km(a, p) / EARTH_MEAN_RADIUS_KM
    t13 = math.radians(initial_bearing_deg(a, p))
    t12 = math.radians(initial_bearing_deg(a, b))
    return math.asin(math.sin(d13) * math.sin(t13 - t12)) * EARTH_MEAN_RADIUS_KM


def bbox_of(points: list[GeoPoint], pad_km: float = 0.0) -> BBox:
    lats = [p.lat for p in points]
    lons = [p.lon for p in points]
    pad_lat = pad_km / 110.574
    mean_lat = sum(lats) / len(lats)
    pad_lon = pad_km / (111.320 * max(0.05, math.cos(math.radians(mean_lat))))
    return BBox(min_lat=min(lats) - pad_lat, min_lon=min(lons) - pad_lon,
                max_lat=max(lats) + pad_lat, max_lon=max(lons) + pad_lon)


def compass_point(bearing_deg: float) -> str:
    names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return names[int((bearing_deg % 360) / 22.5 + 0.5) % 16]
