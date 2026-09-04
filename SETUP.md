# Setup — step by step

Written for someone who has not run a Python backend before. Follow it top to bottom.
If a step fails, the exact error message is in the "If something goes wrong" table at the
bottom.

---

## What you need first

**Python 3.11 or newer.** Check what you have:

```
python --version
```

Expected output, something like: `Python 3.11.9` or `Python 3.12.4`.

If it says `Python 3.10` or lower, or "not recognized", install it from
<https://www.python.org/downloads/>. **On Windows, tick "Add python.exe to PATH"** on the
first screen of the installer — almost every "python is not recognized" problem comes from
missing that box.

That is the only prerequisite. No database, no API keys, no Docker.

---

## The fastest route

### Windows

Open the `orca` folder and **double-click `scripts\run.bat`**.

The first run takes a minute or two (it creates a virtual environment and downloads
FastAPI and friends). You should end up with:

```
  [1/3] Creating a virtual environment (one time only)...
  [2/3] Installing dependencies...
  [3/3] Starting the server...

  OPEN THIS IN YOUR BROWSER:   http://localhost:8000/app/

INFO orca.container: warmup complete in 38.65 ms
INFO orca.main: ORCA ready in 39.1 ms (demo_mode=True, providers=3, ...)
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### macOS / Linux

```bash
cd orca
./scripts/run.sh
```

### Docker (any OS, if you have it)

```bash
cd orca
docker compose up --build
```

---

## The manual route (worth doing once, so you know what the script does)

```bash
cd orca

# 1. Create an isolated Python environment so ORCA's packages don't mix with
#    anything else on your machine.
python -m venv .venv

# 2. Activate it. Your prompt should now start with (.venv).
#    Windows (Command Prompt):
.venv\Scripts\activate
#    Windows (PowerShell):
.venv\Scripts\Activate.ps1
#    macOS / Linux:
source .venv/bin/activate

# 3. Install the dependencies listed in backend/requirements.txt.
pip install -r backend/requirements.txt

# 4. Start the server.
cd backend
uvicorn app.main:app --reload
```

`--reload` restarts the server whenever you edit a file. Use it while developing; leave it
off for a demo.

---

## Check that it actually works

**1. Open <http://localhost:8000/app/>.** This is **the ORCA app** — a dark marine
interface that asks you who you are (Fisher / Researcher / Disaster management /
Maritime), then gives you a question box.

Try: *"Is it safe to go fishing from Kochi tomorrow at 7 AM?"*

> **Three URLs, and it matters which one you open:**
>
> | URL | What it is |
> |---|---|
> | `http://localhost:8000/app/` | **the app** — this is the product |
> | `http://localhost:8000/docs` | the API console (Swagger). Useful for developers, but it is **not** the app |
> | `http://localhost:8000/api/v1/health` | a JSON status check |
>
> Opening plain `http://localhost:8000` now redirects you to the app.

**2. Health check.** In a *second* terminal (leave the server running in the first):

```bash
curl http://localhost:8000/api/v1/health
```

Look for `"status": "ok"` and `"demo_mode": true`.

*(On Windows, `curl` exists in modern PowerShell and Command Prompt. If it doesn't work,
just open the URL in your browser.)*

**3. Ask ORCA the flagship question.**

```bash
curl -X POST http://localhost:8000/api/v1/query ^
  -H "content-type: application/json" ^
  -d "{\"query\":\"Is it safe to go fishing from Kochi tomorrow at 7 AM?\"}"
```

*(That's Windows Command Prompt syntax. On macOS/Linux replace `^` with `\` and use single
quotes.)*

Easier: go to <http://localhost:8000/docs>, expand **POST /api/v1/query**, click
**Try it out**, and paste this into the body:

```json
{ "query": "Is it safe to go fishing from Kochi tomorrow at 7 AM?" }
```

You should get back an answer, a risk level, a list of factors, an evidence array with
about 29 rows, source cards, and a latency breakdown showing single-digit milliseconds.

**4. Run the tests.** This is the real proof the whole thing works.

```bash
pip install -r backend/requirements-dev.txt
cd backend
python -m pytest
```

Expected: `238 passed`. On Windows you can double-click `scripts\test.bat` instead.

**5. Run the demo script.**

```bash
cd backend
python -m app.tools.demo              # all 11 scenarios
python -m app.tools.demo --id d1      # just the flagship
python -m app.tools.demo --failures   # what happens when sources die
```

