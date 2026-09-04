"""Polygon predicates. Ray casting + segment distance, both deterministic."""

from __future__ import annotations

from app.geo.geodesy import bbox_of, point_to_segment_km
from app.schemas.geo import GeoPoint

Ring = list[list[float]]          # GeoJSON ring: [[lon, lat], ...]


def point_in_ring(p: GeoPoint, ring: Ring) -> bool:
    """Even-odd ray casting in lon/lat space.

    Adequate here because every polygon ORCA carries is regional (well away
    from the antimeridian) and rings are dense enough that planar edges do not
    materially differ from geodesics at our tolerances.
    """
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > p.lat) != (yj > p.lat):
            x_int = (xj - xi) * (p.lat - yi) / (yj - yi) + xi
            if p.lon < x_int:
                inside = not inside
        j = i
    return inside


def point_in_polygon(p: GeoPoint, polygon: list[Ring]) -> bool:
    """GeoJSON Polygon: ring 0 is the outer boundary, the rest are holes."""
    if not polygon:
        return False
    if not point_in_ring(p, polygon[0]):
        return False
    return not any(point_in_ring(p, hole) for hole in polygon[1:])


def point_in_multipolygon(p: GeoPoint, multi: list[list[Ring]]) -> bool:
    return any(point_in_polygon(p, poly) for poly in multi)


def point_in_geometry(p: GeoPoint, geometry: dict) -> bool:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon":
        return point_in_polygon(p, coords)
    if gtype == "MultiPolygon":
        return point_in_multipolygon(p, coords)
    return False


def _ring_distance_km(p: GeoPoint, ring: Ring) -> float:
    best = float("inf")
    for i in range(len(ring)):
        a = GeoPoint(lat=ring[i][1], lon=ring[i][0])
        b_raw = ring[(i + 1) % len(ring)]
        b = GeoPoint(lat=b_raw[1], lon=b_raw[0])
        best = min(best, point_to_segment_km(p, a, b))
    return best


def distance_to_geometry_km(p: GeoPoint, geometry: dict) -> float:
    """0.0 if inside, otherwise the shortest distance to the boundary."""
    if point_in_geometry(p, geometry):
        return 0.0
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    best = float("inf")
    if gtype == "Polygon":
        for ring in coords:
            best = min(best, _ring_distance_km(p, ring))
    elif gtype == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                best = min(best, _ring_distance_km(p, ring))
    elif gtype == "LineString":
        for i in range(len(coords) - 1):
            a = GeoPoint(lat=coords[i][1], lon=coords[i][0])
            b = GeoPoint(lat=coords[i + 1][1], lon=coords[i + 1][0])
            best = min(best, point_to_segment_km(p, a, b))
    elif gtype == "Point":
        from app.geo.geodesy import distance_km
        best = distance_km(p, GeoPoint(lat=coords[1], lon=coords[0]))
    return best


def ring_centroid(ring: Ring) -> GeoPoint:
    """Area-weighted centroid (shoelace); falls back to the vertex mean."""
    area = cx = cy = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(area) < 1e-12:
        return GeoPoint(lat=sum(c[1] for c in ring) / n,
                        lon=sum(c[0] for c in ring) / n)
    area *= 0.5
    return GeoPoint(lat=cy / (6 * area), lon=cx / (6 * area))


def geometry_centroid(geometry: dict) -> GeoPoint:
    gtype, coords = geometry.get("type"), geometry.get("coordinates")
    if gtype == "Point":
        return GeoPoint(lat=coords[1], lon=coords[0])
    if gtype == "Polygon":
        return ring_centroid(coords[0])
    if gtype == "MultiPolygon":
        return ring_centroid(coords[0][0])
    if gtype == "LineString":
        pts = [GeoPoint(lat=c[1], lon=c[0]) for c in coords]
        bb = bbox_of(pts)
        return GeoPoint(lat=(bb.min_lat + bb.max_lat) / 2,
                        lon=(bb.min_lon + bb.max_lon) / 2)
    raise ValueError(f"unsupported geometry type {gtype!r}")


def bbox_circle(centre: GeoPoint, radius_km: float) -> dict:
    """A closed ring approximating a circle - used for alert/geofence radii."""
    from app.geo.geodesy import destination_point
    ring = [[q.lon, q.lat] for q in
            (destination_point(centre, b * 10.0, radius_km) for b in range(36))]
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}
