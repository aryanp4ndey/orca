# Live data — free alternatives to paid API keys

This document answers three questions:

1. Why does ORCA show **demo data** by default?
2. Which real sources can I use **without paying and without a credit card**?
3. What exactly do I type to switch to **real-time** data?

---

## 1. Why you are seeing demo data

There is no bug and nothing is missing. `backend/app/config/settings.py` ships with:

```python
demo_mode: bool = Field(default=True, ...)
```

When `demo_mode` is true, `ProviderRegistry._build()` returns *only* the demo
implementations:

```python
if s.demo_mode:
    return [DemoIMDProvider(), DemoINCOISProvider(), DemoMOSDACProvider()]
```

So every number you see comes from `providers/demo_synth.py`, a deterministic physical
model — not a recording, not a cached feed, and **never presented as live**. Every value
carries `origin: DEMO` from the provider through the evidence ledger to the sentence the
user reads, and `GET /api/v1/health` reports `"demo_mode": true`.

Demo mode is the default on purpose: the app must start and answer correctly on a laptop
with no keys, no accounts and no network, which is the situation on a judging table. It is
labelled rather than hidden precisely so that switching it off is a one-line change you
can make on stage.

---

## 2. Free sources, compared

Every row below was checked against the operator's own documentation. "Card" means a
payment card is required at signup even for the free tier.

| Source | Key | Card | Free allowance | Covers | Verdict for ORCA |
|---|---|---|---|---|---|
| **Open-Meteo** | none | no | ~10k calls/day, non-commercial | wind, gusts, rain, visibility, cloud, CAPE **and** waves, swell, period, SST, currents | **Use this.** Already implemented and enabled by default. The only source that covers both atmosphere and ocean with no signup at all. |
| **OpenWeatherMap** | free key | **no** | 60 calls/min, 1,000,000 calls/month on `/data/2.5/weather` and `/data/2.5/forecast` | wind, gusts, rain, visibility, cloud, temperature, condition codes | **Use this as a second atmospheric source.** Implemented. |
| **INCOIS ERDDAP** | none | no | public datasets, unmetered | waves, currents, SST | Free and Indian-authoritative, but needs one discovery run to learn real dataset IDs (see below). |
| **IMD** | free | no | unmetered | atmosphere, marine bulletins, port warnings, cyclone track | Free, but IMD grants access by **IP whitelisting**. You cannot self-serve it. |
| **Copernicus Marine (CMEMS)** | free account | no | unmetered | global wave + physics analysis/forecast | Genuinely free and excellent, but access is a Python subsetting toolbox, not a REST call — heavier than a hackathon demo needs. |
| **MOSDAC / ISRO** | account | no | order-based | satellite EO | An archive *ordering* interface, not a real-time query API. |
| **Stormglass** | free key | no | **10 requests/day** | marine | Too low for a demo; one page load can exceed it. |
| **NOAA / NDBC** | none | no | unmetered | buoys, GFS | Global coverage, sparse near India. |
| **WeatherAPI.com** | free key | no | 1M calls/month | atmosphere only | A workable third atmospheric source; not implemented. |
| **Tomorrow.io** | free key | no | 500 calls/day | atmosphere | Allowance too tight. |

**About One Call 3.0:** OpenWeatherMap's One Call API 3.0 is a *separate product* that
does require a card at signup. ORCA deliberately uses the classic `/data/2.5/*` endpoints,
which do not. If a tutorial tells you to add a card, you are on the wrong endpoint.

### What ORCA will not do

None of the unverified sources are guessed at. Where a response field mapping could not be
confirmed against real documentation — IMD, because we do not hold a whitelisted IP —
the provider reports `NOT_CONFIGURED` and is simply absent from the answer. It does not
invent a field name and it does not substitute a similar-looking number from elsewhere.

---

## 3. Switching to real-time data

### The 60-second route (no signup, no key)

```bash
cp .env.example .env
```

Edit `.env` and change one line:

```bash
ORCA_DEMO_MODE=false
```

That is all. `ORCA_OPENMETEO_ENABLED=true` is already the default, so you immediately get
**live wind, gusts, rain, visibility, cloud** *and* **live wave height, swell, period, SST
and currents** — both halves of the risk engine, from a source that needs no account.

