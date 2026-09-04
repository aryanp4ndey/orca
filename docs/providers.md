# Data sources

ORCA uses four source families for four different jobs. They are **not
interchangeable**, and the system never treats one as a substitute for another.

| Family | Job in ORCA | Why this source |
|---|---|---|
| **IMD** | Atmosphere and warnings: wind, gusts, rainfall, visibility, convective/lightning potential, port and sea-area bulletins, cyclone track and wind fields | India's meteorological authority. Marine and coastal bulletins and cyclone products for Indian waters are theirs. |
| **INCOIS** | Ocean state: significant wave height, swell, wave period and direction, currents, SST — and Potential Fishing Zone advisories | India's ocean-information authority. Waves are what capsize a country craft, so this is the source the risk engine leans on hardest. |
| **MOSDAC / ISRO** | Satellite Earth observation: SST, ocean colour / chlorophyll, INSAT imagery | ISRO's satellite data archive. Gives the physical basis behind a PFZ and independent SST. |
| **GIS** | Location resolution, distances, maritime bands, zone membership, geofencing | Spatial answers need provenance exactly like marine values do. |
| *Open-Meteo* | *Secondary* atmosphere and ocean forecast | The only source in the mix with a documented, key-free, immediately verifiable contract. It is the reference implementation of the live path and a genuine fallback — never the authority for Indian waters. |

---

## Verified access mechanisms

Every entry below was checked against the operator's own documentation **before** any
code was written. Nothing here is an invented endpoint.

### IMD — `https://api.imd.gov.in/api/v1/`

IMD publishes an API catalogue at `https://api.imd.gov.in/public/api_reference.html`.
Endpoints relevant to ORCA include `current_wx`, `stationnowcast`, `districtwarning`,
`portwarning`, `seabulletin`, `coastalbulletin`, `cyclone_track`, `cyclone_wind`,
`cyclone_cou`.

`https://mausam.imd.gov.in/responsive/apis.php` states that access requires **IP
whitelisting by IMD**, that attribution to IMD is required, and that clients should cache.
There is also a self-service portal account at `https://api.imd.gov.in/public/register.php`
(email-verified; government registrants must use a `gov.in`/`nic.in` address) — but the
account is not the gate, the IP whitelist is. See
[indian-sources.md](indian-sources.md) for the full procedure and IMD's support contacts.

**What we could not verify:** the JSON field names inside each response, because they
cannot be observed from a non-whitelisted host. Rather than guess a field name and
silently mis-report a gust as a mean wind, the response mapping lives in
`backend/app/data/providers/imd_fields.json` and **ships empty**. Until it is filled in,
`IMDLiveProvider` reports `NOT_CONFIGURED` and IMD is simply absent from the answer.

> To enable: get your host whitelisted, call each endpoint once, record the keys, and
> copy `imd_fields.example.json` to `imd_fields.json` with real field names.

### INCOIS — ERDDAP at `https://erddap.incois.gov.in/erddap`

INCOIS runs an ERDDAP server exposing the standard ERDDAP REST interface:
`/search/index.json` for discovery, `/griddap/{datasetID}.json` and
`/tabledap/{datasetID}.json` for data, no authentication for public datasets. ERDDAP's URL
grammar is stable across installations, which is what makes this implementable without
guessing.

**What is deployment-specific:** the dataset ids and their variable names. Those live in
`backend/app/data/providers/incois_datasets.json`, which also ships empty.

> To enable: `python -m app.tools.discover_incois --search wave --describe --write` on a
> networked machine, map the canonical variables you need, rename to
> `incois_datasets.json`.

INCOIS PFZ advisories are published as bulletins rather than through a machine-readable
API we could verify, so **PFZ is demo-only in this prototype**. The PFZ agent, the
bearing/distance geometry, the validity handling and the map output are all real; the
coordinates come from the demo provider and are labelled `DEMO`.

### MOSDAC / ISRO

MOSDAC publishes a **data download API** whose documented client is a Python script
(`mdapi.py`) driven by a `config.json`, authenticating with MOSDAC account credentials,
searching by `datasetId` with optional `startTime`/`endTime`/`boundingBox`, capped at 5000
files per user per day, with a one-hour lockout after three failed logins. Accounts are
created at `https://mosdac.gov.in/signup/`.

Two consequences we do not paper over:

1. **It is an archive ordering interface, not a low-latency point query.** A request
   returns granules, which must then be downloaded and processed. That is
   minutes-to-hours, not milliseconds.
2. **Therefore MOSDAC is never on the critical path of a safety answer.** The satellite
   agent is always optional, its results are cached for hours, and if it is missing the
   risk engine proceeds and says so.

`MOSDACLiveProvider` implements the credential gate and reports honestly that granule
download and product decoding are **not implemented** in this prototype. It returns no
geophysical values rather than fabricating them.

### Open-Meteo

`https://api.open-meteo.com/v1/forecast` and `https://marine-api.open-meteo.com/v1/marine`.
Documented, no key for non-commercial use, response shape
`{"hourly": {"time": [...], "<var>": [...]}, "hourly_units": {...}}`. Variable names used
by ORCA are exactly the documented ones, and a test pins them so the mapping cannot drift
into invention. Attribution to Open-Meteo and DWD is required and is carried in every
source report.

---

## The provider contract

```python
class MarineDataProvider:
    async def _fetch(self, query: ProviderQuery) -> ProviderResult: ...
```

Three rules every implementation honours:

1. **Never raise into an agent.** Return a `ProviderResult` whose `status` says what went
   wrong. Partial answers beat exceptions in a safety system.
2. **Always normalise.** Convert to the canonical unit for the variable
   (`app/core/units.py`) and record the conversion in `transformation`.
3. **Always timestamp.** `issued_at`, `valid_time` and `retrieved_at` are three different
   things and the freshness layer needs all three.

```python
ProviderResult(
    provider_id, source, origin,           # DEMO | LIVE | CACHED_LIVE | COMPUTED
    dataset, status,                       # OK | DEGRADED | TIMEOUT | ERROR |
    measurements=[Measurement(...)],       # UNAVAILABLE | NOT_CONFIGURED | CIRCUIT_OPEN
    advisories=[Advisory(...)],
    pfz=[PFZAdvisory(...)],
    retrieved_at, latency_ms, cache, error,
    freshness, attribution,
    update_frequency_seconds, max_acceptable_age_seconds,
)
```

The frontend never learns whether a provider was demo or live from its *shape* — only
from `origin`, which is always present and always accurate.

---

## Adding a source

1. Implement `MarineDataProvider._fetch` returning canonical variables.
2. Declare a `ProviderCapability` — variables, datasets, update cycle, acceptable age,
   cache TTL. The freshness layer needs the last three to mean anything.
3. Add it to `ProviderRegistry._build`, and to `SOURCE_PRIORITY` if it competes with an
   existing source for a variable.
4. That's all. No agent changes, no schema changes, no risk-engine changes.

See [providers-generated.md](providers-generated.md) for the live registry dump.
