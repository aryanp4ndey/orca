# Technical Q&A

Straight answers, each with the place in the code or the command that backs it up.

---

### "Why is this multi-agent? Why not one LLM?"

Three reasons, in order of importance.

**Correctness.** A marine safety answer needs a wave forecast from INCOIS, a wind forecast
and a warning bulletin from IMD, a point-in-polygon test, a unit conversion and a threshold
comparison. Exactly one of those is a language task. Handing the rest to a model means
handing it the chance to be fluently wrong about a number someone will go to sea on.

**Latency.** Separate agents with declared dependencies can run concurrently. One model
call is one serial round-trip, and it was 4–5 seconds in our earlier prototype. The
benchmark shows 1752 ms → 426 ms from the fan-out alone.

**Failure isolation.** Each agent has its own deadline, its own sources and its own defined
failure behaviour, so one dead source degrades one part of the answer instead of failing
the whole request.

`GET /api/v1/agents` prints the full contract for all nine.

---

### "What exactly does each agent do?"

| Agent | Responsibility | On failure |
|---|---|---|
| `planner` | Understand the query, resolve place and time, merge context, choose capabilities | Falls back to rules; asks a clarifying question |
| `geospatial_agent` | Marine point, distance-to-coast, maritime band, zones, distances, bearings | Fails; downstream retrieval is skipped rather than guessed |
| `weather_agent` | Wind, gusts, rain, visibility, cloud, temperature, convective potential | `PARTIAL`; a total loss removes a required risk variable |
| `ocean_agent` | Wave height, period, direction, swell, currents, SST | `PARTIAL`; a total loss withholds the advisory |
| `satellite_agent` | SST, chlorophyll, cloud from the last pass | Always optional; never blocks an answer |
| `pfz_agent` | PFZ advisories with bearing, distance, validity, basis | Says none was available; never synthesises coordinates |
| `hazard_agent` | Cyclone, squall, thunderstorm, high-wave, swell-surge advisories; restricted zones | Says warnings could not be checked; absence is never reported as "no warning" |
| `route_agent` | Corridor sampling and per-segment risk | Marks unassessed segments; never reports a corridor as clear |
| `risk_agent` | Deterministic scoring, gating, confidence | `INSUFFICIENT_DATA`, advisory withheld |
| `response_agent` | Grounded explanation in the user's language | Falls back to templates if the LLM misbehaves |

Full generated table: [agents.md](agents.md).

---

### "How do agents communicate?"

Typed Pydantic models, never free text. `AgentRequest(request_id, capability, context,
point, deadline_ms, depends_on, options)` in; `AgentResponse(agent, capability, status,
data, evidence, warnings, confidence, source_status, processing_time_ms, error)` out. A
contract violation is a validation error at the boundary, not a wrong number three layers
later.

---

### "How do you prevent hallucination?"

Four mechanisms, layered:

1. **The LLM never retrieves.** It cannot produce a measurement because it is never asked
   for one.
2. **Everything numeric comes from a provider or from deterministic code**, and lands in
   the evidence ledger with a source and a timestamp.
3. **The grounding check.** Before any answer is returned, every numeric token in it is
   matched against the ledger, the ruleset thresholds, ORCA's own computations and the
   timestamps being reported. `app/agents/response/grounding.py`.
4. **If the model's phrasing fails that check, it is discarded** and the deterministic
   template answer is used instead.

---

### "What happens if an API fails?"

Depends on whether it carried a *required* variable.

- Optional (MOSDAC): answer proceeds, gap stated, verdict unchanged.
- Required (INCOIS wave height): `INSUFFICIENT_DATA`, `ADVISORY_WITHHELD`, and the answer
  says *"treat this as unknown, not as safe"*.

`ORCA_DEMO_FAIL_SOURCES=INCOIS python -m app.tools.demo --id d1` shows it.
Providers never raise into agents — they return a typed status.

---

### "What happens if the internet is slow?"

