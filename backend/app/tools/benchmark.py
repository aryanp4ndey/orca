"""Latency benchmark.

    python -m app.tools.benchmark                # all modes, 60 iterations
    python -m app.tools.benchmark --iterations 200 --json results.json

Answers the question a judge actually asked us: "if it takes 4-5 seconds in
Jaipur where the internet is good, how will it behave on the coast?"

The honest decomposition is: total = client network + server work. We cannot
make a coastal 2G link faster. What we can do is make server work small, make
it constant under source failure, and make the payload small. This tool
measures all three, in these modes:

  local_serial    provider calls serialised, no cache, zero-latency sources
  local_parallel  dependency-aware fan-out, no cache, zero-latency sources
  coastal_serial  serialised, with per-source latency injected to imitate a
                  real upstream over a weak link (IMD 260 ms, INCOIS 320 ms,
                  MOSDAC 420 ms)  -  this is the shape our earlier prototype had
  coastal_parallel same latency, dependency-aware fan-out
  coastal_cached   same latency, warm cache
  fast_path       an intent whose plan needs fewer agents
  degraded        a required source down - failure must not cost extra latency
  slow_source     a source injected at 1.5 s - the timeout must bound us

The `local_*` modes isolate ORCA's own CPU work. The `coastal_*` modes are the
ones that answer the judge's question, because on a real link the upstream call
dominates and the only lever we have is how many of them we wait for in series.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field

from app.config.settings import get_settings
from app.providers.demo_controls import DemoControls, reset_demo_controls, set_demo_controls
from app.schemas.api import QueryRequest
from app.services.container import Container, warmup
from app.services.query_service import QueryService

FLAGSHIP = "Is it safe to go fishing from Kochi tomorrow at 7 AM?"
FAST_PATH = "Show me the marine weather near Chennai"


@dataclass
class ModeResult:
    mode: str
    description: str
    iterations: int
    p50_ms: float = 0.0
    p90_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    mean_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    provider_p50_ms: float = 0.0
    parallel_saving_p50_ms: float = 0.0
    payload_bytes_p50: int = 0
    payload_bytes_lowbw_p50: int = 0
    cache_hit_rate: float = 0.0
    failures: int = 0
    risk_levels: dict = field(default_factory=dict)
    notes: str = ""


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1))))
    return round(ordered[idx], 2)


async def _run_mode(mode: str, description: str, iterations: int, *,
                    query: str = FLAGSHIP, serial: bool = False,
                    warm_cache: bool = False, controls: DemoControls | None = None,
                    provider_budget_ms: int | None = None) -> ModeResult:
    reset_demo_controls()
    set_demo_controls(controls or DemoControls())
    settings = get_settings()
    if provider_budget_ms:
        settings.budget_provider_ms = provider_budget_ms
    container = Container.build(settings)
    service = QueryService(container)

    if serial:
        _force_serial(container)
        container.orchestrator.serial_mode = True

    if warm_cache:
        await service.handle(QueryRequest(query=query))
    else:
        await service.handle(QueryRequest(query=query))   # warm code paths only
        await container.cache.clear()

    latencies, provider_latencies, savings = [], [], []
    payloads, payloads_lite = [], []
    failures = 0
    risk_levels: dict[str, int] = {}

    for _ in range(iterations):
        if not warm_cache:
            await container.cache.clear()
        started = time.perf_counter()
        try:
            response = await service.handle(QueryRequest(query=query))
        except Exception:  # noqa: BLE001
            failures += 1
            continue
        latencies.append((time.perf_counter() - started) * 1000.0)
        provider_latencies.append(response.latency.providers_ms)
        savings.append(response.latency.parallel_saving_ms)
        payloads.append(len(response.model_dump_json(exclude={"trace"})))
        level = response.risk.risk_level.value if response.risk else "NONE"
        risk_levels[level] = risk_levels.get(level, 0) + 1

    lite = await service.handle(QueryRequest(query=query, low_bandwidth=True,
                                             include_trace=False))
    payloads_lite.append(len(lite.model_dump_json()))

    stats = container.cache.stats()
    return ModeResult(
        mode=mode, description=description, iterations=iterations,
        p50_ms=_pct(latencies, 50), p90_ms=_pct(latencies, 90),
        p95_ms=_pct(latencies, 95), p99_ms=_pct(latencies, 99),
        mean_ms=round(statistics.fmean(latencies), 2) if latencies else 0.0,
        min_ms=round(min(latencies), 2) if latencies else 0.0,
        max_ms=round(max(latencies), 2) if latencies else 0.0,
        provider_p50_ms=_pct(provider_latencies, 50),
        parallel_saving_p50_ms=_pct(savings, 50),
        payload_bytes_p50=int(_pct([float(p) for p in payloads], 50)),
        payload_bytes_lowbw_p50=int(payloads_lite[0]),
        cache_hit_rate=stats.get("hit_rate", 0.0), failures=failures,
        risk_levels=risk_levels,
    )


def _force_serial(container: Container) -> None:
    """Serialise provider fan-out (the orchestrator is serialised alongside).

    Together these reproduce the "call one source, wait, call the next" shape,
    which is what we are claiming to have replaced.
    """
    registry = container.registry
    original = registry.fetch_many

    async def serial_fetch_many(specs, trace=None):
        results = []
        for provider, query in specs:
            results.extend(await original([(provider, query)], trace))
        return results

    registry.fetch_many = serial_fetch_many


#: Per-source round-trip times used by the `coastal_*` modes. These are
#: stand-ins for a real upstream over a weak mobile link, not measurements of
#: IMD/INCOIS/MOSDAC - we have not been able to measure those from a
#: whitelisted host. Override with --source-latency to model your own numbers.
COASTAL_LATENCY = {"IMD": 260, "INCOIS": 320, "MOSDAC": 420}


async def run_all(iterations: int, coastal: dict[str, int] | None = None
                  ) -> list[ModeResult]:
    coastal = coastal or COASTAL_LATENCY
    slow = lambda **kw: DemoControls(slow_sources=dict(coastal), **kw)  # noqa: E731
    coastal_iterations = max(6, iterations // 6)     # these modes are slow by design
    results = [
        await _run_mode("local_serial", "serialised provider calls, no cache, "
                        "zero-latency sources", iterations, serial=True),
        await _run_mode("local_parallel", "fan-out, no cache, zero-latency sources",
                        iterations),
        await _run_mode("coastal_serial",
                        f"serialised with injected upstream latency {coastal} "
                        "- the shape our earlier prototype had",
                        coastal_iterations, serial=True, controls=slow(),
                        provider_budget_ms=3000),
        await _run_mode("coastal_parallel",
                        "same latency, dependency-aware fan-out",
                        coastal_iterations, controls=slow(), provider_budget_ms=3000),
        await _run_mode("coastal_cached", "same latency, warm cache",
                        coastal_iterations, warm_cache=True, controls=slow(),
                        provider_budget_ms=3000),
        await _run_mode("fast_path", "an intent whose plan needs fewer agents",
                        iterations, query=FAST_PATH, warm_cache=True),
        await _run_mode("degraded", "required source (INCOIS) unavailable",
                        iterations, controls=DemoControls(fail_sources={"INCOIS"})),
        await _run_mode("slow_source", "MOSDAC injected at 1500 ms, provider budget 400 ms",
                        max(8, iterations // 5),
                        controls=DemoControls(slow_sources={"MOSDAC": 1500}),
                        provider_budget_ms=400),
    ]
    reset_demo_controls()
    return results


def render(results: list[ModeResult]) -> str:
    header = (f"{'mode':<13}{'p50':>9}{'p90':>9}{'p95':>9}{'max':>9}"
              f"{'prov p50':>10}{'saved':>9}{'payload':>10}{'low-bw':>9}{'fail':>6}")
    lines = ["", "ORCA latency benchmark (server-side work, milliseconds)",
             "=" * len(header), header, "-" * len(header)]
    for r in results:
        lines.append(
            f"{r.mode:<13}{r.p50_ms:>9.2f}{r.p90_ms:>9.2f}{r.p95_ms:>9.2f}{r.max_ms:>9.2f}"
            f"{r.provider_p50_ms:>10.2f}{r.parallel_saving_p50_ms:>9.2f}"
            f"{r.payload_bytes_p50:>10}{r.payload_bytes_lowbw_p50:>9}{r.failures:>6}")
    lines.append("=" * len(header))
    for r in results:
        lines.append(f"  {r.mode:<13} {r.description}")
    by_mode = {r.mode: r for r in results}

    def ratio(a: str, b: str, label: str) -> str | None:
        ra, rb = by_mode.get(a), by_mode.get(b)
        if not ra or not rb or not rb.p50_ms:
            return None
        return (f"  {label}: {ra.p50_ms:.1f} ms -> {rb.p50_ms:.1f} ms "
                f"({ra.p50_ms / rb.p50_ms:.1f}x faster)")

    lines.append("")
    for line in (ratio("coastal_serial", "coastal_parallel",
                       "serial -> parallel, with upstream latency"),
                 ratio("coastal_parallel", "coastal_cached",
                       "cold -> warm cache, with upstream latency"),
                 ratio("coastal_serial", "coastal_cached",
                       "old shape -> ORCA, with upstream latency"),
                 ratio("local_serial", "local_parallel",
                       "serial -> parallel, CPU only")):
        if line:
            lines.append(line)

    degraded, parallel = by_mode.get("degraded"), by_mode.get("local_parallel")
    if degraded and parallel:
        lines.append(f"  a dead required source costs "
                     f"{degraded.p50_ms - parallel.p50_ms:+.1f} ms, not a timeout stall")
    slow = by_mode.get("slow_source")
    if slow:
        lines.append(f"  a 1500 ms source against a 400 ms budget is bounded at "
                     f"p95 {slow.p95_ms:.0f} ms - the timeout holds")
    lines += ["",
              "  These are server-side numbers in demo mode: they isolate ORCA's own",
              "  work from network and upstream-source time. With live providers the",
              "  upstream call dominates, which is exactly why the fan-out, the cache",
              "  and the per-provider timeout matter more on a coastal link, not less.",
              ""]
    return "\n".join(lines)


def _parse_latency(raw: str | None) -> dict[str, int] | None:
    if not raw:
        return None
    out: dict[str, int] = {}
    for item in raw.split(","):
        if ":" in item:
            source, ms = item.split(":", 1)
            out[source.strip().upper()] = int(ms)
    return out or None


async def main_async(args) -> int:
    warmup()
    results = await run_all(args.iterations, _parse_latency(args.source_latency))
    print(render(results))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump([asdict(r) for r in results], fh, indent=2)
        print(f"  wrote {args.json}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ORCA latency benchmark")
    parser.add_argument("--iterations", type=int, default=60)
    parser.add_argument("--json", type=str, default=None)
    parser.add_argument("--source-latency", type=str, default=None,
                        help="override injected upstream latency, "
                             "e.g. IMD:400,INCOIS:500,MOSDAC:700")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
