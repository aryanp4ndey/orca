"""I. Geospatial calculations - deterministic, and checked against known values."""

from __future__ import annotations

import pytest

from app.geo.gazetteer import get_gazetteer
from app.geo.geodesy import (
    compass_point,
    densify,
    destination_point,
    distance_km,
    haversine_km,
    initial_bearing_deg,
    point_to_segment_km,
    vincenty_km,
)
from app.geo.layers import get_baseline, layer_catalogue, maritime_band, zones_near
from app.geo.polygons import (
    distance_to_geometry_km,
    point_in_geometry,
    point_in_polygon,
    ring_centroid,
)
from app.schemas.geo import GeoPoint

KOCHI = GeoPoint(lat=9.9312, lon=76.2673)
CHENNAI = GeoPoint(lat=13.0827, lon=80.2707)


def test_zero_distance():
    assert distance_km(KOCHI, KOCHI) == pytest.approx(0.0, abs=1e-9)


def test_one_degree_of_latitude_is_about_111km():
    a = GeoPoint(lat=0.0, lon=0.0)
    b = GeoPoint(lat=1.0, lon=0.0)
    assert haversine_km(a, b) == pytest.approx(111.19, abs=0.5)
    assert vincenty_km(a, b) == pytest.approx(110.57, abs=0.5)


def test_vincenty_and_haversine_agree_within_a_percent():
    d_h, d_v = haversine_km(KOCHI, CHENNAI), vincenty_km(KOCHI, CHENNAI)
    assert abs(d_h - d_v) / d_v < 0.01


def test_known_leg_kochi_to_chennai():
    # Great-circle separation of the two city centres is ~560 km.
    assert distance_km(KOCHI, CHENNAI) == pytest.approx(560, abs=15)


def test_bearing_is_reciprocal_within_convergence():
    fwd = initial_bearing_deg(KOCHI, CHENNAI)
    back = initial_bearing_deg(CHENNAI, KOCHI)
    assert 0 <= fwd < 360 and 0 <= back < 360
    assert abs(((fwd + 180) % 360) - back) < 15


def test_destination_point_round_trips():
    target = destination_point(KOCHI, 270.0, 50.0)
    assert distance_km(KOCHI, target) == pytest.approx(50.0, rel=1e-3)
    assert target.lon < KOCHI.lon                       # due west
    assert target.lat == pytest.approx(KOCHI.lat, abs=0.01)


def test_densify_endpoints_and_spacing():
    pts = densify(KOCHI, CHENNAI, 5)
    assert len(pts) == 5
    assert pts[0].lat == pytest.approx(KOCHI.lat, abs=1e-6)
    assert distance_km(pts[-1], CHENNAI) < 1.0


@pytest.mark.parametrize("bearing,name", [(0, "N"), (90, "E"), (180, "S"), (270, "W"), (45, "NE")])
def test_compass_points(bearing, name):
    assert compass_point(bearing) == name


def test_point_in_polygon_inside_outside_and_hole():
    square = [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]
    assert point_in_polygon(GeoPoint(lat=5, lon=5), square)
    assert not point_in_polygon(GeoPoint(lat=15, lon=5), square)
    with_hole = square + [[[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]]
    assert not point_in_polygon(GeoPoint(lat=5, lon=5), with_hole)
    assert point_in_polygon(GeoPoint(lat=2, lon=2), with_hole)


def test_distance_to_geometry_is_zero_inside():
    geom = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    assert distance_to_geometry_km(GeoPoint(lat=5, lon=5), geom) == 0.0
    assert distance_to_geometry_km(GeoPoint(lat=5, lon=11), geom) > 50


def test_point_to_segment_uses_the_perpendicular():
    a, b = GeoPoint(lat=0, lon=0), GeoPoint(lat=0, lon=1)
    mid_off = GeoPoint(lat=0.1, lon=0.5)
    assert point_to_segment_km(mid_off, a, b) == pytest.approx(11.06, abs=0.5)


def test_ring_centroid_of_a_square():
    c = ring_centroid([[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]])
    assert (c.lat, c.lon) == pytest.approx((5.0, 5.0))


# ---- gazetteer -------------------------------------------------------------
def test_gazetteer_resolves_english_alias_and_indic_names():
    gz = get_gazetteer()
    assert gz.find("Kochi").id == "kochi"
    assert gz.find("cochin").id == "kochi"
    assert gz.find("കൊച്ചി").id == "kochi"
    assert gz.find("चेन्नई").id == "chennai"


def test_gazetteer_returns_places_in_reading_order():
    gz = get_gazetteer()
    names = [p.name for p in gz.search_in_text("route from Kochi to Mangaluru")]
    assert names == ["Kochi", "Mangaluru"]


def test_gazetteer_handles_indic_case_suffixes():
    gz = get_gazetteer()
    hits = gz.search_in_text("കൊച്ചിയിൽ നിന്ന്")
    assert hits and hits[0].id == "kochi"


def test_longer_name_beats_shorter_substring():
    gz = get_gazetteer()
    names = [p.name for p in gz.search_in_text("weather at Port Blair today")]
    assert names == ["Port Blair"]


def test_offshore_point_is_seaward_and_at_the_right_distance():
    place = get_gazetteer().find("Kochi")
    off = place.offshore_point(6.0)
    assert distance_km(place.point, off) == pytest.approx(6.0, rel=1e-3)
    assert off.lon < place.point.lon      # Kochi's seaward bearing is west


# ---- layers ----------------------------------------------------------------
def test_maritime_bands_increase_with_distance_offshore():
    near = maritime_band(GeoPoint(lat=9.93, lon=76.15))
    far = maritime_band(GeoPoint(lat=12.0, lon=62.0))
    assert near[0] == "territorial_waters"
    assert far[0] == "high_seas"
    assert far[2] > near[2]


def test_every_shipped_layer_is_flagged_non_authoritative():
    # Nothing in this prototype may claim to be an official maritime boundary.
    assert all(not layer.authoritative for layer in layer_catalogue())


def test_zones_near_returns_sorted_relations():
    zones = zones_near(GeoPoint(lat=9.93, lon=76.15), 100.0)
    distances = [z.distance_km for z in zones]
    assert distances == sorted(distances)


def test_baseline_is_marked_non_authoritative():
    baseline = get_baseline()
    assert baseline.authoritative is False
    assert "NOT" in baseline.description
