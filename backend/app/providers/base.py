"""Provider interface.

An agent asks for *canonical variables at a point and time*.  It never knows
whether the answer came from an ERDDAP grid, an IMD bulletin, a cached entry or
a demo fixture - only the :class:`ProviderResult` envelope, which always says.

Three rules every implementation must honour:

1. **Never raise into an agent.**  Return a result whose ``status`` says what
   went wrong.  Partial answers are better than exceptions in a safety system.
2. **Always normalise.**  Values are converted to the canonical unit for their
   variable, and the conversion is recorded in ``transformation``.
3. **Always timestamp.**  ``issued_at`` / ``valid_time`` / ``retrieved_at`` are
   distinct and all three matter to the freshness layer.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import Sequence

from app.core.clock import utcnow
from app.observability.logging import get_logger
from app.schemas.common import DataOrigin, Source, SourceStatus
from app.schemas.marine import ProviderQuery, ProviderResult

log = get_logger("orca.provider")


@dataclass(frozen=True)
class ProviderCapability:
    """What a provider can answer, and how current its answers ever are."""

    variables: tuple[str, ...]
    datasets: tuple[str, ...]
    update_frequency_seconds: int
    max_acceptable_age_seconds: int
    cache_ttl_seconds: int
    supports_forecast: bool = True
    supports_advisories: bool = False
    supports_pfz: bool = False
    spatial_coverage: str = "global"
    temporal_coverage: str = "unspecified"
    notes: str = ""


@dataclass
class ProviderDescriptor:
    provider_id: str
    source: Source
    origin: DataOrigin
    role: str
    capability: ProviderCapability
    attribution: str
    access_mechanism: str
    verified: bool
    verification_note: str = ""
    enabled: bool = True
    extra: dict = field(default_factory=dict)


class MarineDataProvider(abc.ABC):
    """Base class for every marine data source."""

    provider_id: str = "abstract"
    source: Source = Source.ORCA_INTERNAL
    origin: DataOrigin = DataOrigin.COMPUTED
    role: str = ""
    attribution: str = ""
    access_mechanism: str = ""
    verified_access: bool = False
    verification_note: str = ""

    def __init__(self, capability: ProviderCapability) -> None:
        self.capability = capability

    # ---- introspection ---------------------------------------------------
    def describe(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id=self.provider_id, source=self.source, origin=self.origin,
            role=self.role, capability=self.capability, attribution=self.attribution,
            access_mechanism=self.access_mechanism, verified=self.verified_access,
            verification_note=self.verification_note,
        )

    def supports(self, variables: Sequence[str]) -> list[str]:
        return [v for v in variables if v in self.capability.variables]

    # ---- the one method implementations must write ------------------------
    @abc.abstractmethod
    async def _fetch(self, query: ProviderQuery) -> ProviderResult:
        """Do the actual retrieval. May raise; :meth:`fetch` contains it."""

    # ---- the method agents call ------------------------------------------
    async def fetch(self, query: ProviderQuery) -> ProviderResult:
        started = time.perf_counter()
        try:
            result = await self._fetch(query)
        except Exception as exc:  # noqa: BLE001 - failures are data, not crashes
            log.warning("provider %s failed: %s", self.provider_id, exc)
            result = self.empty_result(
                status=SourceStatus.ERROR, error=f"{type(exc).__name__}: {exc}")
        result.latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        if result.retrieved_at is None:
            result.retrieved_at = utcnow()
        result.update_frequency_seconds = self.capability.update_frequency_seconds
        result.max_acceptable_age_seconds = self.capability.max_acceptable_age_seconds
        result.attribution = self.attribution
        return result

    def empty_result(self, status: SourceStatus, error: str | None = None,
                     dataset: str | None = None) -> ProviderResult:
        return ProviderResult(
            provider_id=self.provider_id, source=self.source, origin=self.origin,
            dataset=dataset or (self.capability.datasets[0]
                                if self.capability.datasets else "unknown"),
            status=status, error=error, retrieved_at=utcnow(),
            attribution=self.attribution,
        )


class NotConfiguredProvider(MarineDataProvider):
    """Stands in for a source this deployment cannot reach.

    It exists so the rest of the system keeps its shape: the planner can still
    route to it, the source panel still lists it, and the user is told plainly
    that the source was not consulted - instead of the source silently vanishing.
    """

    def __init__(self, template: MarineDataProvider, reason: str) -> None:
        super().__init__(template.capability)
        self.provider_id = template.provider_id
        self.source = template.source
        self.origin = template.origin
        self.role = template.role
        self.attribution = template.attribution
        self.access_mechanism = template.access_mechanism
        self.verified_access = template.verified_access
        self.verification_note = template.verification_note
        self.reason = reason

    async def _fetch(self, query: ProviderQuery) -> ProviderResult:
        return self.empty_result(SourceStatus.NOT_CONFIGURED, error=self.reason)
