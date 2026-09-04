# Reliability

ORCA is designed around the assumption that **something is always broken**: a source is
down, a source is slow, a source is stale, two sources disagree, the network drops, the
user's place name is not in the gazetteer. None of those may produce a confidently wrong
marine safety answer.

## The failure taxonomy, and what each one does

| Failure | Detected by | Behaviour |
|---|---|---|
| Source unreachable | provider returns `UNAVAILABLE`/`ERROR` | source reported as unavailable; if it carried a **required** variable, the advisory is withheld |
| Source slow | per-provider timeout | `TIMEOUT`, no retry (see below), answer proceeds without it |
| Source repeatedly failing | circuit breaker | `CIRCUIT_OPEN`, bypassed for 30 s so it stops costing every user its full timeout |
| Malformed response | `ProviderPayloadError` | `ERROR` with the parse failure recorded; no partial guess |
| Source not configured | missing field mapping / credentials | `NOT_CONFIGURED` with a message saying exactly what to supply |
| Data stale | freshness layer | status downgraded to `DEGRADED`; advisory downgraded to `ADVISORY_DEGRADED`; confidence cut; user warned |
| Sources disagree | fusion layer | both claims kept, authority wins, confidence cut, conflict reported |
| Agent exceeds budget | `BaseAgent.execute` | `TIMEOUT` status; orchestrator continues |
| Agent raises | `BaseAgent.execute` | `FAILED` status with the exception type; orchestrator continues |
| Optional agent has nothing | agent | `SKIPPED`; never blocks the answer |
| Required upstream agent failed | orchestrator | dependent steps `SKIPPED` with a stated reason |
| Budget nearly spent | orchestrator | optional steps dropped and recorded, required steps still run |
| Place not found | planner | ORCA asks which place, rather than guessing a coastline |
| LLM slow or absent | LLM layer | deterministic path; nothing waits on it |
| LLM invents a number | grounding check | the model's text is discarded, the template answer is used |

Every one of these has a test.

## Required vs optional, and why the distinction matters

The planner marks each capability required or optional. It is not a hint — it changes what
happens to the answer:

- **Optional source down** (MOSDAC, satellite): the answer proceeds, the gap is stated,
  the risk verdict is unchanged. `test_optional_source_down_still_answers`.
- **Required source down** (INCOIS, ocean state): significant wave height is a *required*
  risk variable, so the risk engine returns `INSUFFICIENT_DATA` and `ADVISORY_WITHHELD`,
  and the answer says *"treat this as unknown, not as safe"*.
  `test_critical_source_down_withholds_the_advisory` also asserts that no wave height was
  invented from anywhere else.

That asymmetry is the whole safety argument. A marine decision-support system that answers
"looks fine" when it has no wave forecast is worse than one that answers nothing.

## Timeout and retry policy

```
per-provider timeout   ORCA_BUDGET_PROVIDER_MS       default 1800 ms
connect timeout        ORCA_PROVIDER_CONNECT_TIMEOUT_MS  default 700 ms
retries                ORCA_PROVIDER_RETRY_ATTEMPTS  default 1
backoff                exponential with jitter, base 120 ms
total deadline         all attempts together are bounded by the provider budget
retry on timeout       NO
```

**Why no retry on timeout.** A source that timed out is slow, not flaky. Retrying it spends
the caller's remaining budget to ask the same slow thing again, and on a coastal link that
budget *is* the user experience. Connection-level faults are genuinely transient and do
get one retry. This change alone took the p95 of the `slow_source` benchmark mode from
901 ms to 406 ms.

## Circuit breaker

Four consecutive failures open the circuit for 30 s. While open, calls return
`CIRCUIT_OPEN` immediately instead of burning the timeout. After the window, one probe is
allowed through; success closes the circuit, failure re-opens it. State is visible at
`GET /api/v1/health` and `GET /api/v1/sources`.

## Source conflict resolution

Two sources will disagree. The wrong responses are to **average** them (which invents a
number nobody published) or to take **whichever arrived last** (which makes the answer
depend on network jitter).

ORCA's policy, in `app/reasoning/fusion.py`:

1. Keep every source's claim intact and attributed.
2. Measure the spread against a per-variable tolerance reflecting how much disagreement is
   normal for that quantity (wind ±7 km/h or 25 %; wave height ±0.4 m or 25 %; SST ±1 °C;
   visibility ±3000 m or 40 %).
3. If the spread is material, take the value from the **documented authority for that
   variable's domain** — IMD for atmosphere, INCOIS for ocean, MOSDAC for satellite —
   never a blend.
4. Reduce confidence in proportion to the disagreement.
5. Say so in the answer when it is material.

The priority order lives in `providers/registry.SOURCE_PRIORITY`, so it is configuration
rather than a hidden preference:

```python
"atmosphere": [IMD, OPEN_METEO]
"ocean":      [INCOIS, OPEN_METEO]
"satellite":  [MOSDAC]
```

Demonstrate it: `ORCA_DEMO_CONFLICT=true python -m app.tools.demo --id d1`.

## Graceful degradation, in order

1. Answer fully.
2. Answer with an optional source missing, and say which.
3. Answer with reduced confidence, and say why.
4. Answer with a degraded advisory and a "verify officially" warning.
5. Withhold the advisory, report `INSUFFICIENT_DATA`, and say what is missing.
6. Ask a clarifying question.

ORCA never skips from step 1 to a confident wrong answer, and there is no step where it
fabricates a value.

## Demonstrating any of it

```bash
ORCA_DEMO_FAIL_SOURCES=INCOIS      # required source down   → advisory withheld
ORCA_DEMO_FAIL_SOURCES=MOSDAC      # optional source down   → answer proceeds
ORCA_DEMO_STALE_SOURCES=IMD,INCOIS # stale data             → degraded + warning
ORCA_DEMO_SLOW_SOURCES=INCOIS:4000 # slow source            → timeout, partial answer
ORCA_DEMO_CONFLICT=true            # sources disagree       → both reported, IMD wins
ORCA_DEMO_SCENARIO=pre_cyclone     # severe conditions      → CRITICAL

python -m app.tools.demo --failures  # runs the whole set with commentary
```

## Observability

Every query produces a trace with a span for NLU, planning, each wave, each agent, each
provider call, the risk engine, the grounding check and the response. Each span carries
its duration, status and attributes (cache hit, freshness, confidence, error). It is
attached to the API response when `ORCA_EXPOSE_TRACE_IN_RESPONSE=true` and is always
retrievable at `GET /api/v1/evidence/{query_id}`.

That is the artefact to put on screen when a judge asks *"how exactly did that answer get
generated?"*
