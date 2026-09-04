"""Test fixtures.

Note on async: the suite uses plain ``async def`` tests. If ``pytest-asyncio``
is installed it takes over; if it is not, the hook below runs the coroutine
itself. That keeps the suite runnable in a bare environment - which is exactly
the situation a teammate cloning the repo on a hackathon laptop is in.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import Settings, get_settings, reset_settings_cache  # noqa: E402
from app.core import clock  # noqa: E402
from app.providers.demo_controls import DemoControls, reset_demo_controls, set_demo_controls  # noqa: E402


def pytest_pyfunc_call(pyfuncitem):
    """Run coroutine tests when pytest-asyncio is not installed."""
    test = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test):
        return None
    if any("asyncio" in str(m.name) for m in pyfuncitem.iter_markers()):
        return None
    if "pytest_asyncio" in sys.modules:
        return None
    kwargs = {k: pyfuncitem.funcargs[k] for k in pyfuncitem._fixtureinfo.argnames}
    asyncio.run(test(**kwargs))
    return True


# A fixed instant so demo fixtures, freshness and time parsing are reproducible.
# 2 September 2026, 11:00 IST (05:30 UTC) - mid-morning, southwest monsoon.
FROZEN = dt.datetime(2026, 9, 2, 5, 30, tzinfo=dt.timezone.utc)


@pytest.fixture(autouse=True)
def frozen_clock():
    clock.freeze(FROZEN)
    yield FROZEN
    clock.unfreeze()


@pytest.fixture(autouse=True)
def clean_demo_controls():
    reset_demo_controls()
    set_demo_controls(DemoControls())
    yield
    reset_demo_controls()


@pytest.fixture
def settings() -> Settings:
    reset_settings_cache()
    return get_settings()


@pytest.fixture
def container(settings):
    from app.services.container import Container, warmup
    warmup()
    return Container.build(settings)


@pytest.fixture
def query_service(container):
    from app.services.query_service import QueryService
    return QueryService(container)


@pytest.fixture
def api_client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        yield client


@pytest.fixture
def kochi_point():
    from app.geo.gazetteer import get_gazetteer
    return get_gazetteer().find("Kochi").offshore_point(6.0)


def set_env(monkeypatch, **kwargs):
    for k, v in kwargs.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, str(v))
    reset_settings_cache()
    reset_demo_controls()
