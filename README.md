# ORCA — Marine EcOsystem Reasoning with Collaborative Agents

**Smart India Hackathon 2026 · Problem statement SIH26176 · Indian Space Research Organisation · Category: Software · Team DRISHTI**

A conversational multi-agent marine intelligence and decision-support platform for Indian
waters. You ask a question in your own language; ORCA works out what data that question
actually needs, fetches it from the right authorities in parallel, checks how old it is,
scores it against a transparent ruleset, and answers with every number traceable back to
the source it came from.

```
"Is it safe to go fishing from Kochi tomorrow at 7 AM?"

  ↓ intent + context      marine_safety · fishing_small_boat · Kochi · 03 Sep 07:00 IST
  ↓ task planning         geospatial → {weather ‖ ocean ‖ hazard ‖ satellite} → risk → response
  ↓ parallel retrieval    IMD, INCOIS, MOSDAC — concurrently, each with its own deadline
  ↓ spatial + temporal    9.9312 N 76.2125 E · 5.6 km offshore · territorial waters
  ↓ evidence validation   29 rows, each with source, dataset, issue time, freshness
  ↓ deterministic risk    HIGH · score 41.7 · confidence 0.92 · ADVISORY_ISSUED
  ↓ explanation           in English, Hindi, Malayalam or Tamil

  6.8 ms, no language model involved
```

---

## The two rules everything else follows from

**1. The AI decides *what data to ask for*. Authoritative sources decide *what is true*.**
A language model in ORCA may classify an ambiguous intent and may phrase an
explanation. It never produces a marine measurement, never computes a distance or a
polygon test, and never chooses a risk level. Those are deterministic code paths, and the
response builder mechanically rejects any answer containing a number that is not in the
evidence ledger.

**2. Provenance is not a feature, it is the data model.** Every value that reaches a user
has an `Evidence` row carrying its source, provider, dataset, variable, unit, observation
time, forecast time, issue time, retrieval time, age and freshness verdict. Ask for the
whole chain behind any answer at `GET /api/v1/evidence/{query_id}`.

A corollary we took seriously: **"I don't know" is never converted into "it's safe."** If
the wave forecast is missing or stale, the advisory is withheld and labelled
`INSUFFICIENT_DATA`, not quietly downgraded to a green light.

---

## Run it

**New to Python backends?** [SETUP.md](SETUP.md) is a step-by-step guide with the exact
commands for Windows, macOS and Linux, and a table of every error you might hit.

**Fastest route:** double-click `scripts\run.bat` (Windows) or run `./scripts/run.sh`
(macOS/Linux). It creates the environment, installs dependencies and starts the server.

```bash
git clone <this repo> && cd orca

# Option A — Docker (one command)
docker compose up --build
# → http://localhost:8000/app/

# Option B — local Python 3.11+
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open **<http://localhost:8000/app/>** — that is the ORCA web client. The API
process serves it, so there is one command, one URL, and no CORS to configure.
There is nothing to `npm install`: the client is dependency-free ES modules
(see [frontend.md](docs/frontend.md) for why that was the right call for a
product aimed at weak coastal links).

| | |
|---|---|
| **App** | <http://localhost:8000/app/> |
| **API console** | <http://localhost:8000/docs> |
| **Health** | <http://localhost:8000/api/v1/health> |

```bash
curl -s localhost:8000/api/v1/health | head -40

curl -s -X POST localhost:8000/api/v1/query \
  -H 'content-type: application/json' \
  -d '{"query":"Is it safe to go fishing from Kochi tomorrow at 7 AM?"}'
