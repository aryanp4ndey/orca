"""Runtime switches for demo mode.

These exist so that "what happens when INCOIS is down?" is something we can
*show*, on stage, in one environment variable - and something the test suite
asserts on - rather than something we claim in a slide.

    ORCA_DEMO_SCENARIO=rough
    ORCA_DEMO_FAIL_SOURCES=INCOIS
    ORCA_DEMO_SLOW_SOURCES=IMD:2500
    ORCA_DEMO_STALE_SOURCES=IMD
    ORCA_DEMO_CONFLICT=true
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _csv(name: str) -> set[str]:
    raw = os.environ.get(name, "")
    return {x.strip().upper() for x in raw.split(",") if x.strip()}


def _csv_kv(name: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in os.environ.get(name, "").split(","):
        if ":" in item:
            k, v = item.split(":", 1)
            try:
                out[k.strip().upper()] = int(v)
            except ValueError:
                continue
    return out


@dataclass
class DemoControls:
    scenario: str = "normal"
    fail_sources: set[str] = field(default_factory=set)
    slow_sources: dict[str, int] = field(default_factory=dict)
    stale_sources: set[str] = field(default_factory=set)
    inject_conflict: bool = False

    @classmethod
    def from_env(cls) -> "DemoControls":
        return cls(
            scenario=os.environ.get("ORCA_DEMO_SCENARIO", "normal").strip().lower(),
            fail_sources=_csv("ORCA_DEMO_FAIL_SOURCES"),
            slow_sources=_csv_kv("ORCA_DEMO_SLOW_SOURCES"),
            stale_sources=_csv("ORCA_DEMO_STALE_SOURCES"),
            inject_conflict=os.environ.get("ORCA_DEMO_CONFLICT", "").lower()
            in ("1", "true", "yes"),
        )

    def snapshot(self) -> dict:
        return {
            "scenario": self.scenario,
            "fail_sources": sorted(self.fail_sources),
            "slow_sources": self.slow_sources,
            "stale_sources": sorted(self.stale_sources),
            "inject_conflict": self.inject_conflict,
        }


_controls: DemoControls | None = None


def get_demo_controls() -> DemoControls:
    global _controls
    if _controls is None:
        _controls = DemoControls.from_env()
    return _controls


def set_demo_controls(c: DemoControls) -> None:
    global _controls
    _controls = c


def reset_demo_controls() -> None:
    global _controls
    _controls = None