Restart, then confirm:

```bash
curl -s localhost:8000/api/v1/health
python -m app.tools.verify_live
```

`verify_live` makes one real call per enabled provider and prints what came back, or the
honest failure. In the answer itself the source cards flip from `DEMO` to `LIVE` and the
disclaimer changes accordingly.

### Adding a second atmospheric source (free key, no card)

Worth doing: with two live atmospheric sources, ORCA's conflict-resolution layer has real
disagreements to reconcile instead of a synthetic one — good to show a judge.

1. Sign up at <https://home.openweathermap.org/users/sign_up>
2. Copy the key from the **API keys** tab.
3. In `.env`:

```bash
ORCA_OPENWEATHERMAP_ENABLED=true
ORCA_OPENWEATHERMAP_API_KEY=your_key_here
```

A new key takes up to about **two hours** to activate. Until then the API returns HTTP 401
and ORCA reports the source as `NOT_CONFIGURED` rather than guessing a value — so if you
see that immediately after signing up, wait, do not debug.

### Enabling the Indian authorities

Full step-by-step for all three — accounts, IP whitelisting, the MOSDAC approval gate
people miss — is in [indian-sources.md](indian-sources.md). Short version:

**INCOIS** (free, no key) — the ERDDAP server is public, but ORCA will not hard-code
dataset IDs it has not seen:

```bash
cd backend
python -m app.tools.discover_incois        # lists the real dataset ids
```

Put the ones you want in `app/data/providers/incois_datasets.json`, then set
`ORCA_INCOIS_ENABLED=true`.

**IMD** — request access at <https://mausam.imd.gov.in/responsive/apis.php>. They whitelist
your public IP. You also need to supply `app/data/providers/imd_fields.json` mapping their
response fields, because ORCA refuses to guess them. Then `ORCA_IMD_ENABLED=true`.

**MOSDAC** — create an account at <https://mosdac.gov.in/signup/>, then set
`ORCA_MOSDAC_ENABLED=true` with `ORCA_MOSDAC_USERNAME` / `ORCA_MOSDAC_PASSWORD`. Note this
is an ordering interface for archived products, not a live query API.

### What the source priority does

`providers/registry.py` declares which source wins a disagreement, by domain:

```python
"atmosphere": [Source.IMD, Source.OPEN_METEO, Source.OPEN_WEATHER_MAP],
"ocean":      [Source.INCOIS, Source.OPEN_METEO],
"satellite":  [Source.MOSDAC],
```

So the free sources serve as primary while the Indian authorities are unreachable, and
automatically demote themselves to cross-checks the moment IMD or INCOIS is enabled. ORCA
never averages two disagreeing sources — averaging would publish a number nobody stands
behind. It reports both claims, takes the authority's, and lowers its confidence.

---

## 4. Mixed mode, and the one switch you should leave alone

With `ORCA_DEMO_MODE=false` and only some providers enabled, the response origin becomes
`MIXED` and the health endpoint says which source contributed what. Nothing is blended
silently.

There is also:

```bash
ORCA_ALLOW_LIVE_FALLBACK_TO_DEMO=false
```

**Leave this false.** True lets demo fixtures stand in for a failed live source. The
values stay labelled, but a user glancing at a wave height would be reading a model of the
sea rather than the sea. Withholding the advisory is the correct behaviour.

---

## 5. Quick troubleshooting

| What you see | What it means |
|---|---|
| `demo_mode: true` in health | `.env` is missing, or is not next to the process. Settings reads `.env`, `../.env`, `../../.env`. |
| Startup error: "no live provider is enabled" | You set `ORCA_DEMO_MODE=false` and disabled everything. Enable at least one. |
| OpenWeatherMap `NOT_CONFIGURED` | Key missing, or newly created and not yet activated (~2h). |
| Provider `TIMEOUT` | No outbound network, or a slow link. ORCA does not retry a timeout — retrying a slow source spends the user's remaining budget on the same slow thing. |
| Answer says `INSUFFICIENT_DATA` | A required variable is missing. This is correct behaviour, not a failure — unknown is never converted into safe. |
| All sources fail | Set `ORCA_DEMO_MODE=true` and carry on. The demo path never needs a network. |
