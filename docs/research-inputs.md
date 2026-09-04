# Research inputs — slots for validated figures

**For the research track (the user and Manya).**

The product does not contain a single invented statistic, and it must stay that way. This
file is where validated figures go, with a citation, so that presentation and product draw
from the same place and nobody has to remember which number came from where.

**Rules:**

1. Nothing goes into a slide or into the product until it has a source and a date here.
2. If a figure cannot be sourced, write the question instead and mark it `UNSOURCED`. An
   honest gap beats a confident guess in front of a judge who knows the domain.
3. Prefer official Indian sources — CMFRI, DoF/DAHD, MoES, IMD, INCOIS, TRAI, NSO, Census.
4. Note the year. Coastal and connectivity figures move fast.

---

## 1 · Stakeholders and scale

| Figure | Value | Source | Year | Status |
|---|---|---|---|---|
| Marine fisherfolk population (India) | | CMFRI Marine Fisheries Census | | `UNSOURCED` |
| Active marine fishers | | | | `UNSOURCED` |
| Marine fishing villages | | | | `UNSOURCED` |
| Fish landing centres | | | | `UNSOURCED` |
| Registered fishing craft — traditional / motorised / mechanised | | | | `UNSOURCED` |
| Coastal districts / states and UTs | 13 states & UTs represented in the ORCA gazetteer | this repo | 2026 | ✅ from code |
| Length of Indian coastline | | | | `UNSOURCED` |
| Share of fishers by state (top 5) | | | | `UNSOURCED` |

## 2 · Connectivity and device access

| Figure | Value | Source | Year | Status |
|---|---|---|---|---|
| Rural mobile broadband penetration | | TRAI | | `UNSOURCED` |
| Median mobile download speed, coastal districts | | | | `UNSOURCED` |
| Offshore coverage — how far from shore does a signal persist | | | | `UNSOURCED` |
| Smartphone ownership among fisherfolk | | | | `UNSOURCED` |
| Feature-phone-only share (drives the SMS/USSD case) | | | | `UNSOURCED` |
| Literacy / digital-literacy rate in fishing communities | | | | `UNSOURCED` |
| Preferred language by coastal state | | | | `UNSOURCED` |

> **Why this matters to the build:** the SMS/USSD fallback and voice output are currently
> listed as not-yet-built. A sourced figure for feature-phone share is what decides whether
> they are P1 or P3.

## 3 · Source behaviour — needed to tune the freshness layer

The freshness thresholds in `app/providers/*/demo.py` are currently our best estimate.
Replace each with an observed figure and the code follows.

| Source | Product | Issue schedule | Observed latency | Source | Status |
|---|---|---|---|---|---|
| IMD | Marine / coastal bulletin | assumed 2×/day | | | `UNSOURCED` |
| IMD | Nowcast | assumed 3-hourly | | | `UNSOURCED` |
| IMD | Cyclone bulletin | | | | `UNSOURCED` |
| INCOIS | Ocean State Forecast | assumed 2×/day | | | `UNSOURCED` |
| INCOIS | PFZ advisory | assumed working days, ~24 h validity | | | `UNSOURCED` |
| INCOIS | High wave / swell surge alert | | | | `UNSOURCED` |
| MOSDAC | INSAT imagery | assumed 30 min | | | `UNSOURCED` |
| MOSDAC | Ocean colour composite | assumed daily | | | `UNSOURCED` |

**Where these land in code:** `ProviderCapability.update_frequency_seconds` and
`max_acceptable_age_seconds` in each provider's `__init__`. Change the numbers, the
freshness verdicts change, and `docs/evidence.md` needs its table updated.

## 4 · Boundaries and geography

| Item | Needed | Candidate source | Status |
|---|---|---|---|
| Authoritative coastline | replaces the approximate ORCA baseline | Survey of India / NHO | `UNSOURCED` |
| EEZ polygon | replaces the derived distance band | Marine Regions (marineregions.org) | `UNSOURCED` |
| Territorial waters / contiguous zone | notified limits | | `UNSOURCED` |
| Restricted and defence practice areas | replaces the illustrative rectangles | | `UNSOURCED` |
| Port limits | | Port authorities | `UNSOURCED` |
| Marine protected areas | | | `UNSOURCED` |
| State fishing-ban periods and areas | | State fisheries departments | `UNSOURCED` |

**Where these land in code:** GeoJSON into `backend/app/data/boundaries/`, registered in
`app/geo/layers.py`, with `authoritative: true` **only** when the dataset genuinely is.

## 5 · Risk thresholds — the highest-value research item

The single most important caveat in the whole project ([limitations.md](limitations.md)).
For each activity and vessel class, we need thresholds agreed with or published by an
authority.

| Activity | Vessel | Variable | MODERATE | HIGH | CRITICAL | Source | Status |
|---|---|---|---|---|---|---|---|
| Fishing | traditional / canoe | wave height | | | | | `UNSOURCED` |
| Fishing | traditional / canoe | wind speed | | | | | `UNSOURCED` |
| Fishing | motorised < 12 m | wave height | | | | | `UNSOURCED` |
| Fishing | mechanised | wave height | | | | | `UNSOURCED` |
| Swimming | — | wave height / current | | | | | `UNSOURCED` |
| Any | any | visibility floor | | | | | `UNSOURCED` |

Also needed: the exact wording and trigger criteria IMD uses for "fishermen are advised
not to venture into the sea", so ORCA's advisory floors match real practice.

**Where these land in code:** `backend/app/safety/rules.yaml`. Nothing else changes.

## 6 · Use cases and validation

| Question | Finding | Source | Status |
|---|---|---|---|
| What do fishers actually check before going out today? | | field interviews | `UNSOURCED` |
| Who do they trust, and in what form (radio, WhatsApp, notice board)? | | | `UNSOURCED` |
| What decision would change if they had this information? | | | `UNSOURCED` |
| Incidents attributable to weather/sea state per year | | | `UNSOURCED` |
| Existing systems they already use, and what those lack | | | `UNSOURCED` |

## 7 · Comparison with existing systems

| System | What it does | What ORCA adds | Source | Status |
|---|---|---|---|---|
| INCOIS mobile advisories | | | | `UNSOURCED` |
| IMD bulletins | | | | `UNSOURCED` |
| Existing fisher apps | | | | `UNSOURCED` |

Be scrupulously fair here. "Fragmented across systems and hard to interpret in context" is
a defensible claim. "Nothing like this exists" is not, and a domain judge will know.

---

## How to use this file

- Fill a row, cite it, change the status to ✅.
- If it feeds the product, note where in code it lands — the columns above already say.
- Anything still `UNSOURCED` at submission goes on the limitations slide, not the claims
  slide. That is a strength: it shows you know the difference.
