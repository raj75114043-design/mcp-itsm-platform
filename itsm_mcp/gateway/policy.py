"""Gateway policies applied to every tool call, whatever the transport (stdio, streamable HTTP, in-process).

* Identity and scopes   — bearer token → client id + scopes; each tool declares the scope it needs.
* Rate limiting         — token bucket per (client, tool risk class).
* Circuit breaker       — per backend domain; opens after consecutive failures, half-opens after a cool-down.
* PII redaction         — e-mail addresses and phone numbers are masked unless the client holds `pii.read`.
* Injection screening   — tool *outputs* from human-authored sources are scanned for instructions aimed at AI agents;
                          matches are quarantined and the result is flagged so the agent treats it as data only.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    client_id: str
    scopes: frozenset[str]

    def has(self, scope: str) -> bool:
        return "*" in self.scopes or scope in self.scopes


class AuthError(Exception):
    pass


def authenticate(token: str | None, tokens: dict) -> Identity:
    if not token or token not in tokens:
        raise AuthError("invalid or missing token")
    client, scopes = tokens[token]
    return Identity(client, frozenset(scopes))


class RateLimiter:
    LIMITS = {"read": (60, 60.0), "write": (10, 60.0), "high": (3, 3600.0)}   # capacity, refill window (s)

    def __init__(self):
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, client: str, risk: str) -> tuple[bool, float]:
        cap, window = self.LIMITS[risk]
        rate = cap / window
        with self._lock:
            tokens, last = self._buckets.get((client, risk), (float(cap), time.monotonic()))
            now = time.monotonic()
            tokens = min(cap, tokens + (now - last) * rate)
            if tokens < 1:
                self._buckets[(client, risk)] = (tokens, now)
                return False, round((1 - tokens) / rate, 1)
            self._buckets[(client, risk)] = (tokens - 1, now)
            return True, 0.0

    def reset(self):
        self._buckets.clear()


class CircuitBreaker:
    def __init__(self, threshold: int = 3, cooldown_s: float = 30.0):
        self.threshold, self.cooldown = threshold, cooldown_s
        self.state: dict[str, dict] = {}

    def check(self, domain: str) -> bool:
        s = self.state.get(domain)
        if not s or s["failures"] < self.threshold:
            return True
        return time.monotonic() - s["opened_at"] >= self.cooldown   # half-open: allow a trial call

    def record(self, domain: str, ok: bool) -> None:
        s = self.state.setdefault(domain, {"failures": 0, "opened_at": 0.0})
        if ok:
            s["failures"] = 0
        else:
            s["failures"] += 1
            if s["failures"] >= self.threshold:
                s["opened_at"] = time.monotonic()

    def status(self) -> dict:
        return {d: ("open" if not self.check(d) else "closed") for d in self.state} or {}


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"\+?\d{2}[-\s]?\d{2}\d{6,8}\b|\+\d{1,3}-\d{2}\d{8}\b")


def redact(value):
    if isinstance(value, str):
        return PHONE.sub("[phone redacted]", EMAIL.sub("[email redacted]", value))
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    return value


INJECTION = [
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"(system|developer) (note|prompt|message) to (ai|llm|assistant)s?",
    r"\byou are now\b",
    r"\b(call|invoke|use) (the )?(tool )?(page_engineer|create_incident|add_work_note|close)",
    r"close all (open )?incidents",
    r"page (every|all) (team|engineer)s?",
    r"this is authori[sz]ed",
]
_INJ = re.compile("|".join(INJECTION), re.I)
_SENT = re.compile(r"[^.!?]*(?:[.!?]|$)")


def screen(value, found: list[str]):
    """Quarantine instruction-like sentences inside string fields; record what was found."""
    if isinstance(value, str):
        if not _INJ.search(value):
            return value
        kept = []
        for sent in _SENT.findall(value):
            if sent.strip() and _INJ.search(sent):
                found.append(sent.strip()[:160])
                kept.append(" [quarantined: instruction-like text from an untrusted source]")
            else:
                kept.append(sent)
        return "".join(kept).strip()
    if isinstance(value, list):
        return [screen(v, found) for v in value]
    if isinstance(value, dict):
        return {k: screen(v, found) for k, v in value.items()}
    return value
