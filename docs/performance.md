# Performance

## The question this document answers

> *"If it takes 4–5 seconds in Jaipur where the internet is good, how will it perform in a
> coastal region?"* — mock judge

That question is right, and it drove the architecture from the first commit. The honest
decomposition is:

```
total time = client network round-trip
           + ORCA's own work
           + upstream source time (× how many of them you wait for in series)
```

We cannot make a coastal 2G link faster. What we can do — and did — is:

1. make ORCA's own work small and constant,
2. stop waiting for sources one after another,
3. stop paying the upstream cost at all when the answer is already known,
4. bound the damage a single slow source can do,
5. make the payload small enough to survive the link.

Everything below is measured by `python -m app.tools.benchmark`, which is in the repo and
which anyone on the team can run.

---

## Results

`python -m app.tools.benchmark --iterations 30`, demo mode, milliseconds.

| Mode | p50 | p90 | p95 | max | provider p50 | payload | low-bw payload |
|---|---|---|---|---|---|---|---|
| `local_serial` | 5.7 | 6.3 | 7.3 | 20.8 | 1.3 | 34.8 KB | 25.5 KB |
| `local_parallel` | 5.3 | 5.9 | 6.4 | 7.4 | 1.4 | 34.8 KB | 25.5 KB |
| **`coastal_serial`** | **1752.6** | 1753 | 1754 | 1754 | 1747 | 34.8 KB | 25.5 KB |
| **`coastal_parallel`** | **426.1** | 427 | 428 | 428 | 421 | 34.8 KB | 25.5 KB |
| **`coastal_cached`** | **4.9** | 5.0 | 5.4 | 5.4 | 0.4 | 34.7 KB | 25.5 KB |
| `fast_path` | 3.3 | 3.6 | 3.7 | 3.8 | 0.2 | 14.6 KB | 10.8 KB |
| `degraded` | 4.7 | 5.2 | 5.8 | 6.3 | 1.1 | 26.6 KB | 20.1 KB |
| `slow_source` | 7.3 | 8.7 | **405.7** | 405.7 | 1.7 | 31.7 KB | 23.5 KB |

**Headlines:**

- serial → parallel, with upstream latency: **1752.6 ms → 426.1 ms (4.1×)**
- cold → warm cache, with upstream latency: **426.1 ms → 4.9 ms (87×)**
- the old shape → ORCA: **1752.6 ms → 4.9 ms (356×)**
- a dead required source costs **−0.6 ms**, not a timeout stall
- a 1500 ms source against a 400 ms budget is bounded at **p95 406 ms** — the timeout holds

### What the modes mean

`local_*` modes use zero-latency demo providers and therefore isolate **ORCA's own CPU
work**: about 5 ms, of which ~0.5 ms is NLU, ~1.5 ms is agent orchestration and ~1 ms is
the risk engine. That is the number that stays constant no matter where the user is.

`coastal_*` modes inject per-source round-trip latency (IMD 260 ms, INCOIS 320 ms, MOSDAC
420 ms) to imitate a real upstream over a weak mobile link. **These are stand-ins, not
measurements of IMD/INCOIS/MOSDAC** — we have not been able to measure those from a
whitelisted host, and we do not pretend otherwise. Override them with
`--source-latency IMD:400,INCOIS:500,MOSDAC:700` to model your own numbers.

`coastal_serial` reproduces the shape our earlier prototype had: agents run one at a time
and provider calls inside them run one at a time.

---

## The five levers, and what each is worth

### 1. Keep the language model off the critical path — the biggest single win

A marine query has about a dozen shapes. Rule-based NLU resolves language, intent,
activity, vessel, place and time in **~0.5 ms** with no network call
(`app/reasoning/nlu.py`, `app/reasoning/lexicon.py`). An LLM round-trip is 800–3000 ms and
it was on the critical path of every query in the old prototype.

The model is now a *fallback* consulted only when the rules return low confidence, and an
*optional* phrasing pass that is off by default. `test_no_llm_is_required_for_any_demo_query`
asserts that every one of the eleven demo scenarios completes with `llm_ms == 0.0`.

### 2. Fan out, don't queue up

The planner emits a DAG; the orchestrator groups it into waves and runs each wave with
`asyncio.gather`. For the flagship query:

```
wave 0   geospatial
wave 1   weather ‖ ocean ‖ hazard ‖ satellite     ← one round-trip, not four
wave 2   risk
wave 3   response
```

Every response reports `latency.parallel_saving_ms`, computed as the difference between
the *sum* of provider span durations and the *union* of their time intervals. It is a
measurement, not an assertion.

### 3. Quantised cache with in-flight de-duplication

Cache keys quantise position to a 0.25° grid (~27 km, matching typical marine model
spacing) and time to the hour. Two fishermen 2 km apart asking about the same hour share
one upstream call. Identical concurrent requests are collapsed into a single call by an
in-flight map — `test_identical_concurrent_requests_collapse_to_one_upstream_call`
asserts six simultaneous requests produce exactly one upstream fetch.

This is also why the hazard agent is free: it asks the same providers for the same
variables at the same instant as the weather and ocean agents, so it costs zero extra
network calls.

**The cache can never hide staleness.** Cached objects keep their original timestamps,
freshness is recomputed on read, and cached live data is relabelled `CACHED_LIVE`.

### 4. Selective invocation

The planner does not call every agent for every query, and records why it skipped each
one. `Show me the marine weather near Chennai` runs geospatial + weather + response and
skips ocean, satellite, PFZ, route and risk — hence the `fast_path` row at 3.3 ms and a
14.6 KB payload instead of 34.8 KB.

### 5. Bounded failure

Per-provider timeout (`ORCA_BUDGET_PROVIDER_MS`, default 1800 ms), one retry for
connection faults, **no retry on timeout** — a source that timed out is slow, not flaky,
and retrying spends the user's remaining budget asking the same slow thing again. A total
deadline bounds all attempts together. After four consecutive failures a circuit breaker
opens for 30 s so a dead source stops costing every user its full timeout.

The orchestrator also drops *optional* steps when the remaining budget is less than 60 %
of their deadline, and records that it did.

---

## Low-bandwidth and coastal connectivity

We are not claiming architecture creates bandwidth. We are claiming the payload and the
failure behaviour are designed for a bad link:

| Measure | Status |
|---|---|
| gzip on responses over 800 bytes | on (`GZipMiddleware`) — the evidence chain compresses ~8× |
| `low_bandwidth: true` request flag | drops map geometry and layer payloads, keeps the answer and the source cards byte-identical: 34.8 KB → 25.5 KB uncompressed, and far less after gzip |
| `include_trace: false` | drops the developer trace |
| text-first answer | the answer is a plain string; no client-side rendering is needed to read it |
| explicit timestamps in the answer | so a cached or stale reading is visible without opening a panel |
| partial results | one dead source degrades the answer, it does not fail the request |
| offline gazetteer and boundary layers | place resolution needs no network at all |

Still to build, and listed honestly in [limitations.md](limitations.md): service-worker
caching in the PWA, SMS/USSD fallback, and voice output.

---

## Reproducing

```bash
cd backend
python -m app.tools.benchmark                       # defaults, 60 iterations
python -m app.tools.benchmark --iterations 200 --json results.json
python -m app.tools.benchmark --source-latency IMD:800,INCOIS:900,MOSDAC:1200
```

Raw output from the run in the table above is committed at
[`benchmark-results.json`](benchmark-results.json).
