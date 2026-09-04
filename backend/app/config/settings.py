"""ORCA runtime configuration.

Everything that varies between a laptop, a demo laptop on stage, and a real
deployment lives here and is read from the environment.  No secrets are ever
hard-coded; see ``.env.example`` for the full list.

Startup validation lives in :func:`validate_settings` and is called by the
application factory, so a misconfigured deployment fails loudly at boot rather
than silently producing wrong marine advice.
"""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DataMode(str, Enum):
    """Where the marine numbers in a response came from."""

    DEMO = "DEMO"      # deterministic local fixtures, never presented as live
    LIVE = "LIVE"      # real external source responded
    MIXED = "MIXED"    # some providers live, some demo


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="ORCA_",
    )

    # ----- identity -------------------------------------------------------
    app_name: str = "ORCA"
    app_long_name: str = "Marine EcOsystem Reasoning with Collaborative Agents"
    version: str = "0.1.0"
    environment: Literal["dev", "demo", "staging", "prod"] = "dev"

    # ----- data sourcing --------------------------------------------------
    demo_mode: bool = Field(
        default=True,
        description=(
            "When true every provider resolves to its Demo implementation. "
            "Responses are still fully labelled DEMO end to end."
        ),
    )
    allow_live_fallback_to_demo: bool = Field(
        default=False,
        description=(
            "If a live provider fails, may ORCA silently substitute demo data? "
            "Default NO. Demo data must never masquerade as a live reading."
        ),
    )

    # ----- external sources (all optional; absence => NOT_CONFIGURED) -----
    imd_api_base: str = "https://api.imd.gov.in/api/v1"
    imd_enabled: bool = False          # requires IP whitelisting from IMD
    incois_erddap_base: str = "https://erddap.incois.gov.in/erddap"
    incois_enabled: bool = False
    mosdac_api_base: str = "https://www.mosdac.gov.in"
    mosdac_username: str | None = None
    mosdac_password: str | None = None
    mosdac_enabled: bool = False
    # --- INCOIS OceanSat-2 OCM ocean-colour map layer ---------------------
    # Verified dataset contract; see providers/incois/oceansat.py.
    oceansat_dataset_id: str = "incois_oceansat2_datasets"
    oceansat_axis_order: str = "time,latitude,longitude"
    oceansat_default_variable: str = "CHL"
    oceansat_half_degrees: float = 0.75    # bbox half-width; keeps the fetch small
    oceansat_max_cells: int = 4000         # hard ceiling on what reaches the browser
    oceansat_cache_ttl_seconds: int = 1800

    openmeteo_forecast_base: str = "https://api.open-meteo.com/v1/forecast"
    openmeteo_marine_base: str = "https://marine-api.open-meteo.com/v1/marine"
    openmeteo_enabled: bool = True     # key-free, documented, non-commercial use

    # --- OpenWeatherMap (free key, no card, 60/min and 1M/month) -----------
    # The most generous free atmospheric source we could verify, and therefore
    # the practical stand-in for IMD until an IP whitelist is granted.
    openweathermap_base: str = "https://api.openweathermap.org/data/2.5"
    openweathermap_api_key: str | None = None
    openweathermap_enabled: bool = False

    # ----- LLM (entirely optional) ---------------------------------------
    llm_provider: Literal["none", "openai_compatible", "anthropic"] = "none"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_ms: int = 2500
    llm_enable_for_nlu_fallback: bool = True
    llm_enable_for_explanation: bool = False

    # ----- latency budgets (milliseconds) ---------------------------------
    budget_total_ms: int = 3000
    budget_provider_ms: int = 1800
    budget_agent_ms: int = 2200
    provider_connect_timeout_ms: int = 700
    provider_retry_attempts: int = 1
    provider_retry_backoff_ms: int = 120

    # ----- circuit breaker -------------------------------------------------
    breaker_failure_threshold: int = 4
    breaker_reset_seconds: int = 30

    # ----- cache -----------------------------------------------------------
    cache_backend: Literal["memory", "redis"] = "memory"
    redis_url: str | None = None
    cache_max_entries: int = 4096

    # ----- behaviour -------------------------------------------------------
    default_language: str = "en"
    max_conversation_turns: int = 20
    conversation_ttl_seconds: int = 3600
    expose_trace_in_response: bool = True   # dev/demo transparency panel

    # ----- server ----------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "*"

    @field_validator("cors_origins")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins in ("*", ""):
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def data_dir(self) -> str:
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class ConfigurationError(RuntimeError):
    """Raised at startup when the configuration cannot produce a safe system."""


def validate_settings(s: Settings) -> list[str]:
    """Fail fast on impossible configurations; return non-fatal warnings."""
    warnings: list[str] = []

    if not s.demo_mode:
        enabled = [
            name
            for name, on in (
                ("IMD", s.imd_enabled),
                ("INCOIS", s.incois_enabled),
                ("MOSDAC", s.mosdac_enabled),
                ("OPEN_METEO", s.openmeteo_enabled),
                ("OPEN_WEATHER_MAP", s.openweathermap_enabled),
            )
            if on
        ]
        if not enabled:
            raise ConfigurationError(
                "ORCA_DEMO_MODE=false but no live provider is enabled. "
                "Enable at least one of ORCA_IMD_ENABLED / ORCA_INCOIS_ENABLED / "
                "ORCA_MOSDAC_ENABLED / ORCA_OPENMETEO_ENABLED, or run in demo mode."
            )
        if s.mosdac_enabled and not (s.mosdac_username and s.mosdac_password):
            raise ConfigurationError(
                "ORCA_MOSDAC_ENABLED=true requires ORCA_MOSDAC_USERNAME and "
                "ORCA_MOSDAC_PASSWORD (MOSDAC account credentials)."
            )
        if s.openweathermap_enabled and not s.openweathermap_api_key:
            raise ConfigurationError(
                "ORCA_OPENWEATHERMAP_ENABLED=true requires ORCA_OPENWEATHERMAP_API_KEY. "
                "Get a free key (no card) at https://home.openweathermap.org/users/sign_up")
        if s.imd_enabled:
            warnings.append(
                "IMD API access requires IP whitelisting by IMD. If this host is "
                "not whitelisted the IMD provider will report UNAVAILABLE."
            )

    if s.llm_provider != "none" and not s.llm_api_key:
        raise ConfigurationError(
            f"ORCA_LLM_PROVIDER={s.llm_provider} requires ORCA_LLM_API_KEY."
        )

    if s.cache_backend == "redis" and not s.redis_url:
        raise ConfigurationError("ORCA_CACHE_BACKEND=redis requires ORCA_REDIS_URL.")

    if s.allow_live_fallback_to_demo:
        warnings.append(
            "ORCA_ALLOW_LIVE_FALLBACK_TO_DEMO=true — demo fixtures may stand in for "
            "failed live sources. Responses remain labelled, but do not use this in "
            "any setting where a user could act on the advice."
        )
    return warnings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Used by tests that manipulate the environment."""
    get_settings.cache_clear()
