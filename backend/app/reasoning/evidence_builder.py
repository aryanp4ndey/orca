"""Turn provider results into evidence rows.

Every measurement that survives into an answer gets an :class:`Evidence` row
here, with a stable id.  Risk factors reference those ids, and the response
builder refuses to emit a number that has no row - that chain is what makes
"why did ORCA say that?" answerable rather than rhetorical.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.core.clock import age_seconds, utcnow
from app.reasoning.freshness import classify
from app.schemas.common import DataOrigin, Freshness, Source, VariableKind
from app.schemas.evidence import Evidence, SourceReport
from app.schemas.marine import ProviderResult


def _evidence_id(provider_id: str, variable: str, valid_time: datetime) -> str:
    raw = f"{provider_id}|{variable}|{valid_time.isoformat()}"
    return "ev_" + hashlib.sha1(raw.encode()).hexdigest()[:12]


def from_provider_result(result: ProviderResult, agent: str,
                         now: datetime | None = None) -> list[Evidence]:
    now = now or utcnow()
    out: list[Evidence] = []
    for m in result.measurements:
        reference = m.issued_at or result.retrieved_at
        fresh, _ = classify(
            reference,
            result.update_frequency_seconds or 3600,
            result.max_acceptable_age_seconds or 21600,
            now)
        if m.value is None:
            fresh = Freshness.UNAVAILABLE
        out.append(Evidence(
            evidence_id=_evidence_id(result.provider_id, m.variable, m.valid_time),
            source=result.source, provider=result.provider_id,
            dataset=m.dataset or result.dataset, variable=m.variable,
            value=m.value, unit=m.unit, kind=m.kind, origin=result.origin,
            location=m.location,
            observation_time=m.valid_time if m.kind in (
                VariableKind.OBSERVED, VariableKind.ANALYSIS) else None,
            forecast_time=m.valid_time if m.kind is VariableKind.FORECAST else None,
            issued_at=m.issued_at,
            retrieved_at=result.retrieved_at or now,
            age_seconds=round(age_seconds(reference, now), 1) if reference else float("inf"),
            freshness=fresh, quality=m.quality, transformation=m.transformation,
            agent=agent, cache_hit=result.cache.hit,
        ))
    for a in result.advisories:
        reference = a.issued_at or result.retrieved_at
        fresh, _ = classify(reference, result.update_frequency_seconds or 3600,
                            result.max_acceptable_age_seconds or 21600, now)
        out.append(Evidence(
            evidence_id=_evidence_id(result.provider_id, f"advisory:{a.category}",
                                     a.issued_at or (result.retrieved_at or now)),
            source=result.source, provider=result.provider_id,
            dataset=a.dataset or result.dataset,
            variable=f"advisory:{a.category}", value=a.severity, unit=None,
            kind=VariableKind.ADVISORY, origin=result.origin,
            issued_at=a.issued_at, retrieved_at=result.retrieved_at or now,
            age_seconds=round(age_seconds(reference, now), 1) if reference else float("inf"),
            freshness=fresh, agent=agent, cache_hit=result.cache.hit,
            notes=a.headline,
        ))
    return out


def computed_evidence(variable: str, value, unit: str | None, agent: str,
                      transformation: str, dataset: str = "orca_deterministic",
                      location=None, notes: str | None = None) -> Evidence:
    """Evidence for something ORCA calculated rather than retrieved.

    Distances, distance-to-coast, zone membership: these are ours, and they are
    labelled ``ORCA_INTERNAL`` / ``COMPUTED`` so nobody mistakes a calculation
    for an observation.
    """
    now = utcnow()
    return Evidence(
        evidence_id=_evidence_id("orca", variable, now),
        source=Source.ORCA_INTERNAL, provider="orca_deterministic", dataset=dataset,
        variable=variable, value=value, unit=unit, kind=VariableKind.DERIVED,
        origin=DataOrigin.COMPUTED, location=location, retrieved_at=now,
        age_seconds=0.0, freshness=Freshness.FRESH, transformation=transformation,
        agent=agent, notes=notes,
    )


def source_report(result: ProviderResult) -> SourceReport:
    return SourceReport(
        source=result.source, provider=result.provider_id, origin=result.origin,
        status=result.status.value, latency_ms=round(result.latency_ms, 2),
        retrieved_at=result.retrieved_at, freshness=result.freshness,
        dataset=result.dataset, error=result.error, cache_hit=result.cache.hit,
        attribution=result.attribution,
    )
