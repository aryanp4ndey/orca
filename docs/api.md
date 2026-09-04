# API contract

Base URL: `/api/v1`. Live schema and try-it console at `/docs`; raw OpenAPI at
`/openapi.json`. Only endpoints that are actually implemented are exposed.

Everything is JSON. Responses over 800 bytes are gzipped. Every response carries
`x-request-id` and `x-response-time-ms` headers.

---

## `POST /api/v1/query` — the conversational door

```jsonc
{
  "query": "Is it safe to go fishing from Kochi tomorrow at 7 AM?",
  "session_id": "s_2e7241b7ab",   // optional; carry it back for multi-turn context
  "language": "ml",               // optional; overrides auto-detection
  "lat": 9.9312, "lon": 76.2125,  // optional device position
  "activity": "fishing_small_boat",
  "vessel": "small_motorised",
  "low_bandwidth": false,         // drops map geometry, keeps the answer identical
  "include_trace": true
}
```

Response (abridged — full schema at `/docs`):

```jsonc
{
  "query_id": "q_8a3f21c04b7e",
  "session_id": "s_2e7241b7ab",
  "answer": "For small-boat fishing from Kochi, tomorrow 07:00 IST:\nNot advisable...",
  "answer_language": "en",
  "data_origin": "DEMO",              // LIVE | CACHED_LIVE | DEMO | MIXED | COMPUTED
  "demo_mode": true,

  "intent":   { "value": "marine_safety", "confidence": 0.93,
                "resolver": "rules", "inherited": [], "scores": {...} },
  "location": { "name": "Kochi", "point": {"lat": 9.9312, "lon": 76.2125},
                "resolver": "gazetteer", "confidence": 0.95,
                "distance_to_coast_km": 6.0, "source_dataset": "orca-gazetteer-in-coastal@0.1.0" },
  "time":     { "target": "2026-09-03T01:30:00Z", "window_start": "...",
                "window_end": "...", "is_explicit": true, "horizon_hours": 20.0,
                "resolver": "rules" },
  "activity": "fishing_small_boat",

  "risk": {
    "risk_level": "HIGH", "risk_score": 44.3,
    "decision_status": "ADVISORY_ISSUED",
    "confidence": 0.92, "confidence_drivers": [...],
    "factors": [ { "factor_id": "wind_speed", "variable": "wind_speed_10m",
                   "label": "Wind speed", "value": 34.8, "unit": "km/h",
                   "threshold": 34.0, "comparator": ">=", "level": "HIGH",
                   "weight": 25, "contribution": 16.67,
                   "evidence_ids": ["ev_5c1a9b2f7d31"],
                   "rationale": "Wind speed 34.8 km/h >= 34 km/h -> HIGH (IMD)" } ],
    "missing_variables": [], "stale_variables": [],
    "ruleset_id": "orca-marine-v1", "ruleset_version": "1.0.0",
    "gate_reason": null, "disclaimer": "ORCA is a decision-support prototype..."
  },

  "factors":  [ /* display-ready, localised labels */ ],
  "evidence": [ /* every Evidence row - see docs/evidence.md */ ],
  "sources":  [ { "source": "IMD", "provider": "imd_demo", "origin": "DEMO",
                  "status": "OK", "freshness": "AGING", "latency_ms": 2.79,
                  "retrieved_at": "...", "cache_hit": false, "attribution": "..." } ],
  "conflicts": [ /* see docs/reliability.md */ ],
  "warnings":  [ "MOSDAC: ocean-colour retrieval unavailable under cloud" ],
  "confidence": 0.92,

  "freshness": { "overall": "AGING", "oldest_evidence_age_seconds": 18660.0,
                 "per_source": { "IMD": "AGING", "INCOIS": "FRESH" },
                 "stale_sources": [] },

  "visualizations": {
    "markers": [ { "id": "query_point", "kind": "query", "lat": .., "lon": ..,
                   "label": "Kochi", "risk_level": "HIGH" } ],
    "layers":  [ { "layer_id": "...", "name": "...", "kind": "polygon",
                   "geojson": { "type": "Feature", "geometry": {...},
                                "properties": { "authoritative": false, ... } },
                   "style_hint": "restricted", "source": "demo_restricted_areas" } ],
    "charts":  [ { "id": "risk_factors", "kind": "bar", "series": [...] } ],
    "timeline":[ { "evidence_id": "...", "source": "IMD", "variable": "...",
                   "issued_at": "...", "valid_time": "...", "freshness": "..." } ],
    "cards":   [ { "kind": "risk", ... }, { "kind": "source", ... } ]
  },

  "latency": { "total_ms": 6.77, "nlu_ms": 0.51, "planning_ms": 0.62,
               "agents_ms": 3.9, "providers_ms": 1.81, "risk_ms": 0.9,
               "response_ms": 0.29, "per_agent_ms": {...}, "per_provider_ms": {...},
               "parallel_saving_ms": 7.14, "llm_ms": 0.0 },

  "trace": { "plan": { "waves": [["geospatial"], ["weather","ocean","hazard","satellite"],
                                ["risk"], ["response"]],
                       "skipped": { "pfz": "no fishing-zone question was asked" } },
             "spans": [...], "cache": { "hits": 7, "misses": 0 }, "notes": [...] },

  "disclaimer": "...",
  "generated_at": "2026-09-02T05:41:12Z",
  "follow_up_suggestions": ["What about 5 PM?", "Where is the nearest fishing zone?"]
}
```

