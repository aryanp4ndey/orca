# Frontend

The judge-facing web client. Mobile-first, one-handed, and readable by someone
who has never heard the word "agent".

## Run it

The backend serves the client from the same origin, so there is one command and
one URL:

```bash
cd backend
uvicorn app.main:app --reload
```

| | |
|---|---|
| **App** | <http://localhost:8000/app/> |
| **API** | <http://localhost:8000/api/v1/> |
| **API console** | <http://localhost:8000/docs> |

There is **nothing to install and nothing to build**. No `npm install`, no
bundler, no `node_modules`. If Python runs, the app runs.

## Why there is no build step

This is a deliberate engineering decision, not a shortcut, and it follows from
the problem statement rather than from convenience.

The users we are told to design for are on weak coastal mobile links. A typical
React + Leaflet + charting bundle is 400–600 KB of JavaScript before a single
marine value has been fetched. This client is **native ES modules, no framework,
no runtime dependency** — the whole app is around 90 KB of source, served
gzipped, and it caches to an app shell on first visit. On a 2G link that is the
difference between an app that opens and an app that spins.

Two secondary benefits fell out of it: anyone on the team can run the frontend
without a Node toolchain, and there is no build output that can drift from the
source.

**What it costs us.** No JSX, no component framework, no hot reload, and no
type-checking at build time. For an app of this size — a dozen screens, one
data source, explicit re-render — that is a fair trade. If the team later wants
React and Vite, the seam is `js/api.js`: every call to the backend goes through
it, and nothing else in the app knows the backend exists.

`VITE_API_BASE_URL` is honoured for parity with a future Vite setup — see
"Pointing at a different backend" below.

## Structure

```
frontend/
├── index.html               app shell, boot splash, module entry
├── manifest.webmanifest     PWA manifest (installable, standalone)
├── sw.js                    service worker: app shell only, never API responses
├── offline.html             offline fallback page
├── styles/app.css           the whole design system, one file
└── js/
    ├── main.js              shell, navigation, status bar, sheets, boot
    ├── api.js               the only module that talks to the backend
    ├── config.js            API base resolution
    ├── state.js             store, persistence, user modes
    ├── i18n.js              interface strings (EN / HI / ML / TA)
    ├── util/dom.js          ~110-line hyperscript + icons + toasts
    ├── util/format.js       IST times, units, relative ages
    ├── services/
    │   ├── net.js           online / degraded / offline
    │   ├── geolocation.js   GPS with every failure mode handled
    │   ├── voice.js         speech input and output, feature-detected
    │   └── cache.js         saved answers, always labelled as saved
    └── views/
        ├── ask.js           home + conversation (the main surface)
        ├── answer.js        risk card, factors, progressive disclosure
        ├── evidence.js      evidence rows and source panel
        ├── trace.js         "How ORCA decided"
        ├── map.js           vector marine map
        ├── screens.js       map / PFZ / alerts / route / compare
        ├── settings.js      modes, language, system panel
        └── progress.js      in-flight progress
```

## User modes — one intelligence layer, four decision contexts

The mode does not switch products. It changes the *decision context* sent to the
backend and how much of the same answer is shown by default.

| Mode | Activity sent | Vessel | Default detail | Landing screen |
|---|---|---|---|---|
| 🎣 Fisher | `fishing_small_boat` | `small_motorised` | verdict + 4 factors, disclosure collapsed | Ask |
| 🔬 Researcher | `research` | `mechanised` | 8 factors, "Why" expanded by default | Ask |
| 🚨 Disaster management | `patrol` | `mechanised` | 6 factors, operational | Alerts |
| 🚢 Maritime | `cargo_transit` | `large` | 6 factors, route-first quick actions | Ask |

Because activity and vessel are real inputs to the backend's risk ruleset, the
same conditions genuinely produce a different verdict per mode — a sea that is
CRITICAL for a country craft is routine for a cargo vessel. That is the product
argument for modes, and it is enforced server-side, not faked in the client.

## Progressive disclosure

```
verdict + 3–4 numbers          ← what a fisherman needs, and all they see
  └ Why this result?           ← the factors with thresholds, the score
      └ View evidence (29)     ← every row: source, dataset, times, freshness
          └ Sources            ← per-source status, latency, attribution
              └ How ORCA decided  ← the plan, the agents, the timings
```

Everything below the first line is a `<details>` element, so keyboard and screen
reader support come for free and nothing is hidden from assistive technology.

## The map

