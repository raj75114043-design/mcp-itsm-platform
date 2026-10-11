"""LLM provider abstraction with free/open-source defaults and a deterministic fallback.

Providers (all speak the OpenAI-compatible chat API):
  groq               Free tier hosting open-weight models (Llama 3.x). Set GROQ_API_KEY.
  ollama             Local open-source models, e.g. `ollama pull llama3.1:8b`.
  openai_compatible  Any OpenAI-compatible endpoint (vLLM, LM Studio, Together, ...).
  none               No LLM: agents use deterministic planning and templated answers.

`auto` selects groq when a key is present, otherwise none. Every call is time-boxed and retried,
and any failure degrades to the deterministic path instead of failing the request.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field

from itsm_mcp.config import Settings

log = logging.getLogger("itsm_mcp.llm")

DEFAULTS = {
    "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),  # open-weight; Llama 3.3 70B retired Aug 2026
    "ollama": ("http://localhost:11434/v1", "llama3.1:8b"),
    "openai_compatible": ("", ""),
}


@dataclass
class LLMUsage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    failures: int = 0
    latency_ms: float = 0.0
    events: list[dict] = field(default_factory=list)


class LLMClient:
    provider = "none"
    model = "deterministic"

    @property
    def available(self) -> bool:
        return False

    def chat(self, system: str, user: str, *, json_mode: bool = False, usage: LLMUsage | None = None,
             max_tokens: int = 700) -> str | dict | None:
        return None


class OpenAICompatibleClient(LLMClient):
    def __init__(self, provider: str, base_url: str, model: str, api_key: str, timeout: float):
        from openai import OpenAI
        self.provider, self.model = provider, model
        self.client = OpenAI(base_url=base_url, api_key=api_key or "not-needed", timeout=timeout, max_retries=0)

    @property
    def available(self) -> bool:
        return True

    def chat(self, system, user, *, json_mode=False, usage=None, max_tokens=700):
        usage = usage or LLMUsage()
        kwargs: dict = {"response_format": {"type": "json_object"}} if json_mode else {}
        if "gpt-oss" in self.model:  # reasoning model: keep reasoning short and leave room for the answer
            kwargs["extra_body"] = {"reasoning_effort": "low"}
            max_tokens += 1024
        for attempt in range(3):
            t0 = time.perf_counter()
            try:
                resp = self.client.chat.completions.create(
                    model=self.model, temperature=0, max_tokens=max_tokens,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kwargs)
                ms = (time.perf_counter() - t0) * 1000
                usage.calls += 1
                usage.latency_ms += ms
                if resp.usage:
                    usage.prompt_tokens += resp.usage.prompt_tokens or 0
                    usage.completion_tokens += resp.usage.completion_tokens or 0
                text = resp.choices[0].message.content or ""
                usage.events.append({"model": self.model, "ms": round(ms), "ok": True})
                return _parse_json(text) if json_mode else text.strip()
            except Exception as exc:  # network, rate limit, malformed JSON
                usage.failures += 1
                usage.events.append({"model": self.model, "ok": False, "error": type(exc).__name__,
                                     "status": getattr(exc, "status_code", None)})
                if getattr(exc, "status_code", None) in (400, 401, 403, 404):
                    break  # configuration error: retrying will not help
                log.warning("llm_call_failed", extra={"attempt": attempt, "error": str(exc)[:200]})
                time.sleep(0.5 * (2 ** attempt))
        return None


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("no JSON object in response")
    return json.loads(m.group(0))


def build_llm(settings: Settings) -> LLMClient:
    provider = settings.llm_provider
    if provider == "auto":
        provider = "groq" if settings.llm_api_key else "none"
    if provider == "none":
        return LLMClient()
    base, model = DEFAULTS.get(provider, ("", ""))
    base = settings.llm_base_url or base
    model = settings.llm_model or model
    if not base or not model:
        log.warning("llm_misconfigured_falling_back", extra={"provider": provider})
        return LLMClient()
    return OpenAICompatibleClient(provider, base, model, settings.llm_api_key, settings.llm_timeout_s)
