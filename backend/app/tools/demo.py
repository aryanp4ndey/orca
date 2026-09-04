"""Scripted demo runner.

    python -m app.tools.demo                 # every scenario, in order
    python -m app.tools.demo --id d1         # just the flagship
    python -m app.tools.demo --failures      # the failure-behaviour set

Exists so the demo is a command, not a memorised sequence. Anyone on the team
can run it, and it prints the same thing every time.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.config.settings import get_settings
from app.providers.demo_controls import DemoControls, reset_demo_controls, set_demo_controls
from app.schemas.api import QueryRequest
from app.services.container import Container, warmup
from app.services.query_service import QueryService
from app.tools.demo_queries import DEFAULT_DEMO_POINT, DEMO_QUERIES

RULE = "=" * 78


def show(title: str, response) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")
    print(f"> {response.answer}\n")
    print(f"  intent      : {response.intent['value']} "
          f"(confidence {response.intent['confidence']}, via {response.intent['resolver']})")
    if response.intent.get("inherited"):
        print(f"  inherited   : {', '.join(response.intent['inherited'])}")
    if response.location:
        print(f"  location    : {response.location['name']} "
              f"({response.location['point']['lat']:.4f}, {response.location['point']['lon']:.4f}) "
              f"via {response.location['resolver']}")
    if response.risk:
        print(f"  risk        : {response.risk.risk_level.value} "
              f"score {response.risk.risk_score} "
              f"confidence {response.risk.confidence} "
              f"decision {response.risk.decision_status.value}")
        for factor in response.risk.factors[:4]:
            print(f"                - {factor.label}: {factor.value} {factor.unit or ''} "
                  f"[{factor.level.value}] {factor.rationale}")
    print(f"  origin      : {response.data_origin.value} "
          f"(demo_mode={response.demo_mode})  freshness: {response.freshness.overall.value}")
    print(f"  sources     : " + ", ".join(
        f"{s.source.value}={s.status}/{s.freshness.value}"
        f"{'(cache)' if s.cache_hit else ''}" for s in response.sources) or "none")
    if response.conflicts:
        for conflict in response.conflicts:
            print(f"  conflict    : {conflict.variable} {conflict.severity} - {conflict.explanation}")
    print(f"  evidence    : {len(response.evidence)} rows")
    print(f"  latency     : total {response.latency.total_ms} ms "
          f"(providers {response.latency.providers_ms}, "
          f"parallel saving {response.latency.parallel_saving_ms}, "
          f"llm {response.latency.llm_ms})")
    if response.trace:
        print(f"  plan        : {response.trace.plan.get('waves')}")
        skipped = response.trace.plan.get("skipped") or {}
        for capability, reason in list(skipped.items())[:3]:
            print(f"                skipped {capability}: {reason}")


async def run_queries(service, only: str | None) -> None:
    session_id = None
    for demo in DEMO_QUERIES:
        if only and demo["id"] != only:
            continue
        request = QueryRequest(
            query=demo["query"], session_id=session_id,
            lat=DEFAULT_DEMO_POINT["lat"] if demo.get("needs_location") else None,
            lon=DEFAULT_DEMO_POINT["lon"] if demo.get("needs_location") else None)
        response = await service.handle(request)
        session_id = response.session_id
        show(f"[{demo['id']}] {demo['title']}  -  \"{demo['query']}\"", response)
        print(f"  shows       : {', '.join(demo['shows'])}")


FAILURE_CASES = [
    ("Required source down (INCOIS)", DemoControls(fail_sources={"INCOIS"}),
     "wave height missing -> advisory WITHHELD, never guessed"),
    ("Optional source down (MOSDAC)", DemoControls(fail_sources={"MOSDAC"}),
     "answer proceeds, the gap is stated"),
    ("Stale sources", DemoControls(stale_sources={"IMD", "INCOIS"}),
     "advisory DEGRADED, confidence cut, user warned"),
    ("Sources disagree on wind", DemoControls(inject_conflict=True),
     "both claims kept, IMD wins by policy, confidence cut, nothing averaged"),
    ("Rough conditions", DemoControls(scenario="rough"), "risk escalates"),
    ("Pre-cyclone conditions", DemoControls(scenario="pre_cyclone"),
     "authority warning forces CRITICAL"),
]


async def run_failures(settings) -> None:
    for title, controls, expectation in FAILURE_CASES:
        reset_demo_controls()
        set_demo_controls(controls)
        container = Container.build(settings)
        service = QueryService(container)
        response = await service.handle(QueryRequest(
            query="Is it safe to go fishing from Kochi tomorrow at 7 AM?"))
        show(f"[failure] {title}", response)
        print(f"  expected    : {expectation}")
    reset_demo_controls()


async def main_async(args) -> int:
    warmup()
    settings = get_settings()
    if not settings.demo_mode:
        print("WARNING: ORCA_DEMO_MODE is false; this script drives the demo providers.")
    if args.failures:
        await run_failures(settings)
    else:
        await run_queries(QueryService(Container.build(settings)), args.id)
    print(f"\n{RULE}\nDemo complete. Nothing above required a language model.\n{RULE}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ORCA scripted demo")
    parser.add_argument("--id", help="run a single scenario id, e.g. d1")
    parser.add_argument("--failures", action="store_true",
                        help="run the failure-behaviour scenarios instead")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
