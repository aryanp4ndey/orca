"""H. Risk scoring - deterministic, explainable, and fails safe."""

from __future__ import annotations

import pytest

from app.core.clock import utcnow
from app.reasoning.fusion import FusedValue
from app.safety.risk_engine import RiskInputs, assess, load_rules
from app.schemas.common import (
    DataOrigin,
    DecisionStatus,
    Freshness,
    RiskLevel,
    Source,
    VariableKind,
)
from app.schemas.evidence import Evidence


def fv(variable, value, unit, source=Source.INCOIS, eid=None):
    eid = eid or f"ev_{variable}"
    return FusedValue(variable=variable, value=value, unit=unit, source=source,
                      provider="p", evidence_id=eid, evidence_ids=[eid])


def evidence_for(values, freshness=Freshness.FRESH):
    now = utcnow()
    return [Evidence(evidence_id=v.evidence_id, source=v.source, provider="p",
                     dataset="d", variable=v.variable, value=v.value, unit=v.unit,
                     kind=VariableKind.FORECAST, origin=DataOrigin.DEMO,
                     retrieved_at=now, age_seconds=1.0, freshness=freshness)
            for v in values.values()]


def make(values, **kw):
    inputs = RiskInputs(activity=kw.pop("activity", "fishing_small_boat"),
                        vessel=kw.pop("vessel", "small_motorised"),
                        values=values, evidence=evidence_for(values), **kw)
    return assess(inputs)


CALM = {"wave_height_significant": fv("wave_height_significant", 0.6, "m"),
        "wind_speed_10m": fv("wind_speed_10m", 12.0, "km/h", Source.IMD)}
ROUGH = {"wave_height_significant": fv("wave_height_significant", 2.8, "m"),
         "wind_speed_10m": fv("wind_speed_10m", 40.0, "km/h", Source.IMD)}
SEVERE = {"wave_height_significant": fv("wave_height_significant", 4.5, "m"),
          "wind_speed_10m": fv("wind_speed_10m", 65.0, "km/h", Source.IMD)}


def test_calm_conditions_are_low_risk():
    assessment = make(CALM)
    assert assessment.risk_level is RiskLevel.LOW
    assert assessment.decision_status is DecisionStatus.ADVISORY_ISSUED


def test_rough_conditions_are_high_risk():
    assert make(ROUGH).risk_level is RiskLevel.HIGH


def test_severe_conditions_are_critical():
    assert make(SEVERE).risk_level is RiskLevel.CRITICAL


def test_engine_is_deterministic():
    a, b = make(ROUGH), make(ROUGH)
    assert (a.risk_level, a.risk_score, a.confidence) == (b.risk_level, b.risk_score, b.confidence)


def test_every_factor_cites_the_value_threshold_and_evidence():
    assessment = make(ROUGH)
    assert assessment.factors
    for factor in assessment.factors:
        assert factor.rationale
        assert factor.evidence_ids
        if factor.level is not RiskLevel.LOW:
            assert factor.threshold is not None
            assert factor.comparator in (">=", "<=")


def test_vessel_class_changes_the_thresholds():
    canoe = make(ROUGH, vessel="canoe")
    large = make(ROUGH, vessel="large")
    assert canoe.risk_level.rank >= large.risk_level.rank


def test_activity_changes_the_thresholds():
    """The same sea is dangerous for a swimmer and routine for a cargo ship."""
    moderate = {"wave_height_significant": fv("wave_height_significant", 1.4, "m"),
                "wind_speed_10m": fv("wind_speed_10m", 22.0, "km/h", Source.IMD)}
    swimmer = make(moderate, activity="swimming", vessel="none")
    cargo = make(moderate, activity="cargo_transit", vessel="large")
    assert swimmer.risk_level.rank > cargo.risk_level.rank