---

## Other endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Liveness plus per-source status, agent list, LLM state, cache stats, circuit breakers, config warnings |
| `GET` | `/api/v1/marine-status` | `?place=` or `?lat=&lon=`, optional `?at=`, `?activity=`, `?vessel=` — structured conditions and risk without a sentence |
| `GET` | `/api/v1/pfz` | `?place=` or `?lat=&lon=` — PFZ advisories with bearing, distance, validity and geometry |
| `GET` | `/api/v1/alerts` | `?place=` or `?lat=&lon=` — warnings in force plus hazard zones |
| `POST` | `/api/v1/route-risk` | `{start, end, depart_at, speed_knots, activity, vessel, samples}` — per-segment passage risk |
| `GET` | `/api/v1/evidence/{query_id}` | Full evidence chain, conflicts and trace for an earlier answer |
| `GET` | `/api/v1/sources` | Every source: role, access mechanism, verification status, priority order, breaker state |
| `GET` | `/api/v1/agents` | Every agent's contract, plus the full routing table with reasons |
| `GET` | `/api/v1/map-layers` | Boundary layers with provenance and authority flags |
| `GET` | `/api/v1/languages` | Answer languages available |
| `GET` | `/api/v1/demo/scenarios` | The rehearsed demo queries and the failure switches |
| `GET` | `/` | Service banner |

---

## Notes for the frontend team

**Screen 1 — Conversational.** `POST /api/v1/query`, echo `session_id` on every subsequent
turn. Render `answer` as-is (it is already localised and already carries its caveats), then
`risk`, then `factors`. `follow_up_suggestions` are localised chips.

**Screen 2 — Map.** `visualizations.markers` and `visualizations.layers`. Every layer's
`properties.authoritative` flag must drive a visible distinction: illustrative layers are
not official boundaries and the UI must not let them look like they are.

**Screen 3 — Evidence / reasoning panel.** `visualizations.timeline` is chronological and
ready to render. `trace.plan.waves` shows which agents ran concurrently;
`trace.plan.skipped` shows what was not run and why. For an earlier answer, use
`GET /api/v1/evidence/{query_id}` rather than re-asking.

**Screen 4 — Alerts.** `GET /api/v1/alerts` or the `advisory:*` rows in `evidence`.
Severity is one of `none | watch | advisory | warning | severe`.

**Screen 5 — Risk and source cards.** `visualizations.cards` is pre-shaped:
`kind: "risk"` and `kind: "source"`. Source cards carry `origin`, `freshness`,
`cache_hit`, `latency_ms` and `attribution` — please show `origin` and `freshness`; the
whole honesty story depends on the user being able to see them.

**Low-bandwidth mode.** Send `low_bandwidth: true` when the client detects a slow
connection. Layers and geometry are dropped; the answer, risk, factors, sources and cards
are byte-identical.

**Contract stability.** Fields are added, not removed or repurposed. `data_origin`,
`freshness`, `sources[].origin` and `risk.decision_status` are the four fields the UI must
never silently ignore.

## Errors

| Status | Meaning |
|---|---|
| `400` | Missing required query parameters (e.g. `marine-status` with no location) |
| `404` | Unknown `query_id` in the evidence ledger (it holds the most recent 200) |
| `422` | Request failed validation, or a typed `OrcaError` — body carries `{error: {code, message, context}, user_message}` |
