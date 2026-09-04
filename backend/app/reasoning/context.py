"""Multi-turn conversation context.

"What about 5 PM?" is the query that separates a demo from a product.  It has no
intent keyword, no place and no activity - all of that has to be inherited from
the previous turn, while the one thing the user *did* say (the time) overrides.

The rules, in order:
  * anything the current turn states explicitly always wins;
  * otherwise inherit location, activity, vessel and intent from the last turn
    that had them, within the session TTL;
  * record every inherited field in ``inherited_fields`` so the answer can say
    "for Kochi, fishing, at 5 PM today" instead of silently assuming;
  * a new explicit location resets the activity chain only if the user also
    changed the activity - changing place mid-conversation is normal.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from app.config.settings import get_settings
from app.core.clock import utcnow
from app.schemas.agent import QueryContext, TimeSpec
from app.schemas.common import Activity, Intent, Language, VesselClass
from app.schemas.geo import ResolvedLocation

INHERITABLE = ("location", "activity", "vessel", "intent", "language", "destination")


@dataclass
class Turn:
    query_id: str
    raw_query: str
    intent: Intent
    location: ResolvedLocation | None
    destination: ResolvedLocation | None
    activity: Activity
    vessel: VesselClass
    language: Language
    time: TimeSpec | None
    answer_summary: str = ""
    risk_level: str | None = None
    created_at: float = field(default_factory=time.time)


@dataclass
class Session:
    session_id: str
    turns: list[Turn] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)

    def latest_with(self, attr: str) -> Any:
        for turn in reversed(self.turns):
            value = getattr(turn, attr, None)
            if value not in (None, Activity.GENERIC, VesselClass.NONE, Intent.UNKNOWN):
                return value
        return None


class SessionStore:
    """In-process session store with TTL and a bounded size.

    Deliberately not a database: conversation state is small, per-user and
    disposable. ``Cache`` is the seam if this ever needs to survive a restart.
    """

    def __init__(self, ttl_seconds: int | None = None, max_sessions: int = 2000) -> None:
        s = get_settings()
        # `or` would silently turn an explicit 0 into the default.
        self.ttl = s.conversation_ttl_seconds if ttl_seconds is None else ttl_seconds
        self.max_turns = s.max_conversation_turns
        self.max_sessions = max_sessions
        self._sessions: OrderedDict[str, Session] = OrderedDict()

    def _evict(self) -> None:
        now = time.time()
        for sid in [k for k, v in self._sessions.items() if now - v.last_seen > self.ttl]:
            self._sessions.pop(sid, None)
        while len(self._sessions) > self.max_sessions:
            self._sessions.popitem(last=False)

    def get(self, session_id: str) -> Session:
        self._evict()
        session = self._sessions.get(session_id)
        if session is None:
            session = Session(session_id=session_id)
            self._sessions[session_id] = session
        session.last_seen = time.time()
        self._sessions.move_to_end(session_id)
        return session

    def append(self, session_id: str, turn: Turn) -> None:
        session = self.get(session_id)
        session.turns.append(turn)
        if len(session.turns) > self.max_turns:
            session.turns = session.turns[-self.max_turns:]

    def stats(self) -> dict:
        return {"sessions": len(self._sessions),
                "turns": sum(len(s.turns) for s in self._sessions.values())}


def apply_context(ctx: QueryContext, session: Session) -> QueryContext:
    """Fill unstated fields from the conversation, recording what was inherited."""
    inherited: list[str] = []

    if ctx.location is None:
        prior = session.latest_with("location")
        if prior is not None:
            ctx.location = prior
            inherited.append("location")

    if ctx.destination is None and ctx.intent is Intent.ROUTE_RISK:
        prior = session.latest_with("destination")
        if prior is not None:
            ctx.destination = prior
            inherited.append("destination")

    if ctx.activity is Activity.GENERIC:
        prior = session.latest_with("activity")
        if prior is not None:
            ctx.activity = prior
            inherited.append("activity")

    if ctx.vessel is VesselClass.NONE:
        prior = session.latest_with("vessel")
        if prior is not None:
            ctx.vessel = prior
            inherited.append("vessel")

    if ctx.intent in (Intent.UNKNOWN,):
        prior = session.latest_with("intent")
        if prior is not None:
            ctx.intent = prior
            ctx.intent_confidence = max(ctx.intent_confidence, 0.75)
            inherited.append("intent")

    if ctx.time is None:
        prior_turn = session.turns[-1] if session.turns else None
        if prior_turn is not None and prior_turn.time is not None:
            ctx.time = prior_turn.time
            inherited.append("time")

    ctx.inherited_fields = inherited
    return ctx


def summarise(session: Session, limit: int = 4) -> list[dict]:
    return [
        {"query": t.raw_query, "intent": t.intent.value,
         "location": t.location.name if t.location else None,
         "risk": t.risk_level,
         "time": t.time.target.isoformat() if t.time else None}
        for t in session.turns[-limit:]
    ]
