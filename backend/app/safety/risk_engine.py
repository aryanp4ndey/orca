"""Deterministic risk engine.

Properties this engine guarantees, all of them testable:

* **Deterministic** - same evidence in, same assessment out, every time.
* **Explainable** - every band comes from a named rule with the exact value and
  threshold that triggered it, and each factor carries the evidence ids it used.
* **LLM-free** - no model is consulted here. The language model never chooses a
  risk level, and never sees this code path.
* **Fails safe** - missing or stale evidence for a required variable produces
  INSUFFICIENT_DATA and an explicitly withheld advisory. "We do not know" is
  never converted into "it is fine".
* **Tunable** - all thresholds live in ``rules.yaml``.

An authority's warning is treated as a fact, not an input to be re-scored: an
IMD severe warning sets a CRITICAL floor no matter what the numbers say.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

from app.reasoning.fusion import FusedValue
from app.schemas.common import DecisionStatus, Freshness, RiskLevel
from app.schemas.evidence import Conflict, Evidence
from app.schemas.risk import RiskAssessment, RiskFactor

LEVEL_ORDER = [RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.CRITICAL]

DISCLAIMER = (
    "ORCA is a decision-support prototype, not a certified navigation or "
    "maritime-safety system. Always check the official IMD / INCOIS advisory and "
    "your local fisheries or port authority before going to sea.")


@lru_cache(maxsize=1)
def load_rules(path: str | None = None) -> dict[str, Any]:
    path = path or os.path.join(os.path.dirname(__file__), "rules.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _resolve_activity(rules: dict, activity: str) -> dict:
    activities = rules["activities"]
    spec = activities.get(activity) or activities["generic"]
    if "inherit" not in spec:
        return {"label": spec["label"], "rules": [dict(r) for r in spec["rules"]]}
    parent = _resolve_activity(rules, spec["inherit"])
    merged = [dict(r) for r in parent["rules"]]
    overrides = spec.get("overrides", {})
    for rule in merged:
        if rule["id"] in overrides:
            rule["bands"] = dict(overrides[rule["id"]])
    merged.extend(dict(r) for r in spec.get("extra_rules", []))
    return {"label": spec.get("label", parent["label"]), "rules": merged}


@dataclass
class RiskInputs:
    activity: str
    vessel: str
    values: dict[str, FusedValue]
    evidence: list[Evidence]
    advisory_severity: str = "none"
    advisory_headlines: list[str] | None = None
    conflicts: list[Conflict] | None = None
    unavailable_sources: list[str] | None = None
    worst_freshness: Freshness = Freshness.FRESH


def _band_for(value: float, comparator: str, bands: dict[str, float],
              factor: float) -> tuple[RiskLevel, float | None]:
    """Highest band whose threshold the value has crossed."""
    hit: tuple[RiskLevel, float | None] = (RiskLevel.LOW, None)
    for level_name in ("MODERATE", "HIGH", "CRITICAL"):
        if level_name not in bands:
            continue
        threshold = bands[level_name] * factor
        crossed = value >= threshold if comparator == ">=" else value <= threshold
        if crossed:
            hit = (RiskLevel[level_name], round(threshold, 3))
    return hit


def assess(inputs: RiskInputs, rules: dict | None = None) -> RiskAssessment:
    rules = rules or load_rules()
    spec = _resolve_activity(rules, inputs.activity)
    vessel_factor = rules["vessel_factor"].get(inputs.vessel, 1.0)
    conf_cfg = rules["confidence"]

    factors: list[RiskFactor] = []
    missing_required: list[str] = []
    missing_optional: list[str] = []
    stale_variables: list[str] = []
    score = 0.0
    total_weight = 0.0

    for rule in spec["rules"]:
        variable = rule["variable"]
        fused = inputs.values.get(variable)
        # Visibility-style rules invert, so the vessel factor must invert too:
        # a bigger vessel tolerates *lower* visibility.
        factor = vessel_factor if rule["comparator"] == ">=" else (1.0 / vessel_factor)

        if fused is None:
            (missing_required if rule.get("required") else missing_optional).append(variable)
            continue

        ev = next((e for e in inputs.evidence if e.evidence_id == fused.evidence_id), None)
        if ev is not None and ev.freshness is Freshness.STALE:
            stale_variables.append(variable)

        level, threshold = _band_for(fused.value, rule["comparator"],
                                     rule["bands"], factor)
        weight = float(rule["weight"])
        total_weight += weight
        contribution = weight * (LEVEL_ORDER.index(level) / 3.0)
        score += contribution

        factors.append(RiskFactor(
            factor_id=rule["id"], variable=variable, label=rule["label"],
            value=round(fused.value, 2), unit=fused.unit or rule.get("unit"),
            threshold=threshold, comparator=rule["comparator"], level=level,
            weight=weight, contribution=round(contribution, 2),
            evidence_ids=fused.evidence_ids,
            rationale=_rationale(rule, fused, level, threshold, vessel_factor),
        ))

    normalised_score = round(100.0 * score / total_weight, 1) if total_weight else 0.0

    # ---- combine ---------------------------------------------------------
    if factors:
        level = max((f.level for f in factors), key=lambda l: LEVEL_ORDER.index(l))
    else:
        level = RiskLevel.INSUFFICIENT_DATA

    esc = rules["escalation"]
    moderate_plus = sum(1 for f in factors if f.level is not RiskLevel.LOW)
    high_plus = sum(1 for f in factors
                    if f.level in (RiskLevel.HIGH, RiskLevel.CRITICAL))
    if level is RiskLevel.MODERATE and moderate_plus >= esc["moderate_count_for_high"]:
        level = RiskLevel.HIGH
    if level is RiskLevel.HIGH and high_plus >= esc["high_count_for_critical"]:
        level = RiskLevel.CRITICAL

    floor = RiskLevel[rules["advisory_floors"].get(inputs.advisory_severity, "LOW")]
    if level is not RiskLevel.INSUFFICIENT_DATA and \
            LEVEL_ORDER.index(floor) > LEVEL_ORDER.index(level):
        level = floor

    # ---- confidence ------------------------------------------------------
    confidence = float(conf_cfg["base"])
    drivers: list[str] = []
    if missing_required:
        confidence -= conf_cfg["penalty_per_missing_required"] * len(missing_required)
        drivers.append(f"missing required variable(s): {', '.join(missing_required)}")
    if missing_optional:
        confidence -= conf_cfg["penalty_per_missing_optional"] * len(missing_optional)
        drivers.append(f"missing optional variable(s): {', '.join(missing_optional)}")
    if stale_variables:
        confidence -= conf_cfg["penalty_stale_source"]
        drivers.append(f"stale evidence for {', '.join(sorted(set(stale_variables)))}")
    elif inputs.worst_freshness is Freshness.AGING:
        confidence -= conf_cfg["penalty_aging_source"]
        drivers.append("some evidence is older than its normal update cycle")
    for source in (inputs.unavailable_sources or []):
        confidence -= conf_cfg["penalty_unavailable_source"]
        drivers.append(f"{source} did not respond")
    for conflict in (inputs.conflicts or []):
        confidence -= conflict.confidence_penalty
        if conflict.confidence_penalty:
            drivers.append(f"sources disagree on {conflict.variable}")
    confidence = round(max(0.0, min(1.0, confidence)), 3)

    # ---- gating ----------------------------------------------------------
    warnings: list[str] = list(inputs.advisory_headlines or [])
    gate_reason = None
    if missing_required:
        level = RiskLevel.INSUFFICIENT_DATA
        decision = DecisionStatus.ADVISORY_WITHHELD
        gate_reason = ("required evidence is missing: "
                       + ", ".join(missing_required))
        warnings.append(
            "ORCA cannot assess safety without " + ", ".join(missing_required)
            + ". Treat this as 'unknown', not as 'safe'.")
    elif stale_variables:
        decision = DecisionStatus.ADVISORY_DEGRADED
        gate_reason = ("assessment based on data older than its acceptable age: "
                       + ", ".join(sorted(set(stale_variables))))
        warnings.append(
            "Some readings are older than they should be; verify against the "
            "current official advisory before acting.")
    elif confidence < conf_cfg["min_confidence_for_advisory"]:
        decision = DecisionStatus.ADVISORY_WITHHELD
        level = RiskLevel.INSUFFICIENT_DATA
        gate_reason = f"confidence {confidence} below the minimum for an advisory"
        warnings.append(
            "Too little reliable data to give a safety recommendation right now.")
    else:
        decision = DecisionStatus.ADVISORY_ISSUED

    dominant = max(factors, key=lambda f: (LEVEL_ORDER.index(f.level), f.contribution),
                   default=None)

    return RiskAssessment(
        risk_level=level, risk_score=normalised_score, decision_status=decision,
        factors=sorted(factors, key=lambda f: -LEVEL_ORDER.index(f.level)),
        dominant_factor=dominant.factor_id if dominant else None,
        confidence=confidence, confidence_drivers=drivers, warnings=warnings,
        missing_variables=missing_required + missing_optional,
        stale_variables=sorted(set(stale_variables)),
        evidence_freshness=inputs.worst_freshness,
        ruleset_id=rules["ruleset_id"], ruleset_version=str(rules["version"]),
        activity=inputs.activity, gate_reason=gate_reason, disclaimer=DISCLAIMER,
    )


def _rationale(rule: dict, fused: FusedValue, level: RiskLevel,
               threshold: float | None, vessel_factor: float) -> str:
    unit = fused.unit or rule.get("unit", "")
    if level is RiskLevel.LOW or threshold is None:
        return (f"{rule['label']} {fused.value:g} {unit} is below the "
                f"{rule['label'].lower()} advisory threshold "
                f"({fused.source.value})")
    adjust = "" if abs(vessel_factor - 1.0) < 1e-9 else \
        f", adjusted by vessel factor {vessel_factor:g}"
    return (f"{rule['label']} {fused.value:g} {unit} {rule['comparator']} "
            f"{threshold:g} {unit} -> {level.value} ({fused.source.value}{adjust})")
