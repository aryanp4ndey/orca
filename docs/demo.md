# Demo guide

## The point of this document

The mock drill exposed a real problem: a presenter froze on the technical slide, and the
demo depended on them. So the demo is a **command**, not a memorised sequence. Anyone on
the team can run it, it prints the same thing every time, and it explains itself.

```bash
cd backend
python -m app.tools.demo                 # all 11 scenarios, in order
python -m app.tools.demo --id d1         # just the flagship
python -m app.tools.demo --failures      # what happens when sources die
```

Or drive the real UI at **`http://localhost:8000/app/`** — that is what a judge should
see. (`http://localhost:8000/docs` is the API console; useful for showing the contract,
but it is not the product.)

---

## Before you start

```bash
docker compose up --build          # or: cd backend && uvicorn app.main:app
curl -s localhost:8000/api/v1/health | head -20
```

Check three things on the health output: `"status": "ok"`, `"demo_mode": true`, and the
provider list. If a judge asks what is real, that endpoint is the answer.

**Demo mode is on by default and that is deliberate.** External sources fail during
judging. Demo mode is deterministic, physically coherent, and labelled `DEMO` from the
provider through to the sentence the user reads. Say that out loud — it is a strength, not
an apology. Then show `ORCA_DEMO_MODE=false` and `python -m app.tools.verify_live` to
prove the live path exists.

---

## Scenario 1 — Fishing safety *(the flagship; make this one perfect)*

> **"Is it safe to go fishing from Kochi tomorrow at 7 AM?"**

What to point at, in this order:

1. **The answer.** A verdict, the reasons with numbers and units, the warnings in force,
   the sources, the retrieval time, the caveats, the disclaimer.
2. **`intent`** — `marine_safety`, confidence 0.93, resolver `rules`. *"No language model
   was involved in understanding that. It took half a millisecond."*
3. **`trace.plan.waves`** — `[[geospatial], [weather, ocean, hazard, satellite], [risk],
   [response]]`. *"Four sources, one round-trip."*
4. **`trace.plan.skipped`** — *"and here is why it did not call the PFZ agent."*
5. **`risk.factors`** — each with value, threshold, comparator, level and `evidence_ids`.
   *"Wind 34.8 km/h against a 34 km/h threshold. That is a rule in a YAML file, not a
   model's opinion."*
6. **`evidence`** — pick one row. Source, dataset, issue time, forecast time, retrieval
   time, age, freshness. *"Every number in that answer has one of these."*
7. **`latency.total_ms`** — single digits. *"Our earlier prototype took four to five
   seconds. The benchmark in the repo shows where that went."*

## Scenario 2 — Multi-turn

> **"What about 5 PM?"**  *(same `session_id`)*

`intent.inherited` shows `["location", "activity", "intent"]`. The location, activity and
intent were carried over; the time was stated and overrode. *"The user did not have to
repeat themselves, and we can show exactly what was inherited rather than assumed."*

## Scenario 3 — Sea condition

> **"What is the sea condition near Kochi?"**

A different plan: ocean-led, no hazard agent. Shows the routing is real.

## Scenario 4 — Potential Fishing Zone

> **"Where is the nearest Potential Fishing Zone today?"** *(with device position)*

Bearing, distance, depth, validity window, and the basis (SST front, chlorophyll
gradient). Say plainly: **the PFZ coordinates here are demo data.** INCOIS publishes PFZ
as bulletins and we could not verify a machine-readable API, so the agent, the geometry,
the distance maths and the validity handling are real and the coordinates are labelled
`DEMO`. That is exactly the kind of thing judges reward you for saying first.

## Scenario 5 — Hazard check

> **"Are there any cyclone or lightning warnings near my location?"**

Authority advisories are quoted verbatim and not re-scored. Note the wording when nothing
is found: *"No warning was found in force **in the sources ORCA could reach**"* — never
"there is no warning".

## Scenario 6 — Analytical

> **"Why is fishing potential lower here between 5 PM and 10 PM?"**

