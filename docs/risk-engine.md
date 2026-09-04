# Risk engine

## What it guarantees

| Property | How |
|---|---|
| **Deterministic** | Same evidence in, same assessment out. Asserted by test. |
| **Explainable** | Every band comes from a named rule with the exact value, threshold and comparator that triggered it, plus the evidence ids used. |
| **LLM-free** | No model is consulted. A language model never chooses a risk level in ORCA. |
| **Fails safe** | Missing or stale required evidence produces `INSUFFICIENT_DATA` with the advisory explicitly withheld. "Unknown" never becomes "safe". |
| **Tunable** | The entire policy is `backend/app/safety/rules.yaml`. Diffable, reviewable by a domain expert who does not read Python, changeable without a redeploy. |

## Honesty note — read this before using it operationally

**The thresholds are indicative.** They are informed by the shape of common small-craft
advisory practice and by the Beaufort and Douglas scales. They are **not** a reproduction
of any authority's official criteria, and ORCA is not a certified navigation or
maritime-safety system.

An operational deployment must replace these numbers with thresholds agreed with the
relevant authority — IMD, INCOIS, the state fisheries department, the Coast Guard — for
each activity and vessel class. That is a one-file change, and it is the single most
important thing to do before anyone acts on an ORCA answer.

## The model

```
for each rule in the activity profile:
    factor_level = highest band whose threshold the value has crossed
    contribution = weight × (level_rank / 3)

risk_score = 100 × Σ contribution / Σ weight

risk_level = max(factor_level)                         then escalations:
             ≥3 non-LOW factors and level == MODERATE  → HIGH
             ≥3 HIGH+ factors and level == HIGH        → CRITICAL
             authority advisory floor                  → at least that band
```

Thresholds are multiplied by a **vessel factor** — a canoe capsizes in conditions a
trawler ignores:

| Vessel | Factor |
|---|---|
| canoe | 0.75 |
| small motorised | 1.00 |
| mechanised | 1.35 |
| large | 1.85 |

Inverted rules (visibility: lower is worse) invert the factor too, so a larger vessel
tolerates lower visibility rather than requiring more of it.

## Default profile — small-boat fishing

| Rule | Variable | MODERATE | HIGH | CRITICAL | Weight | Required |
|---|---|---|---|---|---|---|
| Significant wave height | `wave_height_significant` | 1.5 m | 2.5 m | 3.5 m | 30 | **yes** |
| Wind speed | `wind_speed_10m` | 20 km/h | 34 km/h | 50 km/h | 25 | **yes** |
| Swell height | `swell_height` | 1.5 m | 2.2 m | 3.0 m | 12 | no |
| Wind gusts | `wind_gust_10m` | 30 km/h | 45 km/h | 62 km/h | 10 | no |
| Visibility (≤) | `visibility` | 5000 m | 2000 m | 1000 m | 10 | no |
| Thunderstorm probability | `thunderstorm_probability` | 40 % | 60 % | 80 % | 8 | no |
| Rainfall | `precipitation` | 7 mm | 15 mm | 30 mm | 5 | no |

Other profiles inherit and override: `fishing_mechanised` roughly doubles the wave and
wind bands; `swimming` roughly halves them and adds a surface-current rule;
`cargo_transit` raises them substantially. `generic`, `patrol`, `tourism`, `diving` and
`research` inherit from the closest fit.

## Authority warnings are facts, not inputs

An issued warning is not re-scored. It sets a **floor**:

| Advisory severity | Minimum risk level |
|---|---|
| severe | CRITICAL |
| warning | HIGH |
| advisory / watch | MODERATE |

If IMD says "fishermen advised not to venture into the sea", ORCA does not get to
disagree because the numbers looked survivable.

## Confidence

```
start 0.92
  − 0.30  per missing REQUIRED variable
  − 0.06  per missing optional variable
  − 0.18  if any evidence is STALE
  − 0.06  if evidence is merely AGING
  − 0.12  per unavailable source
  − the conflict penalty for each disagreeing variable
```

Below `0.35`, the advisory is withheld entirely.

## Gating — the part that matters most

| Situation | `decision_status` | What the user is told |
|---|---|---|
| All required evidence present and current | `ADVISORY_ISSUED` | the verdict |
| Required evidence is stale | `ADVISORY_DEGRADED` | verdict + "verify against the current official advisory" |
| A required variable is missing | `ADVISORY_WITHHELD` | `INSUFFICIENT_DATA` + "treat this as unknown, not as safe" |
| Confidence below floor | `ADVISORY_WITHHELD` | "too little reliable data to give a recommendation" |

Demonstrate it:

```bash
ORCA_DEMO_FAIL_SOURCES=INCOIS python -m app.tools.demo --id d1
# → wave height missing → INSUFFICIENT_DATA → ADVISORY_WITHHELD
```

## Output

```python
RiskAssessment(
    risk_level, risk_score, decision_status,
    factors=[RiskFactor(..., evidence_ids=[...], rationale="...")],
    dominant_factor, confidence, confidence_drivers,
    warnings, missing_variables, stale_variables, evidence_freshness,
    ruleset_id="orca-marine-v1", ruleset_version="1.0.0",
    activity, gate_reason, disclaimer,
)
```

The ruleset id and version travel with every assessment, so an answer from last week can
be reproduced against the ruleset that produced it.

## Worked example

Query: *"Is it safe to go fishing from Kochi tomorrow at 7 AM?"*, demo mode, September
(southwest monsoon), small motorised boat.

```
Wind speed          34.8 km/h  >= 34 km/h   → HIGH       (IMD)     weight 25 → 16.67
Wind gusts          51.7 km/h  >= 45 km/h   → HIGH       (IMD)     weight 10 →  6.67
Wave height          2.08 m    >= 1.5 m     → MODERATE   (INCOIS)  weight 30 → 10.00
Swell height         1.69 m    >= 1.5 m     → MODERATE   (INCOIS)  weight 12 →  4.00
Thunderstorm prob      61 %    >= 60 %      → HIGH       (IMD)     weight  8 →  5.33
Visibility          12570 m    (no band)    → LOW        (IMD)     weight 10 →  0.00
Rainfall             7.23 mm   >= 7 mm      → MODERATE   (IMD)     weight  5 →  1.67

risk_score  = 100 × 44.34 / 100 = 44.3
max factor  = HIGH
advisory floor from IMD thunderstorm warning = HIGH
→ HIGH, ADVISORY_ISSUED, confidence 0.92
```

Every one of those seven numbers has an evidence row, and every row has a source, an issue
time and a freshness verdict.
