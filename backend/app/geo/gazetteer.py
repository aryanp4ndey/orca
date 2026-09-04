"""Offline place resolution for the Indian coast.

Deliberately offline.  A fisherman on a 2G connection at 05:30 should not wait
on a geocoding API to find out that "Kochi" is at 9.93 N, 76.27 E.  The
gazetteer resolves in microseconds, works with no network at all, and matches
Malayalam/Tamil/Hindi/Devanagari spellings as well as English ones.

An online geocoder can be layered *behind* this for places we do not carry -
see :class:`app.providers.gis.base.GISProvider`.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from app.geo.geodesy import destination_point, distance_km
from app.schemas.geo import GeoPoint, ResolvedLocation

_WS = re.compile(r"[^a-z0-9ऀ-෿ ]+")


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).strip().lower()
    t = _WS.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


_INDIC = re.compile(r"[\u0900-\u0DFF]")


@lru_cache(maxsize=4096)
def _pattern_for(key: str) -> "re.Pattern[str]":
    """Match a gazetteer key inside free text.

    Malayalam, Tamil and the other Indic scripts are agglutinative: "Kochi" in
    Malayalam appears as കൊച്ചിയിൽ ("in Kochi") with the case marker fused onto
    the stem. Requiring a word boundary *after* the name - correct for English -
    would make every inflected mention invisible, so for Indic keys we anchor
    only the start of the name.
    """
    if _INDIC.search(key):
        return re.compile(rf"(?<![\u0900-\u0DFF]){re.escape(key)}")
    return re.compile(rf"(?<![\w\u0900-\u0DFF]){re.escape(key)}(?![\w\u0900-\u0DFF])")


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    state: str
    lat: float
    lon: float
    kind: str
    seaward_bearing: float
    aliases: tuple[str, ...]
    local_names: tuple[tuple[str, str], ...]
    landing_centre: str | None = None

    @property
    def point(self) -> GeoPoint:
        return GeoPoint(lat=self.lat, lon=self.lon)

    def offshore_point(self, km: float = 6.0) -> GeoPoint:
        """A deterministic retrieval point at sea off this place.

        Marine models have no valid value on land, so for a shore location we
        step ``km`` seaward along the recorded coast-normal bearing.  This is a
        *computed* point and is reported as such in the evidence.
        """
        return destination_point(self.point, self.seaward_bearing, km)

    def names_dict(self) -> dict[str, str]:
        return dict(self.local_names)


class Gazetteer:
    def __init__(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        self.dataset_id: str = raw["dataset_id"]
        self.version: str = raw["version"]
        self.precision_note: str = raw.get("precision_note", "")
        self.places: dict[str, Place] = {}
        self._index: dict[str, str] = {}
        for p in raw["places"]:
            place = Place(
                id=p["id"], name=p["name"], state=p["state"], lat=p["lat"], lon=p["lon"],
                kind=p["kind"], seaward_bearing=float(p.get("seaward_bearing", 270)),
                aliases=tuple(p.get("aliases", [])),
                local_names=tuple(sorted(p.get("local_names", {}).items())),
                landing_centre=p.get("landing_centre"),
            )
            self.places[place.id] = place
            for key in (place.name, place.id.replace("_", " "), *place.aliases,
                        *[v for _, v in place.local_names]):
                self._index.setdefault(normalise(key), place.id)

    # ---- lookup -----------------------------------------------------------
    def get(self, place_id: str) -> Place | None:
        return self.places.get(place_id)

    def find(self, text: str) -> Place | None:
        """Exact-ish match on a normalised name/alias/local name."""
        key = normalise(text)
        if not key:
            return None
        pid = self._index.get(key)
        if pid:
            return self.places[pid]
        # tolerate trailing descriptors: "kochi port", "chennai city"
        for suffix in (" port", " harbour", " harbor", " city", " beach",
                       " coast", " se", " me", " ka", " ke", " se jana"):
            if key.endswith(suffix):
                pid = self._index.get(key[: -len(suffix)].strip())
                if pid:
                    return self.places[pid]
        return None

    def search_in_text(self, text: str) -> list[Place]:
        """Gazetteer places occurring in free text, returned in reading order.

        Overlapping candidates are resolved longest-match-first ("Port Blair"
        beats "port"), then the surviving matches are ordered by position so
        that "from Kochi to Mangaluru" yields [Kochi, Mangaluru] - which is what
        route planning needs.
        """
        norm = normalise(text)
        spans: list[tuple[int, int, Place]] = []
        for key, pid in self._index.items():
            if not key:
                continue
            for m in re.finditer(_pattern_for(key), norm):
                spans.append((m.start(), m.end(), self.places[pid]))
        spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
        chosen: list[tuple[int, int, Place]] = []
        for start, end, place in spans:
            if any(not (end <= cs or start >= ce) for cs, ce, _ in chosen):
                continue
            if any(place.id == p.id for _, _, p in chosen):
                continue
            chosen.append((start, end, place))
        return [p for _, _, p in sorted(chosen, key=lambda c: c[0])]

    def nearest(self, point: GeoPoint, limit: int = 1) -> list[tuple[Place, float]]:
        scored = [(p, distance_km(point, p.point)) for p in self.places.values()]
        scored.sort(key=lambda s: s[1])
        return scored[:limit]

    def to_resolved(self, place: Place, query: str, *, offshore_km: float = 6.0,
                    use_offshore: bool = True) -> ResolvedLocation:
        point = place.offshore_point(offshore_km) if use_offshore else place.point
        return ResolvedLocation(
            query=query,
            name=place.name,
            local_names=place.names_dict(),
            point=point,
            kind=place.kind,
            state=place.state,
            is_marine_point=use_offshore,
            distance_to_coast_km=offshore_km if use_offshore else 0.0,
            resolver="gazetteer",
            confidence=0.95,
            source_dataset=f"{self.dataset_id}@{self.version}",
        )


@lru_cache(maxsize=1)
def get_gazetteer() -> Gazetteer:
    from app.config.settings import get_settings
    return Gazetteer(os.path.join(get_settings().data_dir, "gazetteer.json"))