```

No API keys are needed. No language model is needed. ORCA starts in **demo mode**, which
uses a deterministic built-in dataset — clearly labelled `DEMO` in every response, in the
answer text, and on the health endpoint. It is never presented as live.

**Want real live data?** Copy `.env.example` to `.env` and set `ORCA_DEMO_MODE=false`.
That single line gives you live wind *and* live waves via Open-Meteo, which needs no key,
no account and no card. [docs/live-data.md](docs/live-data.md) compares every free source
we verified and explains what each one costs you in signup effort.

**Run the whole demo as a script**, so nobody has to remember a sequence:

```bash
cd backend
python -m app.tools.demo               # all 11 scenarios, in order
python -m app.tools.demo --id d1       # just the flagship query
python -m app.tools.demo --failures    # what happens when sources die
python -m app.tools.benchmark          # latency, p50/p90/p95
python -m pytest                       # 272 tests
python ../tools/verify_frontend.py     # drives the UI in a real browser
```

---

## What's actually here

| | |
|---|---|
| **Agents** | 9 real ones — planner, geospatial, weather, ocean, satellite, PFZ, hazard, route, risk, response. Each has a declared responsibility, typed input and output, its own tools, its own deadline enforced by the base class, defined failure behaviour, and its own trace span. `GET /api/v1/agents` prints the lot. |
| **Sources** | IMD (atmosphere + warnings), INCOIS (ocean state + PFZ), MOSDAC/ISRO (satellite EO), GIS (location, boundaries, geofencing), Open-Meteo (verified secondary). Every access mechanism was checked against the operator's own documentation before a line was written — see [docs/providers.md](docs/providers.md). |
| **Languages** | English, Hindi (Devanagari **and** romanised Hinglish), Malayalam, Tamil — understood *and* answered. The internal representation is language-independent and there is a test that asserts four languages produce byte-identical intent, place, activity and time. |
| **Latency** | 4.1× from parallel retrieval, 87× more from caching, under a simulated coastal link. Measured, not claimed — see [docs/performance.md](docs/performance.md). |
| **Web client** | Mobile-first, served by the API process at `/app/`. Four user modes, progressive disclosure from a verdict down to the evidence chain, real GPS, a vector marine map that needs no tile server, and an offline app shell. No `npm install` — see [docs/frontend.md](docs/frontend.md). |
| **Failure** | A dead required source withholds the advisory. A dead optional source is noted and ignored. Stale data degrades confidence and says so. Disagreeing sources are both reported and never averaged. All demonstrable with one environment variable. |
| **Tests** | 272, covering intent, routing, agent contracts, normalisation, freshness, stale handling, conflicts, risk scoring, geodesy, caching, timeouts, partial failure, multilingual parity, multi-turn context, API schema, the frontend contract, and all demo queries end to end. `tools/verify_frontend.py` additionally drives the whole judge flow through Chromium. |

---

## Documentation

| Document | What it covers |
|---|---|
| [SETUP.md](SETUP.md) | Step-by-step setup and troubleshooting for a first-time runner |
| [frontend.md](docs/frontend.md) | The web client: modes, disclosure, the map, and why there is no build step |
| [architecture.md](docs/architecture.md) | The pipeline, the layers, and every technology choice with its trade-off |
| [agents.md](docs/agents.md) | Every agent and the full routing table — *generated from the code* |
| [providers.md](docs/providers.md) | Each source: verified access mechanism, role, what is and isn't implemented |
| [live-data.md](docs/live-data.md) | Free (no-card) alternatives to paid keys, and how to switch demo → real-time |
| [indian-sources.md](docs/indian-sources.md) | Step-by-step access to IMD, INCOIS and MOSDAC — accounts, whitelisting, approvals |
| [evidence.md](docs/evidence.md) | The provenance model and how to read an evidence chain |
| [risk-engine.md](docs/risk-engine.md) | The ruleset, the thresholds, and their limits |
| [performance.md](docs/performance.md) | Benchmark method and results; the coastal-connectivity answer |
| [reliability.md](docs/reliability.md) | Timeouts, retries, breakers, degradation, conflict handling |
| [demo.md](docs/demo.md) | The demo script, scenario by scenario, with what to say |
| [api.md](docs/api.md) | The frontend contract |
| [judge-qa.md](docs/judge-qa.md) | Straight answers to the 24 technical questions we expect |
| [limitations.md](docs/limitations.md) | What is mocked, what is approximate, what we will not claim |
| [research-inputs.md](docs/research-inputs.md) | Slots for the research team's validated figures |

---

## Repository layout

```
orca/
├── backend/
│   ├── app/
│   │   ├── agents/          planner (+ routing table), weather, ocean, geospatial,
│   │   │                    satellite, pfz, hazard, route, risk, response
│   │   ├── providers/       provider interface + imd/ incois/ mosdac/ openmeteo/ gis/
│   │   │                    each with demo and live implementations
│   │   ├── reasoning/       nlu, lexicon, planner glue, orchestrator, fusion,
│   │   │                    freshness, evidence builder, conversation context
│   │   ├── safety/          risk_engine.py + rules.yaml (the whole risk policy)
│   │   ├── geo/             geodesy, polygons, gazetteer, boundary layers
│   │   ├── schemas/         every typed contract (Pydantic)
│   │   ├── services/        composition root, query pipeline, direct capabilities
│   │   ├── cache/           interface + in-process and Redis backends
│   │   ├── observability/   per-request trace and structured logging
│   │   ├── i18n/            the message catalogue (the only place language lives)
│   │   ├── llm/             optional, provider-agnostic, off by default
│   │   ├── data/            gazetteer, coastal baseline, boundary layers
│   │   └── tools/           demo, benchmark, verify_live, discover_incois, gen_docs
│   └── tests/               272 tests
├── frontend/                the web client — no build step, no dependencies
│   ├── index.html · sw.js · manifest.webmanifest · offline.html
│   ├── styles/app.css       the whole design system, one file
│   └── js/                  api · state · i18n · services/ · views/
├── tools/
│   └── verify_frontend.py   drives the judge flow through a real browser
├── scripts/                 run.bat · run.sh · test.bat · demo.bat
├── docs/
├── SETUP.md
├── .env.example
└── docker-compose.yml
```

---

## Honesty notes

- **Demo mode is a model, not a recording and not a feed.** It is deterministic and
  physically coherent (wave height follows wind, the monsoon drives the seasonal
  contrast, there is a real sea-breeze cycle) so that a demo is repeatable and the
  freshness and risk layers have something meaningful to work on. Every value it produces
  is labelled `DEMO` from the provider to the sentence the user reads.
- **Live providers are implemented against verified access mechanisms, not guessed
  endpoints.** Where a response field mapping could not be verified — because IMD's API
  requires IP whitelisting we do not have — the provider reports `NOT_CONFIGURED` and is
  simply absent from the answer. It does not guess a field name.
- **The maritime boundary layers are approximations and are flagged as such
  everywhere**, including in the API response. They must not be used for navigation or
  for any legal determination of maritime limits. [docs/limitations.md](docs/limitations.md) is
  the full list.
- **ORCA is decision support.** It is not a certified navigation or maritime-safety
  system, and it says so in every answer.

---

*Built by Team DRISHTI for Smart India Hackathon 2026.*
