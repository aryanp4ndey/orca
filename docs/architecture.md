# Architecture

## The pipeline

```
                    natural language (en / hi / ml / ta)
                                  │
        ┌─────────────────────────▼─────────────────────────┐
        │  NLU (deterministic, ~0.5 ms, no network)         │
        │  language · intent · activity · vessel · place    │
        │  · time.  LLM fallback only if confidence is low  │
        └─────────────────────────┬─────────────────────────┘
                                  │
        ┌─────────────────────────▼─────────────────────────┐
        │  Conversation context                             │
        │  inherit unstated fields; the stated one wins      │
        └─────────────────────────┬─────────────────────────┘
                                  │
        ┌─────────────────────────▼─────────────────────────┐
        │  Planner: intent → capability DAG                 │
        │  and an explicit reason for every capability it    │
        │  chose NOT to run                                  │
        └─────────────────────────┬─────────────────────────┘
                                  │
        ┌─────────────────────────▼─────────────────────────┐
        │  Orchestrator: dependency waves                   │
        │                                                    │
        │   wave 0   geospatial                             │
        │   wave 1   weather ‖ ocean ‖ hazard ‖ satellite    │
        │   wave 2   risk                                    │
        │   wave 3   response                                │
        └─────────────────────────┬─────────────────────────┘
                                  │
        ┌─────────────────────────▼─────────────────────────┐
        │  Provider registry                                │
        │  quantised cache → in-flight de-dup → timeout →   │
        │  retry → circuit breaker → normalise → freshness  │
        └─────────────────────────┬─────────────────────────┘
                                  │
              IMD ──┐   INCOIS ──┐   MOSDAC ──┐   GIS ──┐
                    └───────┬────┴────────────┴─────────┘
                            │  (concurrent)
        ┌───────────────────▼───────────────────────────────┐
        │  Evidence ledger  +  fusion / conflict resolution  │
        │  one value per variable, attributed, never averaged│
        └───────────────────┬───────────────────────────────┘
                            │
        ┌───────────────────▼───────────────────────────────┐
        │  Deterministic risk engine (rules.yaml)           │
        │  level · score · factors · confidence · gate      │
        └───────────────────┬───────────────────────────────┘
                            │
        ┌───────────────────▼───────────────────────────────┐
        │  Response agent → grounding check → answer        │
        │  a number not in the evidence cannot be emitted    │
        └───────────────────┬───────────────────────────────┘
                            │
        structured JSON: answer · risk · factors · evidence ·
        sources · conflicts · warnings · confidence ·
        freshness · visualisations · latency · trace
```

## Layering

| Layer | Package | Responsibility |
|---|---|---|
| HTTP | `app/api`, `app/main.py` | Routing, validation, compression, request ids. No business logic. |
| Services | `app/services` | Composition root, the query pipeline, direct capability endpoints. |
| Reasoning | `app/reasoning` | NLU, conversation context, orchestration, fusion, freshness, evidence. |
| Agents | `app/agents` | Nine specialists, each with one responsibility and its own deadline. |
| Safety | `app/safety` | The deterministic risk engine and its ruleset. |
| Geo | `app/geo` | Geodesy, polygons, gazetteer, boundary layers. All deterministic. |
| Providers | `app/providers` | Source adapters. Demo and live behind one interface. |
| Cache / observability / config / i18n / llm | | Cross-cutting, all injected, none global. |

The rule that keeps this honest: **agents depend on canonical variables, never on an
upstream API's response shape.** `wave_height_significant` in metres is the contract;
whether it came from an INCOIS ERDDAP grid, an Open-Meteo JSON array or a demo fixture is
the provider's problem and the evidence row's disclosure.

---

## Technology choices and their trade-offs

### FastAPI + Pydantic v2 + asyncio
Chosen. Every agent hand-off, every provider envelope and every API response is a
Pydantic model, so a contract violation is a validation error at the boundary rather than
a wrong number three layers later. Async is not optional here: the entire latency story
is concurrent I/O.

### A custom orchestrator instead of LangGraph
**Trade-off taken deliberately.** LangGraph gives you a graph runtime, persistence and a
large ecosystem. What we needed was: per-agent deadline budgets, fan-out with partial
results, dropping optional steps when the budget runs short, and a trace a judge can read
in ten seconds. Getting those out of a general graph runtime means fighting its
scheduler; writing them directly is about 120 lines (`app/reasoning/orchestrator.py`) and
we own every millisecond. We still build a real DAG — `ExecutionPlan.waves()` is a
topological grouping, and the routing table is data, not control flow.

**What we give up:** durable graph state across process restarts, and a lot of
off-the-shelf integrations. Neither is needed for a marine query that must complete in
under a second.

### The LLM is optional and off the critical path
**This is the single most important design decision in the system**, and it is the direct
answer to the latency problem the judges raised. A marine query has about a dozen shapes.
Rule-based NLU resolves intent, language, activity, vessel, place and time in ~0.5 ms with
no network call. The model is consulted only when that returns low confidence, and only to
fill the same typed fields. Optionally it may re-phrase an explanation whose facts are
handed to it verbatim — and if its output contains a number that is not in the evidence,
the output is discarded.

**What we give up:** graceful handling of genuinely novel phrasings without a model
configured. We accept that: the fallback exists, and a clarifying question is a better
failure than a 4-second wait.

### Pure-Python WGS84 geodesy instead of Shapely / PostGIS
Vincenty inverse distance, ray-cast point-in-polygon, segment distance, corridor
densification — all closed-form, in `app/geo/`, unit-tested against known values. They run
in microseconds with no database round-trip and no native dependency, so `git clone &&
uvicorn` works on any machine.

**What we give up:** spatial indexing, projected-CRS operations, and topology operations
(union, buffer, overlay). Once the boundary datasets are authoritative national polygons
rather than a few dozen zones, an R-tree or PostGIS wins. `app/geo/` is the seam:
`GeospatialAgent` calls functions, not a database, so swapping the implementation touches
one package.

*(There is also a practical reason worth stating: the environment this prototype was
built in had no package registry access, so Shapely/GEOS could not have been installed or
tested there. A geospatial layer we could not run is worse than one we could.)*

### In-process cache by default, Redis behind the same interface
A hackathon prototype must start with one command. `Cache` is an ABC;
`ORCA_CACHE_BACKEND=redis` swaps the implementation. Both re-evaluate freshness on read,
so a cache hit can make an answer faster but never newer.

### PostgreSQL / PostGIS: deliberately not yet
Nothing in the current prototype needs durable relational state. Conversation context is
per-session and disposable; evidence is per-query. Adding a database now would add a
container, a migration story and a failure mode in exchange for nothing. It becomes right
when we store alert subscriptions, user vessels, or a PFZ history — and `docs/limitations.md`
says so.

---

## Where the intelligence lives, and where it does not

| Done by the LLM (or rules that stand in for it) | Done by deterministic code |
|---|---|
| Which intent is this? | Which capabilities that intent needs |
| What activity and vessel? | Coordinates, distances, bearings |
| Which place and which time? | Point-in-polygon, geofences, maritime bands |
| How should this be phrased, in which language? | Unit conversion and normalisation |
| | Freshness classification |
| | Source conflict resolution |
| | Risk thresholds, scores and gating |
| | Whether an advisory may be issued at all |

The second column is the reason ORCA can be argued with. Every entry in it is a function
you can read, a rule you can diff, and a test that pins it.