We can't make the link faster; we make everything else small and bounded. Per-provider
timeout, no retry on timeout (a slow source is slow, not flaky), a circuit breaker, gzip,
a `low_bandwidth` flag that drops map geometry, a quantised cache, and an offline
gazetteer so place resolution needs no network at all. Numbers in
[performance.md](performance.md).

---

### "What happens if data is stale?"

Freshness is measured against **issue time**, not valid time — a forecast issued 30 hours
ago for tomorrow morning is stale however future-dated it is. `STALE` downgrades the
provider result to `DEGRADED`, the advisory to `ADVISORY_DEGRADED`, cuts confidence by
0.18, and adds a warning telling the user to check the current official advisory.
A cache hit never resets any of that.

---

### "What happens if sources disagree?"

Both claims are kept and attributed. The spread is measured against a per-variable
tolerance. If it is material, ORCA takes the value from the documented authority for that
variable's domain — IMD for atmosphere, INCOIS for ocean — **never an average**, because
an average is a number nobody published. Confidence drops in proportion, and the answer
says so. `ORCA_DEMO_CONFLICT=true` demonstrates it.

---

### "How do you know the recommendation is grounded?"

`GET /api/v1/evidence/{query_id}` returns every evidence row, every conflict, and the full
execution trace. Each risk factor lists the `evidence_ids` it used, and a test asserts
those ids exist in that query's ledger.

---

### "What is actually real-time?"

Nothing in demo mode, and the system says so in the answer text, in `data_origin`, in
every source card and on `/api/v1/health`.

In live mode: Open-Meteo is hourly and verified end to end. IMD's API is real and its
endpoints are verified, but it requires **IP whitelisting we do not have**, so it reports
`NOT_CONFIGURED` until a whitelisted host supplies the field mapping. INCOIS ERDDAP is
public and its URL grammar is verified; dataset ids need one discovery run. MOSDAC is an
**order-based archive**, not a real-time API — which is why the satellite agent is always
optional. Details in [providers.md](providers.md).

---

### "What is deterministic?"

Coordinates, distances, bearings, point-in-polygon, geofences, maritime bands, unit
conversion, freshness classification, conflict resolution, risk thresholds, risk scores,
confidence, and whether an advisory may be issued at all. The intent rules are
deterministic too. The only non-deterministic component in the whole system is an optional
LLM that is off by default and cannot influence any of the above.

---

### "Why IMD? Why INCOIS? Why MOSDAC?"

Because they do different jobs and are not interchangeable. IMD is the atmospheric and
warning authority; INCOIS is the ocean-state and PFZ authority; MOSDAC is the satellite EO
archive. Waves come from INCOIS, warnings from IMD, chlorophyll from MOSDAC — and the
conflict resolver encodes exactly that priority per variable domain. Using one where
another belongs would be a correctness bug, not a shortcut.

---

### "How are geospatial calculations performed?"

Closed-form WGS84 geodesy in pure Python: Vincenty inverse for distance, spherical
formulae for bearing and destination, ray casting for point-in-polygon, local
equirectangular projection for point-to-segment distance. All in `app/geo/`, all unit
tested against known values. **No language model performs coordinate arithmetic anywhere
in ORCA.** The planner decides *which* spatial question to ask; `app/geo/` answers it.

Trade-off and the PostGIS migration path: [architecture.md](architecture.md).

---

### "How do you support regional languages?"

The internal representation is language-independent. All language-specific strings live in
two files — `app/reasoning/lexicon.py` for understanding and `app/i18n/catalog.py` for
answering. Adding Telugu or Bengali is adding rows, not code.

Understanding covers English, Hindi in Devanagari *and* romanised Hinglish, Malayalam and
Tamil, including Indic case suffixes (`കൊച്ചിയിൽ` → Kochi). There is a test asserting four
languages produce byte-identical intent, place, activity and time, and another asserting
they produce the same risk verdict.

---

### "How does ORCA work for fishermen with limited digital literacy?"

