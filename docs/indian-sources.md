# Getting access to IMD, INCOIS and MOSDAC

The three Indian authorities are all **free**. What differs is how you get in, and how
long it takes. Read the difficulty column before you plan your demo around one.

| Source | What you need | Self-service? | Realistic wait | Blocks a demo? |
|---|---|---|---|---|
| **INCOIS** | nothing — public ERDDAP | **yes** | minutes | no |
| **MOSDAC** | approved account (username + password) | account yes, *data* approval no | hours–days | yes, for L1 products |
| **IMD** | portal account **and** IP whitelisting | account yes, whitelist no | days–weeks | yes |

Start with INCOIS. It is the only one you can finish today, and it happens to be the
source ORCA's risk engine leans on hardest (waves).

---

## 1. INCOIS — no account, no key, ~15 minutes

INCOIS runs a standard **ERDDAP** server. ERDDAP's URL grammar is identical across every
installation in the world, which is exactly why ORCA can implement it without guessing.
Public datasets need no authentication at all.

**What is deployment-specific** is the dataset IDs and their internal variable names.
Those cannot be invented, so `app/data/providers/incois_datasets.json` ships empty and
`INCOISLiveProvider` reports `NOT_CONFIGURED` until you fill it.

### Step 1 — see what's actually there

Open <https://erddap.incois.gov.in/erddap/info/index.html?page=1&itemsPerPage=1000> in a
browser. That is the full dataset catalogue. Real IDs on that server look like
`incois_tmi_3day_datasets` and `incois_quickscat_daily_datasets`.

### Step 2 — run the discovery tool

```bash
cd backend
python -m app.tools.discover_incois --search wave --describe --write
python -m app.tools.discover_incois --search current --describe --write
python -m app.tools.discover_incois --search sst --describe --write
```

It hits ERDDAP's documented `/search/index.json` and `/info/{datasetID}/index.json`
endpoints and prints each dataset with its real variable names, then writes
`app/data/providers/incois_datasets.discovered.json`.

### Step 3 — map the variables you need

Copy the discovered file to `incois_datasets.json` and fill each `variables` block,
mapping ORCA's canonical name to the dataset's actual variable name and unit:

```json
{
  "<real_dataset_id>": {
    "kind": "griddap",
    "variables": {
      "wave_height_significant": {"field": "<real_var_name>", "unit": "m"},
      "wave_period":            {"field": "<real_var_name>", "unit": "s"},
      "sea_surface_temperature":{"field": "<real_var_name>", "unit": "degC"}
    }
  }
}
```

`app/data/providers/incois_datasets.example.json` shows the shape. Only map variables you
have actually seen in the `available_variables` list — a wrong mapping is worse than a
missing one, because it produces a confident wrong wave height.

### Step 4 — enable it

```bash
ORCA_DEMO_MODE=false
ORCA_INCOIS_ENABLED=true
```

```bash
python -m app.tools.verify_live      # should now show INCOIS answering
```

### Two things that will bite you

- **TLS chain.** The INCOIS ERDDAP certificate did not verify from our test host
  (`unable to get local issuer certificate`). If you hit that, it is a missing
  intermediate certificate on their side, not a bug in ORCA. Fix it by installing the
  proper CA bundle (`pip install certifi` and point `SSL_CERT_FILE` at it) — **do not**
  disable certificate verification to make it go away.
- **PFZ is not here.** INCOIS publishes Potential Fishing Zone advisories as *bulletins*
  (PDF/text for a district), not through a machine-readable API we could verify. So PFZ in
  ORCA stays demo-only: the agent, the bearing and distance geometry, the validity window
  handling and the map output are all real, and the coordinates are labelled `DEMO`. Say
  that to a judge before they ask.

---

## 2. MOSDAC — account, then data-level approval

You were right that this one needs a registered, **approved** username and password. There
are two distinct gates and people usually only discover the second one.

### Step 1 — create the account

Go to <https://mosdac.gov.in/signup/>. The form asks for:

- Username — minimum 5 characters, no capitals, first 3 must be alphabetic
- Password — minimum 8 characters with an uppercase, a lowercase, a number and a special character
- Title, first and last name
- Email address
- Organisation and address, city, country
- Mobile in the format `+91-XXXXXXXXXX`
- **Purpose of registration** — write a real sentence here. "Smart India Hackathon 2026,
  problem statement SIH26176, marine safety decision support for fishermen" is exactly the
  kind of thing that gets waved through
- CAPTCHA

Use an institutional email if you have one. It makes the next step easier.

### Step 2 — the gate people miss

An account alone does **not** entitle you to every product. MOSDAC's own FAQ covers the
case where a registered user downloading L1 data is told *"your account is not configured
to download"* — higher-level and L1 products require your account to be additionally
approved for them. If you get that message, you are not doing anything wrong; you need to
request access for that product family through MOSDAC support.

Plan for hours to days. Do not put MOSDAC on the critical path of a demo you are giving
next week.

### Step 3 — the download API

The documented client is a Python script, not a REST endpoint you call from a web app.
Download `mdapi.zip` from <https://www.mosdac.gov.in/downloadapi-manual>; it contains
`mdapi.py` and `config.json`. Do not rename `config.json` — the script looks for that exact
name.

`config.json` has three sections:

| Section | Contents |
|---|---|
| `user_credentials` | `username`, `password` |
| `search_parameters` | `datasetId` (mandatory), `startTime`/`endTime` as `YYYY-MM-DD`, `count` (capped at **100**), `boundingBox` as `minLon,minLat,maxLon,maxLat`, optional `gId` for a single granule |
| `download_settings` | output directory and logging |

Limits worth knowing: **5000 files per user per day**, and **three wrong logins locks the
account for one hour**. Do not put a credential loop in a retry.

