# Evidence and provenance

## Why this is the data model, not a feature

The question a technical judge will ask is *"how do you know that number is real?"* The
only answer that survives follow-up is: here is the row it came from.

So in ORCA, **a value cannot exist in an answer without an `Evidence` row.** The response
agent runs a mechanical grounding check before returning: every numeric token in the
answer text must correspond to a value in the ledger, a threshold from the risk ruleset, a
deterministic computation, or a timestamp being reported. A number that matches none of
those fails the check, and if the text came from a language model it is discarded in
favour of the deterministic answer.

## The Evidence row

```python
Evidence(
    evidence_id,        # stable: sha1(provider|variable|valid_time)
    source,             # IMD | INCOIS | MOSDAC | GIS | OPEN_METEO | ORCA_INTERNAL
    provider,           # the concrete implementation, e.g. "incois_demo"
    dataset,            # dataset / endpoint / bulletin identifier
    variable,           # canonical name, e.g. "wave_height_significant"
    value, unit,
    kind,               # OBSERVED | FORECAST | ANALYSIS | ADVISORY | DERIVED
    origin,             # LIVE | CACHED_LIVE | DEMO | COMPUTED
    location,
    observation_time,   # when it was measured
    forecast_time,      # what time it describes
    issued_at,          # when the source published it
    retrieved_at,       # when ORCA fetched it
    age_seconds,
    freshness,          # FRESH | AGING | STALE | UNAVAILABLE
    quality,            # GOOD | ESTIMATED | SUSPECT | MISSING
    transformation,     # e.g. "m/s -> km/h", "nearest-hour selection"
    agent,              # which agent produced it
    cache_hit,
    notes,
)
```

Four separate timestamps is not over-engineering. A forecast issued 30 hours ago for
07:00 tomorrow is *stale* even though its valid time is in the future — and a system that
carries only one timestamp cannot tell you that.

## Reading a chain

```
GET /api/v1/evidence/q_8a3f21c04b7e
```

```
INCOIS  incois_demo  wave_height_significant  2.08 m
        forecast for 2026-09-03T01:30Z | issued 2026-09-02T02:30Z
        retrieved 2026-09-02T05:41Z | age 11460 s | FRESH | GOOD
        transformation: demo synthesis (deterministic)

IMD     imd_demo     wind_speed_10m           34.8 km/h
        forecast for 2026-09-03T01:30Z | issued 2026-09-02T00:30Z
        retrieved 2026-09-02T05:41Z | age 18660 s | AGING | GOOD

IMD     imd_demo     advisory:wind            "advisory"
        "Strong winds likely over the coastal waters"
        issued 2026-09-02T00:30Z | AGING

ORCA    orca_deterministic  distance_to_coast_km  5.6 km   COMPUTED
        transformation: shortest great-circle distance from the query point to
        the ORCA coastal baseline polyline
        note: Baseline is approximate (order 10 km) and non-authoritative.
```

Two things to notice. First, ORCA's own computations are labelled `ORCA_INTERNAL` /
`COMPUTED` and carry the method — nobody can mistake a calculation for an observation.
Second, the caveat travels *with* the value: the coastal baseline says it is approximate
in its own evidence row, not only in a document.

## From evidence to risk factor

Each `RiskFactor` carries `evidence_ids`. There is a test asserting that every factor's
ids exist in the ledger for that query, so the chain cannot silently break:

```python
RiskFactor(
    factor_id="wind_speed",
    variable="wind_speed_10m",
    value=34.8, unit="km/h",
    threshold=34.0, comparator=">=",
    level=HIGH, weight=25, contribution=16.67,
    evidence_ids=["ev_5c1a9b2f7d31"],
    rationale="Wind speed 34.8 km/h >= 34 km/h -> HIGH (IMD)",
)
```

## Freshness

Measured against **issue time** where a source provides one, falling back to retrieval
time, and compared with that provider's own declared update cycle:

| Condition | Verdict |
|---|---|
| `age <= update_frequency` | **FRESH** |
| `age <= max_acceptable_age` | **AGING** |
| `age > max_acceptable_age` | **STALE** — the result is also downgraded to `DEGRADED` |
| no usable reference | **UNAVAILABLE** |

Declared policy per source (demo values shown; live providers declare their own):

| Source | Update cycle | Max acceptable age |
|---|---|---|
| IMD | 3 h (nowcast cadence) | 12 h (a bulletin stands until superseded) |
| INCOIS | 12 h | 24 h |
| MOSDAC | 24 h | 72 h |
| Open-Meteo forecast | 1 h | 3 h |
| Open-Meteo marine | 3 h | 12 h |

**A cache hit never changes any of this.** The cached object keeps its original
`retrieved_at` and `issued_at`, freshness is recomputed on read, and a cached *live*
reading is relabelled `CACHED_LIVE` — never left as `LIVE`. There is a test for exactly
that.

## Conflict records

When two sources disagree materially, both claims are preserved:

```python
Conflict(
    variable="wind_speed_10m",
    severity="MATERIAL",
    claims=[
        {"source": "IMD", "value": 53.9, "freshness": "AGING", "evidence_id": "..."},
        {"source": "INCOIS", "value": 34.8, "freshness": "FRESH", "evidence_id": "..."},
    ],
    spread=19.1, tolerance=11.1,
    winning_source="IMD",
    resolution="used IMD as the documented authority for atmosphere variables; "
               "values were not averaged",
    confidence_penalty=0.24,
)
```

See [reliability.md](reliability.md) for the resolution policy.
