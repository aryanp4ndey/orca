"""Per-request tracing.

Judges will ask "how exactly did that answer get generated?".  The answer is a
:class:`Trace`: a flat list of timed spans covering NLU, planning, every agent,
every provider call, the risk engine and response generation.  It is attached to
the API response when ``ORCA_EXPOSE_TRACE_IN_RESPONSE`` is on.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from app.schemas.api import QueryTrace, TraceSpan


@dataclass
class Span:
    name: str
    kind: str
    start_ms: float
    duration_ms: float = 0.0
    status: str = "OK"
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    query_id: str
    t0: float = field(default_factory=time.perf_counter)
    spans: list[Span] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    cache: dict[str, Any] = field(default_factory=lambda: {"hits": 0, "misses": 0, "keys": []})

    # ---- timing ----------------------------------------------------------
    def now_ms(self) -> float:
        return (time.perf_counter() - self.t0) * 1000.0

    @contextmanager
    def span(self, name: str, kind: str, **attrs: Any) -> Iterator[Span]:
        s = Span(name=name, kind=kind, start_ms=self.now_ms(), attributes=dict(attrs))
        self.spans.append(s)
        started = time.perf_counter()
        try:
            yield s
        except Exception as exc:  # noqa: BLE001 - trace must record then re-raise
            s.status = "ERROR"
            s.attributes["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            s.duration_ms = (time.perf_counter() - started) * 1000.0

    def add_span(self, name: str, kind: str, start_ms: float,
                 duration_ms: float, status: str = "OK", **attrs: Any) -> Span:
        s = Span(name, kind, start_ms, duration_ms, status, dict(attrs))
        self.spans.append(s)
        return s

    # ---- bookkeeping ------------------------------------------------------
    def note(self, msg: str) -> None:
        self.notes.append(msg)

    def cache_hit(self, key: str) -> None:
        self.cache["hits"] += 1
        self.cache["keys"].append({"key": key, "hit": True})

    def cache_miss(self, key: str) -> None:
        self.cache["misses"] += 1
        self.cache["keys"].append({"key": key, "hit": False})

    # ---- aggregation ------------------------------------------------------
    def total_ms(self) -> float:
        return self.now_ms()

    def sum_kind(self, kind: str) -> float:
        return sum(s.duration_ms for s in self.spans if s.kind == kind)

    def per_name(self, kind: str) -> dict[str, float]:
        out: dict[str, float] = {}
        for s in self.spans:
            if s.kind == kind:
                out[s.name] = round(out.get(s.name, 0.0) + s.duration_ms, 2)
        return out

    def wall_clock_of_kind(self, kind: str) -> float:
        """Union of span intervals - i.e. real elapsed time, not the sum.

        The gap between :meth:`sum_kind` and this is exactly what parallelism
        bought us, which is the number we report as ``parallel_saving_ms``.
        """
        intervals = sorted(
            (s.start_ms, s.start_ms + s.duration_ms)
            for s in self.spans if s.kind == kind
        )
        if not intervals:
            return 0.0
        total, cur_s, cur_e = 0.0, *intervals[0]
        for s, e in intervals[1:]:
            if s > cur_e:
                total += cur_e - cur_s
                cur_s, cur_e = s, e
            else:
                cur_e = max(cur_e, e)
        return total + (cur_e - cur_s)

    def to_schema(self) -> QueryTrace:
        return QueryTrace(
            query_id=self.query_id,
            plan=self.plan,
            spans=[
                TraceSpan(
                    name=s.name, kind=s.kind, start_ms=round(s.start_ms, 2),
                    duration_ms=round(s.duration_ms, 2), status=s.status,
                    attributes=s.attributes,
                )
                for s in self.spans
            ],
            cache=self.cache,
            notes=self.notes,
        )