Vector, drawn in the client from `GET /api/v1/geo/basemap` and from the
`visualizations.layers` on each answer. There is no tile server and no
third-party basemap in the default path.

Three reasons, in order of weight:

1. Coastal users are exactly the users who cannot afford to download raster
   tiles. The whole basemap is a few kilobytes and works with no connectivity.
2. What is drawn is the *same* geometry the backend reasoned about, so the user
   sees what the risk engine actually used rather than a prettier proxy.
3. We are not in a position to vouch for a third-party basemap's boundaries.
   Every outline here carries its own provenance and an `authoritative` flag,
   and every shipped layer is flagged `false`.

Coordinates are projected to pixels in JavaScript (Web Mercator) rather than
relying on a scaled `viewBox`, so stroke widths and label sizes stay honest at
every zoom level. Pan, pinch and wheel zoom all work; layers toggle individually.

## Honesty rules the client enforces

These are the rules that would be easy to break in a UI and expensive to break
in the field:

- **Demo data is labelled** in the status bar, on every answer card, and on
  every source card. The word "live" never appears unless `data_origin` says so.
- **Colour is never the only signal.** Every risk level carries an icon, a word
  and a colour. `INSUFFICIENT_DATA` renders as **NOT KNOWN**, never as a raw enum.
- **A saved answer is drawn as saved**, with the time it was retrieved. Stale is
  never dressed as current.
- **Freshness travels with every value** — `FRESH` / `AGEING` / `STALE` /
  `no value` — on the evidence row itself, not in a footnote.
- **When the backend withholds an advisory**, the card leads with
  *"Current marine conditions could not be verified"* rather than a green light.
- **Authority warnings are quoted**, never paraphrased.
- **Progress is not faked.** While a request is in flight the client shows which
  stage is *expected* to be running; it never ticks a stage as complete, because
  it cannot observe the backend's internal progress. The moment the answer lands
  it is replaced by the real measured timings from the trace.
- **No feature exists that the backend cannot serve.** The microphone button is
  not rendered at all unless the browser actually has speech recognition.

## Connectivity

| State | How it is detected | What changes |
|---|---|---|
| **Online** | requests completing under ~2.5 s | normal |
| **Degraded** | a request took over ~2.5 s, or timed out | status chip warns; saved answers offered on failure |
| **Offline** | `navigator.onLine` false, or a request failed with no network | app shell still opens; saved answers readable, clearly marked; "could not be verified" on new questions |

`navigator.onLine` alone is close to useless on a coastal link — the phone
reports "online" while nothing completes — so observed request latency is
combined with it. The health probe runs once a minute, not every few seconds:
polling hard is exactly the behaviour that ruins a metered connection.

## Low-bandwidth mode

A switch in **More → Settings**. It sets `low_bandwidth: true` on every query,
which makes the backend drop map geometry and layer payloads from the response
(34.8 KB → 25.5 KB before gzip, and the answer itself is byte-identical). In the
client it also decimates the coastline, hides place labels, and disables smooth
scrolling.

## Languages

English, Hindi, Malayalam and Tamil, in the selector and in the answers. Hindi
typed in Roman letters ("Kal subah 7 baje Kochi se fishing ke liye jaana safe
hai?") is understood — the backend detects it and answers in Hindi.

Interface strings live in `js/i18n.js`; answers are translated server-side. A
missing string falls back to English rather than rendering blank, so a partial
translation is always safe to ship.

## Accessibility

Skip link; `aria-live` announcements for every answer and status change; every
interactive element labelled; 44 px minimum tap targets; `<details>` for
disclosure; `role="switch"` on toggles; focus trapping and Escape in sheets;
`prefers-reduced-motion` respected; colour never the sole carrier of meaning.

## Pointing at a different backend

Same origin by default. To point elsewhere, in order of precedence:

1. `?api=https://host:8000` in the URL (remembered afterwards)
2. `window.ORCA_CONFIG = { VITE_API_BASE_URL: 'https://host:8000' }` in a
   `config.local.js` loaded before `main.js`
3. **More → Settings → Backend address**

CORS is already permissive on the backend (`ORCA_CORS_ORIGINS`), so a separately
hosted frontend works without changes.

## Verified in a real browser

`tools/verify_frontend.py` drives Chromium through the full judge flow at a
390 × 844 viewport with geolocation granted: mode selection, GPS, the flagship
query, progressive disclosure, the follow-up, map, alerts, PFZ, route, compare,
Hindi, the desktop layout and offline behaviour. It fails on any console error.