def test_missing_required_variable_withholds_the_advisory():
    """'I do not know' must never become 'it is safe'."""
    only_wind = {"wind_speed_10m": fv("wind_speed_10m", 8.0, "km/h", Source.IMD)}
    assessment = make(only_wind)
    assert assessment.risk_level is RiskLevel.INSUFFICIENT_DATA
    assert assessment.decision_status is DecisionStatus.ADVISORY_WITHHELD
    assert "wave_height_significant" in assessment.missing_variables
    assert any("unknown" in w.lower() for w in assessment.warnings)


def test_no_evidence_at_all_is_insufficient_data():
    assessment = make({})
    assert assessment.risk_level is RiskLevel.INSUFFICIENT_DATA
    assert assessment.decision_status is DecisionStatus.ADVISORY_WITHHELD


def test_stale_evidence_degrades_the_advisory_and_the_confidence():
    values = dict(CALM)
    inputs = RiskInputs(activity="fishing_small_boat", vessel="small_motorised",
                        values=values, evidence=evidence_for(values, Freshness.STALE),
                        worst_freshness=Freshness.STALE)
    assessment = assess(inputs)
    fresh = make(CALM)
    assert assessment.decision_status is DecisionStatus.ADVISORY_DEGRADED
    assert assessment.confidence < fresh.confidence
    assert assessment.stale_variables


def test_authority_warning_sets_a_floor_and_is_not_re_scored():
    assessment = make(CALM, advisory_severity="severe",
                      advisory_headlines=["Cyclonic conditions likely"])
    assert assessment.risk_level is RiskLevel.CRITICAL
    assert "Cyclonic conditions likely" in assessment.warnings


def test_several_moderate_factors_escalate_to_high():
    values = {
        "wave_height_significant": fv("wave_height_significant", 1.6, "m"),
        "wind_speed_10m": fv("wind_speed_10m", 21.0, "km/h", Source.IMD),
        "swell_height": fv("swell_height", 1.6, "m"),
        "visibility": fv("visibility", 4500.0, "m", Source.IMD),
    }
    assert make(values).risk_level is RiskLevel.HIGH


def test_unavailable_source_lowers_confidence():
    with_source = make(CALM)
    without = make(CALM, unavailable_sources=["MOSDAC"])
    assert without.confidence < with_source.confidence
    assert any("MOSDAC" in d for d in without.confidence_drivers)


def test_visibility_rule_inverts_correctly_for_larger_vessels():
    poor_visibility = {
        "wave_height_significant": fv("wave_height_significant", 0.5, "m"),
        "wind_speed_10m": fv("wind_speed_10m", 10.0, "km/h", Source.IMD),
        "visibility": fv("visibility", 4000.0, "m", Source.IMD)}
    small = make(poor_visibility, vessel="canoe")
    large = make(poor_visibility, vessel="large")
    small_factor = next(f for f in small.factors if f.factor_id == "visibility")
    large_factor = next(f for f in large.factors if f.factor_id == "visibility")
    assert small_factor.level.rank >= large_factor.level.rank


def test_disclaimer_is_always_attached():
    assert "not a certified" in make(CALM).disclaimer.lower()


def test_ruleset_is_versioned_and_reported():
    assessment = make(CALM)
    rules = load_rules()
    assert assessment.ruleset_id == rules["ruleset_id"]
    assert assessment.ruleset_version == str(rules["version"])


def test_ruleset_carries_its_own_honesty_note():
    """The thresholds must never be mistaken for an authority's official criteria."""
    import pathlib
    import re
    raw = pathlib.Path("app/safety/rules.yaml").read_text().lower()
    text = re.sub(r"\s+", " ", raw.replace("#", " "))
    assert "indicative" in text
    assert "not a certified" in text
    assert "not a reproduction of any authority" in text


def test_inherited_activity_profiles_resolve():
    for activity in ("fishing_mechanised", "swimming", "cargo_transit", "patrol",
                     "tourism", "diving", "research", "generic"):
        assessment = make(ROUGH, activity=activity)
        assert assessment.factors, f"{activity} produced no factors"
        assert assessment.activity == activity
