"""G. Source conflict handling - never average, always attribute."""

from __future__ import annotations

import datetime as dt

from app.core.clock import utcnow
from app.reasoning.fusion import fuse, material_conflicts
from app.schemas.common import DataOrigin, Freshness, Source, VariableKind
from app.schemas.evidence import Evidence


def ev(source, variable, value, unit, eid):
    now = utcnow()
    return Evidence(
        evidence_id=eid, source=source, provider=f"{source.value.lower()}_x",
        dataset="d", variable=variable, value=value, unit=unit,
        kind=VariableKind.FORECAST, origin=DataOrigin.DEMO,
        retrieved_at=now, age_seconds=10.0, freshness=Freshness.FRESH)


def test_single_source_passes_through_unchanged():
    fused, conflicts = fuse([ev(Source.IMD, "wind_speed_10m", 20.0, "km/h", "e1")])
    assert conflicts == []
    assert fused["wind_speed_10m"].value == 20.0


def test_small_disagreement_is_within_tolerance():
    fused, conflicts = fuse([
        ev(Source.IMD, "wind_speed_10m", 20.0, "km/h", "e1"),
        ev(Source.OPEN_METEO, "wind_speed_10m", 22.0, "km/h", "e2")])
    assert material_conflicts(conflicts) == []
    assert fused["wind_speed_10m"].value == 20.0        # IMD is the authority


def test_material_disagreement_keeps_both_claims_and_never_averages():
    fused, conflicts = fuse([
        ev(Source.IMD, "wind_speed_10m", 20.0, "km/h", "e1"),
        ev(Source.OPEN_METEO, "wind_speed_10m", 55.0, "km/h", "e2")])
    material = material_conflicts(conflicts)
    assert len(material) == 1
    conflict = material[0]
    assert {c["value"] for c in conflict.claims} == {20.0, 55.0}
    assert fused["wind_speed_10m"].value in (20.0, 55.0)
    assert fused["wind_speed_10m"].value != 37.5, "values must never be averaged"
    assert conflict.confidence_penalty > 0
    assert "not averaged" in conflict.resolution


def test_documented_authority_wins_per_domain():
    fused, _ = fuse([
        ev(Source.OPEN_METEO, "wave_height_significant", 1.0, "m", "e1"),
        ev(Source.INCOIS, "wave_height_significant", 3.0, "m", "e2")])
    assert fused["wave_height_significant"].source is Source.INCOIS
    fused2, _ = fuse([
        ev(Source.OPEN_METEO, "wind_speed_10m", 10.0, "km/h", "e3"),
        ev(Source.IMD, "wind_speed_10m", 40.0, "km/h", "e4")])
    assert fused2["wind_speed_10m"].source is Source.IMD


def test_conflict_lowers_confidence_proportionally():
    _, small = fuse([ev(Source.IMD, "wave_height_significant", 2.0, "m", "a"),
                     ev(Source.INCOIS, "wave_height_significant", 2.9, "m", "b")])
    _, large = fuse([ev(Source.IMD, "wave_height_significant", 2.0, "m", "c"),
                     ev(Source.INCOIS, "wave_height_significant", 6.0, "m", "d")])
    assert large[0].confidence_penalty > small[0].confidence_penalty


def test_every_claim_keeps_its_attribution_and_evidence_id():
    _, conflicts = fuse([
        ev(Source.IMD, "wind_speed_10m", 20.0, "km/h", "e1"),
        ev(Source.OPEN_METEO, "wind_speed_10m", 60.0, "km/h", "e2")])
    for claim in conflicts[0].claims:
        assert claim["source"] and claim["provider"] and claim["evidence_id"]


def test_non_numeric_evidence_is_ignored_by_fusion():
    fused, _ = fuse([ev(Source.IMD, "advisory:wind", "warning", None, "e1")])
    assert fused == {}