Two comparison windows are parsed and retrieved separately. Then ORCA explicitly declines
to claim causality: *"it does not claim a causal explanation for fishing outcomes — that
would need catch data and biological evidence it does not have."* **This is the single
best slide in the demo.** A system that knows what it cannot conclude is the one a
scientist trusts.

## Scenario 7 — Areas to avoid

> **"What areas should I avoid?"**

Geofencing with honest labelling: every zone says `(illustrative layer, confirm
officially)`. `GET /api/v1/map-layers` shows `authoritative: false` on every shipped
layer.

## Scenario 8 — Route risk

> **"Show the safest route from Kochi to Mangaluru"**

Corridor sampling, per-segment risk, hazardous segments named. Then read the disclaimer
out loud: *"not a navigational route: it does not account for depth, traffic separation,
notices to mariners or obstacles."*

## Scenarios 9–11 — Multilingual

> **"Kal subah 7 baje Kochi se fishing ke liye jaana safe hai?"** (romanised Hindi)
> **"നാളെ രാവിലെ 7 മണിക്ക് കൊച്ചിയിൽ നിന്ന് മീൻപിടിക്കാൻ പോകുന്നത് സുരക്ഷിതമാണോ?"** (Malayalam)
> **"நாளை காலை 7 மணிக்கு சென்னையிலிருந்து மீன்பிடிக்கச் செல்வது பாதுகாப்பானதா?"** (Tamil)

Same intent, same activity, same resolved time, same risk verdict — different words. Note
the Malayalam case suffix: `കൊച്ചിയിൽ` is "in Kochi", and the gazetteer handles the
agglutination. There is a test asserting all four languages produce identical internal
representations and identical risk scores.

---

## Failure demo — `python -m app.tools.demo --failures`

This is where a technically strong panel is won.

| Switch | What to say |
|---|---|
| `ORCA_DEMO_FAIL_SOURCES=INCOIS` | *"The wave forecast is gone. Watch: `INSUFFICIENT_DATA`, `ADVISORY_WITHHELD`, and the answer says treat this as unknown, not as safe. It did not fall back to another source's wave height, because there isn't one, and it did not guess."* |
| `ORCA_DEMO_FAIL_SOURCES=MOSDAC` | *"Optional source. Answer proceeds, gap stated, verdict unchanged."* |
| `ORCA_DEMO_STALE_SOURCES=IMD,INCOIS` | *"Data is old. Advisory degraded, confidence cut, user told to check the official advisory. It never presents stale as current."* |
| `ORCA_DEMO_CONFLICT=true` | *"IMD and INCOIS disagree on wind. Both claims are reported, IMD wins because it is the documented authority for atmosphere, confidence drops, and we never average — averaging would invent a number nobody published."* |
| `ORCA_DEMO_SCENARIO=pre_cyclone` | *"Severe conditions. The authority warning sets a CRITICAL floor; the numbers do not get to argue."* |
| `ORCA_DEMO_SLOW_SOURCES=INCOIS:4000` | *"A source hangs. Bounded by the timeout, no retry — retrying a slow source spends the user's budget asking the same slow thing again."* |

---

## If something goes wrong live

| Symptom | Do this |
|---|---|
| Server won't start | `python -m app.tools.demo --id d1` needs no server |
| A scenario looks odd | `ORCA_DEMO_SCENARIO=normal` and re-run |
| Someone asks for live data | `python -m app.tools.verify_live` — it reports honestly, including failure |
| Laptop dies | the recorded run is the backup; every scenario is reproducible from this file |
| Judge asks something technical | [judge-qa.md](judge-qa.md) |

---

## Presentation notes

**Slide 2** should carry the prototype link and/or QR plus a short recorded demo, per the
mock-judging feedback. Record `python -m app.tools.demo` and the `--failures` run: they
are deterministic, so the recording and the live run will match.

**The three sentences worth memorising:**

1. *"The AI decides what data to ask for. The authorities decide what is true."*
2. *"Every number in the answer has an evidence row with a source and a timestamp — here."*
3. *"When we don't know, we say we don't know. We never turn 'unknown' into 'safe'."*

**One thing not to say:** do not call demo data "real-time". The system is careful about
this everywhere; the presenter has to be too.