### Step 4 — enable it in ORCA, and what you'll get

```bash
ORCA_MOSDAC_ENABLED=true
ORCA_MOSDAC_USERNAME=your_username
ORCA_MOSDAC_PASSWORD=your_password
```

Be clear about what this does and does not do today. `MOSDACLiveProvider` implements the
**credential gate** and reports honestly that granule download and product decoding are
**not implemented** in this prototype. It returns no geophysical values rather than
fabricating them.

That is a deliberate architectural position, not an unfinished corner: MOSDAC is an
**archive ordering interface**, not a low-latency point query. A request returns granules
which must then be downloaded and processed — minutes to hours, not milliseconds. So
MOSDAC is never on the critical path of a safety answer. The satellite agent is always
optional, its results cache for hours, and if it is absent the risk engine proceeds and
says so.

If you want to finish it, the honest shape is an **offline ingest job**: run `mdapi.py` on a
schedule, decode the granules into a local store, and have `MOSDACLiveProvider` read that
store. Do not try to make a granule order happen inside a 3-second query budget.

---

## 3. IMD — account, then IP whitelisting

Two gates again, and the second is the slow one.

### Step 1 — register on the API portal

<https://api.imd.gov.in/public/register.php> — there is a self-service account creation
form with a CAPTCHA and an email verification step (the page has a "resend verification
email" link). Government-organisation registrants are required to use an official address
ending in `gov.in` or `nic.in`.

*What I could not verify from here:* the exact fields on that form, because it renders
behind a CAPTCHA. Fill it in and see. Nothing in ORCA depends on the field list.

### Step 2 — get your IP whitelisted

This is the real gate. <https://mausam.imd.gov.in/responsive/apis.php> states that API
access requires **IP whitelisting by IMD**. Note the consequences before you build around
it: it binds access to a fixed public IP, so a laptop on hotel wifi at the venue will not
work, and neither will most cloud functions. If you need IMD live on stage, whitelist the
demo machine's IP in advance, or put a small fixed-IP proxy in front.

Contacts from IMD's own page, in their escalation order:

| Level | Contact |
|---|---|
| 1 — ISSD Technical Support | rthnewdelhi4@gmail.com · +91-11-24344325 |
| 2 — Dr. Sankar Nath | sankar.nath@imd.gov.in · +91-9821832587 |
| 3 — Dr. Kuldeep Shrivastav | kuldeep.srivastava@imd.gov.in · +91-11-43824314 |

Write from an institutional address, state your public IP, your organisation, and the
purpose. Mention that you will cache client-side and attribute IMD — both are things IMD
explicitly asks for, and saying so unprompted helps.

### Step 3 — record the response field names

Once whitelisted, the endpoint catalogue is at
<https://api.imd.gov.in/public/api_reference.html> and includes `current_wx`,
`stationnowcast`, `districtwarning`, `portwarning`, `seabulletin`, `coastalbulletin`,
`cyclone_track`, `cyclone_wind`, `cyclone_cou`.

**ORCA will not guess IMD's JSON field names.** They cannot be observed from a
non-whitelisted host, and guessing one is how you silently report a gust as a mean wind
and tell a fisherman the sea is calmer than it is. So:

```bash
curl 'https://api.imd.gov.in/api/v1/current_wx?...' | python -m json.tool
```

Look at the real keys. Then copy `app/data/providers/imd_fields.example.json` to
`imd_fields.json` and replace every `REPLACE_WITH_REAL_KEY` with the key you actually saw,
along with its real unit:

```json
"current_wx": {
  "rows_key": "data",
  "issued_field": "<real key>",
  "valid_field": "<real key>",
  "variables": {
    "wind_speed_10m": {"field": "<real key>", "unit": "kn", "kind": "OBSERVED"}
  }
}
```

Get the `unit` right. ORCA converts to canonical units on the way in and records the
conversion in `transformation`; a wrong declared unit produces a wrong number with a
perfect audit trail behind it.

### Step 4 — enable it

```bash
ORCA_DEMO_MODE=false
ORCA_IMD_ENABLED=true
```

IMD is first in `SOURCE_PRIORITY["atmosphere"]`, so from that moment it becomes the
authority for wind and warnings and Open-Meteo demotes itself to a cross-check
automatically. No code change.

---

## Which order to actually do this in

1. **Today, no signup:** `ORCA_DEMO_MODE=false`. Open-Meteo gives live wind *and* waves.
   You have a live demo.
2. **This afternoon:** run `discover_incois`, map two or three variables, enable INCOIS.
   Now an Indian authority is in the answer and the conflict layer has two real ocean
   sources to reconcile.
3. **This week:** register with MOSDAC and file the IMD whitelist request. Both have
   human latency you cannot compress, so start them early even though they finish last.
4. **Optional, 2 minutes:** a free OpenWeatherMap key (no card) as a second atmospheric
   source — see [live-data.md](live-data.md).

Whatever is not enabled reports `NOT_CONFIGURED` and is simply absent from the answer. It
is never quietly replaced by a similar-looking number from somewhere else.

---

## Sources

- MOSDAC Data Download API manual — <https://www.mosdac.gov.in/downloadapi-manual>
- MOSDAC signup — <https://mosdac.gov.in/signup/>
- MOSDAC FAQ on unconfigured accounts — <https://www.mosdac.gov.in/faq-page>
- IMD APIs page (whitelisting, attribution, support contacts) — <https://mausam.imd.gov.in/responsive/apis.php>
- IMD API portal / registration — <https://api.imd.gov.in/public/index.php>
- INCOIS ERDDAP dataset catalogue — <https://erddap.incois.gov.in/erddap/info/>
- INCOIS ERDDAP REST interface — <https://erddap.incois.gov.in/erddap/rest.html>