**6. Run the benchmark.**

```bash
python -m app.tools.benchmark
```

This is the answer to the judge's latency question. It takes about a minute.

---

## Configuration

ORCA runs with zero configuration. When you want to change something:

```bash
copy .env.example .env        # Windows
cp .env.example .env          # macOS / Linux
```

Then edit `.env`. Every setting is documented in there with what it does and why.
**Never commit your `.env`** — `.gitignore` already excludes it.

The settings worth knowing on day one:

| Setting | Default | What it does |
|---|---|---|
| `ORCA_DEMO_MODE` | `true` | Uses the built-in demonstration dataset. Labelled `DEMO` everywhere. |
| `ORCA_PORT` | `8000` | Change if port 8000 is taken. |
| `ORCA_EXPOSE_TRACE_IN_RESPONSE` | `true` | Includes the execution trace in every response. Great for the demo, turn off in production. |
| `ORCA_DEMO_SCENARIO` | `normal` | `calm`, `normal`, `rough`, `pre_cyclone`. |

To show failure behaviour without changing any code:

```bash
# Windows Command Prompt
set ORCA_DEMO_FAIL_SOURCES=INCOIS
python -m app.tools.demo --id d1

# macOS / Linux
ORCA_DEMO_FAIL_SOURCES=INCOIS python -m app.tools.demo --id d1
```

---

## If something goes wrong

| What you see | What it means | Fix |
|---|---|---|
| `'python' is not recognized` | Python isn't on your PATH | Reinstall Python with "Add python.exe to PATH" ticked, then open a **new** terminal |
| `No module named venv` | Python installed without the venv module | On Ubuntu/Debian: `sudo apt install python3-venv` |
| `cannot be loaded because running scripts is disabled` (PowerShell) | PowerShell execution policy | Use Command Prompt instead, or run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that PowerShell window |
| `[Errno 48] Address already in use` / `only one usage of each socket address` | Port 8000 is taken | `uvicorn app.main:app --port 8001`, or set `ORCA_PORT=8001` |
| `ModuleNotFoundError: No module named 'app'` | You're in the wrong directory | `cd backend` first — `app` lives there |
| `ModuleNotFoundError: No module named 'fastapi'` | Virtual environment not activated, or deps not installed | Activate `.venv`, then `pip install -r backend/requirements.txt` |
| `ConfigurationError: ORCA_DEMO_MODE=false but no live provider is enabled` | You turned off demo mode without enabling a source | Set `ORCA_DEMO_MODE=true`, or enable a provider in `.env` |
| Server starts but `/docs` is blank | Browser cache, or an ad blocker | Hard refresh (Ctrl+Shift+R), or try `/redoc` |
| Tests fail on a fresh clone | Dev dependencies missing | `pip install -r backend/requirements-dev.txt` |
| pip is very slow or times out | Weak connection | `pip install --timeout 120 -r backend/requirements.txt` |

If none of those match: **copy the exact error text**, don't paraphrase it. The last three
lines of a Python traceback almost always name the file and the line.

---

## Where things are

```
orca/
├── scripts/run.bat, run.sh     ← start here
├── backend/
│   ├── app/                    ← all the code
│   │   ├── main.py             ← the FastAPI app
│   │   ├── agents/             ← the nine agents
│   │   ├── providers/          ← IMD, INCOIS, MOSDAC, GIS, Open-Meteo
│   │   ├── safety/rules.yaml   ← the entire risk policy, in one readable file
│   │   └── tools/              ← demo, benchmark, verify_live, discover_incois
│   ├── tests/                  ← 238 tests
│   └── requirements.txt
├── docs/                       ← architecture, agents, providers, judge Q&A, ...
├── .env.example
└── README.md
```

**Good first files to read**, in this order:

1. `backend/app/safety/rules.yaml` — the risk policy, no Python needed
2. `backend/app/agents/planner/routing.py` — which agents run for which question, and why
3. `backend/app/services/query_service.py` — the whole pipeline in one file
4. `docs/architecture.md` — why each choice was made

---

## Handing this to a teammate

Everything they need is one command: `scripts\run.bat` (or `./scripts/run.sh`). No secrets
to share, no database to seed, no accounts to create. The demo is
`python -m app.tools.demo`, and it prints the same thing on every machine.