The answer is a short spoken-language paragraph with a verdict first, then reasons with
plain units — not a dashboard. It is available in the user's own language including
romanised typing. The `low_bandwidth` mode keeps the text and drops the map. Follow-up
suggestions are one-tap chips. Multi-turn context means "what about 5 PM?" works without
repeating anything.

Not yet built, and we say so: voice input and output, and an SMS/USSD fallback. The
response is deliberately structured so a text-to-speech layer needs no new backend work.

---

### "How does caching work?"

Position quantised to a 0.25° grid (~27 km, matching typical marine model spacing), time
to the hour, plus the variable set — so two boats a few km apart asking about the same hour
share one upstream call. Identical concurrent requests are collapsed by an in-flight map
(six simultaneous requests → one upstream fetch, asserted by test). Per-source TTLs.
Cached objects keep their original timestamps, freshness is recomputed on read, and cached
live data is relabelled `CACHED_LIVE`. The cache key includes everything that changes the
value — a bug we found and fixed when switching demo scenarios served stale values.

---

### "How did you reduce latency?"

Five levers, all measured: keep the LLM off the critical path (the biggest win), fan out
independent retrieval, quantised cache with de-duplication, selective agent invocation per
intent, and bounded failure. 1752 ms → 426 ms → 4.9 ms. Method and caveats in
[performance.md](performance.md).

---

### "How does this scale?"

The API is stateless apart from an in-process session store and cache, both behind
interfaces with Redis implementations, so horizontal scaling is a config change. The
expensive resource is upstream API quota, not CPU — and grid quantisation plus
de-duplication means N users in one coastal district cost roughly one upstream call per
grid cell per hour, not N calls. IMD explicitly asks clients to cache; we do.

---

### "How do you handle maritime boundaries?"

Carefully, and with a disclaimer we do not hide. ORCA ships a `BoundaryLayer` abstraction
where every layer carries its source, version and an `authoritative` flag. **Every layer
shipped today is flagged `authoritative: false`**, and a test enforces that. The maritime
bands are UNCLOS *distance definitions* applied to an approximate coastal baseline built
from public settlement coordinates — a calculation, not a claim about notified limits.
Authoritative polygons (Marine Regions EEZ, notified restricted areas) drop into
`app/data/boundaries/` and take over.

---

### "How do you calculate risk?"

A versioned, transparent ruleset in `app/safety/rules.yaml`: per-activity thresholds for
each variable across MODERATE/HIGH/CRITICAL, weighted contributions, a vessel-class
multiplier, escalation when several factors fire together, and a floor set by any
authority warning in force. Full walkthrough with a worked example:
[risk-engine.md](risk-engine.md).

---

### "Does ORCA replace official navigation or safety systems?"

No, and it says so in every answer. It is decision support. The route feature is explicitly
risk annotation of a straight-line passage, not routing: it does not account for depth,
traffic separation, notices to mariners or obstacles, and the response says exactly that.

---

### "What is mocked in the prototype?"

Named precisely, in [limitations.md](limitations.md). In short: all marine *values* in demo
mode; PFZ coordinates in every mode (no verifiable machine-readable INCOIS PFZ API);
MOSDAC granule download and product decoding; and the boundary layers, which are
approximations. The agents, planner, orchestrator, evidence layer, freshness layer,
conflict resolver, risk engine, geodesy, cache, resilience layer and API are all real and
tested.

---

### "Could you have done this with a smaller system?"

For one query and one source, yes. The complexity here buys four specific things: agents
that fail independently, sources that are swappable without touching reasoning code, an
evidence chain that makes every claim checkable, and a risk decision that a domain expert
can audit and tune without reading Python. Take any of those away and the system gets
smaller and materially less trustworthy.

---

### "What would you do next, with more time?"

In priority order: get an IMD-whitelisted host and complete the field mapping; run INCOIS
ERDDAP discovery and enable the live ocean provider; replace the illustrative boundary
layers with authoritative datasets; agree real thresholds with a domain authority; add
voice output and an SMS/USSD fallback; add PostGIS once the boundary datasets justify it.
