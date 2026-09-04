"""Multi-source fusion and conflict resolution.

Two sources will disagree.  The wrong responses are to average them (which
invents a number nobody published) or to take whichever arrived last (which
makes the answer depend on network jitter).

ORCA's rule:

1. keep every source's claim intact and attributed;
2. measure the spread against a per-variable tolerance that reflects how much
   disagreement is normal for that quantity;
3. if the spread is material, pick the value from the **documented authority for
   that variable's domain** - IMD for atmosphere, INCOIS for ocean - never a
   blend;
4. reduce confidence in proportion to the disagreement, and say so in the answer
   when it is material enough to move the risk band.

The priority order lives in ``providers/registry.SOURCE_PRIORITY`` so it is
configuration, not a hidden preference.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.providers.registry import SOURCE_PRIORITY, VARIABLE_DOMAIN
from app.schemas.common import ConflictSeverity, Source
from app.schemas.evidence import Conflict, Evidence

# absolute tolerance, relative tolerance - whichever is larger applies
TOLERANCES: dict[str, tuple[float, float]] = {
    "wind_speed_10m": (7.0, 0.25),
    "wind_gust_10m": (10.0, 0.30),
    "wind_direction_10m": (40.0, 0.0),
    "precipitation": (2.0, 0.60),
    "visibility": (3000.0, 0.40),
    "cloud_cover": (25.0, 0.0),
    "temperature_2m": (2.0, 0.0),
    "cape": (600.0, 0.40),
    "wave_height_significant": (0.4, 0.25),
    "wave_period": (2.0, 0.25),
    "swell_height": (0.4, 0.30),
    "sea_surface_temperature": (1.0, 0.0),
    "current_speed": (0.8, 0.40),
}
DEFAULT_TOLERANCE = (1.0, 0.35)


@dataclass
class FusedValue:
    variable: str
    value: float
    unit: str
    source: Source
    provider: str
    evidence_id: str
    evidence_ids: list[str]
    conflict: Conflict | None = None
    confidence: float = 1.0


def _priority_index(variable: str, source: Source) -> int:
    order = SOURCE_PRIORITY.get(VARIABLE_DOMAIN.get(variable, ""), [])
    return order.index(source) if source in order else len(order)


def fuse(evidence: list[Evidence]) -> tuple[dict[str, FusedValue], list[Conflict]]:
    """Collapse many sources' claims into one value per variable."""
    by_variable: dict[str, list[Evidence]] = {}
    for e in evidence:
        if e.value is None or not isinstance(e.value, (int, float)):
            continue
        by_variable.setdefault(e.variable, []).append(e)

    fused: dict[str, FusedValue] = {}
    conflicts: list[Conflict] = []

    for variable, items in by_variable.items():
        items = sorted(items, key=lambda e: _priority_index(variable, e.source))
        winner = items[0]
        ids = [e.evidence_id for e in items]

        if len(items) == 1:
            fused[variable] = FusedValue(
                variable=variable, value=float(winner.value), unit=winner.unit or "",
                source=winner.source, provider=winner.provider,
                evidence_id=winner.evidence_id, evidence_ids=ids)
            continue

        values = [float(e.value) for e in items]
        spread = max(values) - min(values)
        abs_tol, rel_tol = TOLERANCES.get(variable, DEFAULT_TOLERANCE)
        mean = sum(values) / len(values)
        tolerance = max(abs_tol, abs(mean) * rel_tol)

        if spread <= tolerance:
            severity = ConflictSeverity.NONE if spread <= tolerance / 2 else ConflictSeverity.MINOR
            penalty = 0.0 if severity is ConflictSeverity.NONE else 0.03
        else:
            severity = ConflictSeverity.MATERIAL
            penalty = min(0.30, 0.10 + 0.20 * min(1.0, (spread - tolerance) / max(tolerance, 1e-6)))

        conflict = None
        if severity is not ConflictSeverity.NONE:
            conflict = Conflict(
                variable=variable, severity=severity.value, unit=winner.unit or "",
                claims=[{"source": e.source.value, "provider": e.provider,
                         "value": float(e.value), "unit": e.unit,
                         "freshness": e.freshness.value,
                         "evidence_id": e.evidence_id} for e in items],
                spread=round(spread, 3), tolerance=round(tolerance, 3),
                resolution=(f"used {winner.source.value} as the documented authority "
                            f"for {VARIABLE_DOMAIN.get(variable, 'this')} variables; "
                            "values were not averaged"),
                winning_source=winner.source, confidence_penalty=round(penalty, 3),
                explanation=_explain(items, spread, tolerance, severity),
            )
            conflicts.append(conflict)

        fused[variable] = FusedValue(
            variable=variable, value=float(winner.value), unit=winner.unit or "",
            source=winner.source, provider=winner.provider,
            evidence_id=winner.evidence_id, evidence_ids=ids,
            conflict=conflict, confidence=max(0.0, 1.0 - penalty))

    return fused, conflicts


def _explain(items: list[Evidence], spread: float, tolerance: float,
             severity: ConflictSeverity) -> str:
    if severity is not ConflictSeverity.MATERIAL:
        return f"sources agree within tolerance ({spread:.2f} <= {tolerance:.2f})"
    claims = " vs ".join(
        "{} {:g}{}".format(e.source.value, float(e.value), e.unit or "") for e in items)
    return f"{claims} (spread {spread:.2f} > tolerance {tolerance:.2f})"


def material_conflicts(conflicts: list[Conflict]) -> list[Conflict]:
    return [c for c in conflicts if c.severity == ConflictSeverity.MATERIAL.value]
