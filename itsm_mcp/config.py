"""Runtime configuration (read when Settings() is created)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TOKENS = (
    "agent-token=incident-commander:itsm.read,itsm.write,cmdb.read,kb.read,oncall.read,oncall.page,monitoring.read;"
    "readonly-token=ops-dashboard:itsm.read,cmdb.read,kb.read,oncall.read,monitoring.read;"
    "admin-token=sre-admin:*"
)


def _tokens() -> dict[str, tuple[str, set[str]]]:
    """MCP_TOKENS="token=client:scope,scope;..." → {token: (client_id, scopes)}. Stands in for OAuth access tokens."""
    out = {}
    for part in os.getenv("MCP_TOKENS", DEFAULT_TOKENS).split(";"):
        if "=" in part and ":" in part:
            tok, rest = part.split("=", 1)
            client, scopes = rest.split(":", 1)
            out[tok.strip()] = (client.strip(), {s.strip() for s in scopes.split(",") if s.strip()})
    return out


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'itsm.db'}"))
    tokens: dict = field(default_factory=_tokens)
    fault_rate: dict = field(default_factory=lambda: {k: float(v) for k, v in
                                                      (p.split("=") for p in os.getenv("FAULT_INJECTION", "").split(",") if "=" in p)})
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "auto"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", ""))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", os.getenv("GROQ_API_KEY", "")))
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_S", "30")))


def get_settings() -> Settings:
    return Settings()
