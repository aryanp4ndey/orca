"""Grounding check: no number reaches the user that is not in the evidence.

This is the mechanical enforcement of ORCA's central rule.  Whatever produced
the answer text - our templates or a language model - the text is scanned for
numeric tokens and every one of them must correspond to a value in the evidence
ledger, a threshold from the risk ruleset, a deterministic computation, or the
timestamps being reported.

For the template path this is a self-check that catches our own bugs.  For the
LLM path it is a hard guard: a model that invents "waves of 3.5 m" when the
evidence says 2.1 m fails the check and its output is discarded in favour of the
template answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NUMBER = re.compile(r"(?<![\w.])(\d{1,4}(?:[.,]\d{1,3})?)(?![\w])")
REL_TOLERANCE = 0.02


@dataclass
class GroundingReport:
    ok: bool
    ungrounded: list[str] = field(default_factory=list)
    checked: int = 0

    def as_dict(self) -> dict:
        return {"ok": self.ok, "ungrounded": self.ungrounded, "checked": self.checked}


def collect_allowed(*groups) -> set[float]:
    """Flatten every number ORCA is entitled to say."""
    allowed: set[float] = set()
    for group in groups:
        for value in group:
            if value is None:
                continue
            try:
                allowed.add(round(float(value), 4))
            except (TypeError, ValueError):
                continue
    return allowed


def check(text: str, allowed: set[float]) -> GroundingReport:
    ungrounded: list[str] = []
    checked = 0
    for match in NUMBER.finditer(text):
        raw = match.group(1).replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            continue
        checked += 1
        if any(abs(value - a) <= max(REL_TOLERANCE * abs(a), 0.051) for a in allowed):
            continue
        ungrounded.append(match.group(1))
    return GroundingReport(ok=not ungrounded, ungrounded=ungrounded, checked=checked)


def numbers_in_timestamp(dt) -> list[float]:
    """Date and clock components are legitimate numbers in an answer."""
    if dt is None:
        return []
    return [float(dt.year), float(dt.month), float(dt.day),
            float(dt.hour), float(dt.minute),
            float(f"{dt.hour}.{dt.minute:02d}") if dt.minute else float(dt.hour),
            float(dt.hour % 12 or 12)]
