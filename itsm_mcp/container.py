"""Wiring: database, seed data and the policy-enforcing registry (one per process)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from itsm_mcp.config import Settings, get_settings
from itsm_mcp.data.generator import generate
from itsm_mcp.gateway.registry import Registry
from itsm_mcp.store import Backend, is_seeded, make_engine, seed


def build(settings: Settings | None = None, reseed: bool = False) -> Registry:
    settings = settings or get_settings()
    if settings.database_url.startswith("sqlite:///"):
        Path(settings.database_url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.database_url)
    if reseed or not is_seeded(engine):
        seed(engine, generate())
    return Registry(Backend(engine), settings.tokens, settings.fault_rate)


@lru_cache(maxsize=4)
def _cached(sig: tuple) -> Registry:
    return build()


def get_registry() -> Registry:
    return _cached(tuple(os.getenv(k, "") for k in ("DATABASE_URL", "MCP_TOKENS", "FAULT_INJECTION")))
