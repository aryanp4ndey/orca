"""Deterministic natural-language understanding.

This is the fast path, and it is the single biggest reason ORCA can answer in
milliseconds where our earlier prototype took 4-5 seconds: **a marine query does
not need a language model to be understood.**  Intent, language, activity,
vessel, place and time are all extracted here by rules, in well under a
millisecond, with no network call.

The LLM is a *fallback*, not a stage.  It is consulted only when this module
returns low confidence, and even then it is only allowed to fill in the same
typed fields - it never sees a marine measurement and never decides a risk.

Everything language-specific lives in ``lexicon.py``; the logic below is
language-independent, which is what makes the internal representation identical
for "Is it safe to fish from Kochi tomorrow at 7 AM?" and its Hindi, Malayalam
and Tamil equivalents.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core.clock import IST, ensure_utc, utcnow
from app.geo.gazetteer import Place, get_gazetteer
from app.reasoning.lexicon import (
    ACTIVITY_TERMS,
    CLOCK_SUFFIXES,
    DAY_OFFSETS,
    INTENT_TERMS,
    NOW_TERMS,
    PART_OF_DAY,
    ROMAN_HI_MARKERS,
    SCRIPT_RANGES,
    VESSEL_TERMS,
)
from app.schemas.agent import TimeSpec
from app.schemas.common import Activity, Intent, Language, VesselClass

_CLOCK = re.compile(
    r"(?<![\d:])(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?(?![\d])",
    re.IGNORECASE)
_SUFFIX_CLOCK = re.compile(
    r"(?<![\d:])(\d{1,2})(?:[:.](\d{2}))?\s*(" + "|".join(map(re.escape, CLOCK_SUFFIXES)) + ")",
    re.IGNORECASE)


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).strip().lower())


# ---------------------------------------------------------------- language --
def detect_language(text: str, override: Language | None = None) -> Language:
    if override is not None:
        return override
    counts: dict[str, int] = {}
    for ch in text:
        cp = ord(ch)
        for code, lo, hi in SCRIPT_RANGES:
            if lo <= cp <= hi:
                counts[code] = counts.get(code, 0) + 1
                break
    if counts:
        best = max(counts, key=counts.get)
        try:
            return Language(best)
        except ValueError:
            return Language.EN
    tokens = set(re.findall(r"[a-z']+", text.lower()))
    if len(tokens & ROMAN_HI_MARKERS) >= 2:
        return Language.HI
    return Language.EN


# ------------------------------------------------------------------ intent --
def classify_intent(text: str) -> tuple[Intent, float, dict[str, float]]:
    norm = normalise(text)
    scores: dict[Intent, float] = {}
    for intent, terms in INTENT_TERMS.items():
        total = 0.0
        for weight, term in terms:
            if term in norm:
                total += weight
        if total:
            scores[intent] = total

    if not scores:
        return Intent.UNKNOWN, 0.0, {}

    # Composite disambiguation. "Is it safe to fish" hits both MARINE_SAFETY and
    # a fishing term; safety must win. "Why is fishing lower at 5 PM" hits
    # ANALYTICAL and PFZ; the question word wins.
    if Intent.ANALYTICAL in scores and scores[Intent.ANALYTICAL] >= 3.0:
        scores[Intent.ANALYTICAL] += 1.5
    if Intent.MARINE_SAFETY in scores and Intent.SEA_CONDITION in scores:
        scores[Intent.MARINE_SAFETY] += 1.0
    if Intent.ROUTE_RISK in scores:
        scores[Intent.ROUTE_RISK] += 1.0

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top, top_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = top_score - runner_up
    confidence = min(0.99, 0.45 + 0.09 * top_score + 0.07 * margin)
    return top, round(confidence, 3), {i.value: round(s, 2) for i, s in ranked}


def detect_activity(text: str) -> tuple[Activity, float]:
    norm = normalise(text)
    for activity, terms in ACTIVITY_TERMS.items():
        for t in terms:
            if t in norm:
                return activity, 0.9
    return Activity.GENERIC, 0.3


def detect_vessel(text: str) -> VesselClass:
    norm = normalise(text)
    for vessel, terms in VESSEL_TERMS.items():
        for t in terms:
            if t in norm:
                return vessel
    return VesselClass.NONE


def detect_places(text: str) -> list[Place]:
    return get_gazetteer().search_in_text(text)


# -------------------------------------------------------------------- time --
@dataclass
class ClockHit:
    hour: int
    minute: int
    meridiem: str | None
    position: int
    explicit_meridiem: bool


def _find_clocks(norm: str) -> list[ClockHit]:
    hits: list[ClockHit] = []
    for m in _SUFFIX_CLOCK.finditer(norm):
        h = int(m.group(1))
        if 0 <= h <= 24:
            hits.append(ClockHit(h, int(m.group(2) or 0), None, m.start(), False))
    consumed = {(h.position) for h in hits}
    for m in _CLOCK.finditer(norm):
        if m.start() in consumed:
            continue
        h = int(m.group(1))
        mins = int(m.group(2) or 0)
        mer = (m.group(3) or "").replace(".", "").lower() or None
        # A bare number with no meridiem, no clock suffix and no colon is
        # usually not a time ("2 boats", "26176"). Require some signal.
        if mer is None and m.group(2) is None:
            after = norm[m.end(): m.end() + 12]
            before = norm[max(0, m.start() - 14): m.start()]
            if not any(k in after or k in before for k in
                       ("am", "pm", "o'clock", "hrs", "at ", "by ", "around ",
                        "after ", "before ", "and ", "to ")):
                continue
        if h > 24 or (mer and h > 12):
            continue
        hits.append(ClockHit(h, mins, mer, m.start(), mer is not None))
    hits.sort(key=lambda h: h.position)
    return hits


def _day_offset(norm: str) -> tuple[int | None, str | None]:
    for term, offset in DAY_OFFSETS:
        if term in norm:
            return offset, term
    return None, None


def _part_of_day(norm: str) -> tuple[int | None, str | None]:
    best: tuple[int, str] | None = None
    for term, hour in PART_OF_DAY:
        if term in norm:
            if best is None or len(term) > len(best[1]):
                best = (hour, term)
    return (best[0], best[1]) if best else (None, None)


def _resolve_hour(hit: ClockHit, part_hour: int | None) -> int:
    h = hit.hour
    if hit.meridiem:
        if hit.meridiem.startswith("p") and h < 12:
            h += 12
        elif hit.meridiem.startswith("a") and h == 12:
            h = 0
        return h % 24
    if h > 12:
        return h % 24
    if part_hour is not None:
        # "7 baje subah" -> 07; "5 baje shaam" -> 17
        if part_hour >= 12 and h < 12:
            return (h + 12) % 24
        return h % 24
    # No meridiem and no part-of-day: marine departures skew to early morning,
    # but we do not guess silently - the caller marks this low confidence.
    return h % 24


def _build(target_ist: datetime, raw: str, explicit: bool, now: datetime,
           resolver: str = "rules", span_hours: float = 3.0) -> TimeSpec:
    target_utc = ensure_utc(target_ist)
    return TimeSpec(
        target=target_utc,
        window_start=target_utc - timedelta(minutes=30),
        window_end=target_utc + timedelta(hours=span_hours),
        is_explicit=explicit, raw=raw,
        horizon_hours=round((target_utc - ensure_utc(now)).total_seconds() / 3600.0, 2),
        resolver=resolver,
    )


def parse_time(text: str, now: datetime | None = None) -> tuple[TimeSpec | None, list[TimeSpec]]:
    """Return (primary time, additional windows for comparison queries)."""
    now = ensure_utc(now or utcnow())
    now_ist = now.astimezone(IST)
    norm = normalise(text)

    if any(t in norm for t in NOW_TERMS) and not _find_clocks(norm):
        return _build(now_ist, "now", True, now, span_hours=1.0), []

    offset, offset_term = _day_offset(norm)
    part_hour, part_term = _part_of_day(norm)
    clocks = _find_clocks(norm)

    base_date = (now_ist + timedelta(days=offset or 0)).date()

    def at(hour: int, minute: int = 0) -> datetime:
        dt = datetime(base_date.year, base_date.month, base_date.day,
                      hour, minute, tzinfo=IST)
        # "at 7 AM" with no day word, already past today -> they mean tomorrow.
        if offset is None and dt < now_ist - timedelta(minutes=10):
            dt += timedelta(days=1)
        return dt

    def today_or_now(hour: int, minute: int = 0) -> datetime:
        """For a day reference with no clock time, never point into the past."""
        dt = at(hour, minute)
        return max(dt, now_ist) if offset == 0 else dt

    # Comparison window: "between 5 PM and 10 PM"
    if len(clocks) >= 2 and any(m in norm for m in
                                ("between", "and", " to ", "from", "से", "तक")):
        windows = []
        for hit in clocks[:2]:
            h = _resolve_hour(hit, part_hour)
            windows.append(_build(at(h, hit.minute),
                                  f"{hit.hour}{':%02d' % hit.minute if hit.minute else ''}"
                                  f"{hit.meridiem or ''}", True, now, span_hours=1.0))
        primary = windows[0]
        return primary, windows

    if clocks:
        hit = clocks[0]
        h = _resolve_hour(hit, part_hour)
        raw = " ".join(x for x in (offset_term, part_term,
                                   f"{hit.hour:02d}:{hit.minute:02d}") if x)
        return _build(at(h, hit.minute), raw, True, now), []

    if part_hour is not None:
        raw = " ".join(x for x in (offset_term, part_term) if x)
        return _build(today_or_now(part_hour), raw, True, now), []

    if offset is not None:
        # A day with no hour: for marine activity the working assumption is the
        # early-morning departure window, and we say so in the answer. For
        # "today" we never look backwards - we start from now.
        return _build(today_or_now(6), offset_term or "", True, now), []

    return None, []


# ------------------------------------------------------------------ result --
@dataclass
class NLUResult:
    language: Language
    intent: Intent
    intent_confidence: float
    intent_scores: dict[str, float]
    activity: Activity
    activity_confidence: float
    vessel: VesselClass
    places: list[Place]
    time: TimeSpec | None
    analysis_windows: list[TimeSpec] = field(default_factory=list)
    resolver: str = "rules"
    needs_llm: bool = False
    reasons: list[str] = field(default_factory=list)


LOW_CONFIDENCE = 0.62


def understand(text: str, *, now: datetime | None = None,
               language_override: Language | None = None) -> NLUResult:
    language = detect_language(text, language_override)
    intent, confidence, scores = classify_intent(text)
    activity, act_conf = detect_activity(text)
    vessel = detect_vessel(text)
    places = detect_places(text)
    time_spec, windows = parse_time(text, now)

    reasons: list[str] = []
    if intent is Intent.UNKNOWN:
        reasons.append("no intent keyword matched")
    if confidence < LOW_CONFIDENCE:
        reasons.append(f"intent confidence {confidence} below {LOW_CONFIDENCE}")
    if not places:
        reasons.append("no known place found in query")

    return NLUResult(
        language=language, intent=intent, intent_confidence=confidence,
        intent_scores=scores, activity=activity, activity_confidence=act_conf,
        vessel=vessel, places=places, time=time_spec, analysis_windows=windows,
        resolver="rules",
        needs_llm=(intent is Intent.UNKNOWN or confidence < LOW_CONFIDENCE),
        reasons=reasons,
    )
