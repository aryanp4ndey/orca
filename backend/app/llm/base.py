"""LLM abstraction.

ORCA's position on language models is deliberately narrow, and it is the single
most important safety property of the system:

    The LLM decides WHAT TO ASK. Authoritative sources decide WHAT IS TRUE.

Concretely, an LLM in ORCA may only:
  * disambiguate an intent the rule-based NLU could not classify;
  * fill the same typed :class:`QueryContext` fields the rules would have;
  * phrase an explanation whose numbers are supplied to it verbatim.

It may never: retrieve data, compute a distance, choose a risk level, invent a
timestamp, or fill in a missing measurement.  Those are all deterministic code
paths, and the response builder validates that every number in the final text
appears in the evidence ledger.

Every method is timeout-bounded and every failure degrades to the rule-based
path, so a slow or missing model cannot slow down or break a marine answer.
"""

from __future__ import annotations

import abc
import json
from typing import Any


class LLMUnavailable(RuntimeError):
    pass


class LLMClient(abc.ABC):
    name: str = "abstract"
    model: str | None = None

    @property
    def available(self) -> bool:
        return False

    @abc.abstractmethod
    async def complete_json(self, system: str, user: str,
                            timeout_ms: int) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def complete_text(self, system: str, user: str,
                            timeout_ms: int, max_tokens: int = 400) -> str: ...

    def info(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "available": self.available}


class NullLLM(LLMClient):
    """The default. ORCA is fully functional with no model configured at all."""

    name = "none"

    @property
    def available(self) -> bool:
        return False

    async def complete_json(self, system: str, user: str, timeout_ms: int) -> dict:
        raise LLMUnavailable("no LLM configured (ORCA_LLM_PROVIDER=none)")

    async def complete_text(self, system: str, user: str, timeout_ms: int,
                            max_tokens: int = 400) -> str:
        raise LLMUnavailable("no LLM configured (ORCA_LLM_PROVIDER=none)")


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start, depth = text.find("{"), 0
    if start < 0:
        raise ValueError("no JSON object in model response")
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unterminated JSON object in model response")
