"""Policy-enforcing tool registry shared by every MCP server and transport.

invoke() pipeline:  authenticate → scope → rate limit → validate → idempotency → (high risk: create approval and stop)
                    → circuit breaker → execute → redact PII → screen for injection → audit
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
import uuid

from pydantic import ValidationError

from itsm_mcp.gateway.policy import AuthError, CircuitBreaker, Identity, RateLimiter, authenticate, redact, screen
from itsm_mcp.gateway.tools import ToolError, ToolSpec, build_specs
from itsm_mcp.store import Backend

log = logging.getLogger("itsm_mcp.gateway")


class Registry:
    def __init__(self, backend: Backend, tokens: dict, fault_rate: dict | None = None, seed: int | None = None):
        self.backend, self.tokens = backend, tokens
        self.specs: dict[str, ToolSpec] = {s.name: s for s in build_specs(backend)}
        self.limiter, self.breaker = RateLimiter(), CircuitBreaker()
        self.fault_rate = fault_rate or {}
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------ catalogue
    def catalogue(self, domain: str | None = None) -> list[dict]:
        return [{"name": s.name, "server": s.domain, "scope": s.scope, "risk": s.risk, "description": s.description,
                 "untrusted_output": s.untrusted_output, "input_schema": s.args.model_json_schema(), "annotations": s.annotations}
                for s in self.specs.values() if domain in (None, s.domain)]

    # ------------------------------------------------------------------ invoke
    def invoke(self, token: str | None, tool: str, args: dict | None) -> dict:
        t0 = time.perf_counter()
        args = args or {}
        client, flags = "anonymous", []

        def done(outcome: str, payload: dict, detail: str | None = None) -> dict:
            ms = round((time.perf_counter() - t0) * 1000, 1)
            self.backend.write_audit({"client_id": client, "tool": tool, "args": redact(args), "outcome": outcome, "detail": detail,
                                      "ms": ms, "flags": ",".join(flags) or None})
            log.info("tool_call", extra={"client": client, "tool": tool, "outcome": outcome, "ms": ms, "flags": flags})
            return {"tool": tool, "outcome": outcome, "ms": ms, "flags": flags, **payload}

        try:
            ident: Identity = authenticate(token, self.tokens)
        except AuthError as exc:
            return done("unauthenticated", {"error": str(exc)})
        client = ident.client_id
        spec = self.specs.get(tool)
        if not spec:
            return done("unknown_tool", {"error": f"UNKNOWN_TOOL: {tool}"})
        if not ident.has(spec.scope):
            return done("forbidden", {"error": f"missing scope {spec.scope}"})
        ok, retry_after = self.limiter.allow(client, spec.risk)
        if not ok:
            return done("rate_limited", {"error": "rate limit exceeded", "retry_after_s": retry_after})
        try:
            parsed = spec.args(**args).model_dump()
        except ValidationError as exc:
            e = exc.errors()[0]
            return done("invalid_arguments", {"error": f"{'.'.join(map(str, e['loc']))}: {e['msg']}"})

        idem_key = None
        if spec.risk == "write":
            raw = parsed.get("idempotency_key") or json.dumps([client, tool, parsed], sort_keys=True)
            idem_key = hashlib.sha256(f"{client}|{tool}|{raw}".encode()).hexdigest()[:32]
            prior = self.backend.idem_get(idem_key)
            if prior is not None:
                flags.append("idempotent_replay")
                return done("ok", {"result": prior}, "idempotent replay")

        if spec.risk == "high":
            approval_id = "APR-" + uuid.uuid4().hex[:8].upper()
            self.backend.create_approval({"approval_id": approval_id, "client_id": client, "tool": tool, "args": parsed,
                                          "reason": f"{tool} is a high-impact action and requires human approval"})
            return done("pending_approval", {"result": {"status": "pending_approval", "approval_id": approval_id,
                                                        "message": "A human must approve this action before it is executed."}})
        return self._execute(spec, parsed, ident, done, flags, idem_key)

    def _execute(self, spec: ToolSpec, parsed: dict, ident: Identity, done, flags: list, idem_key: str | None) -> dict:
        if not self.breaker.check(spec.domain):
            return done("circuit_open", {"error": f"{spec.domain} backend unavailable (circuit open); retry later"})
        try:
            if self._rng.random() < self.fault_rate.get(spec.domain, 0.0):
                raise ConnectionError(f"{spec.domain} backend timeout (injected fault)")
            result = spec.handler(**{k: v for k, v in parsed.items() if k != "idempotency_key" or spec.name == "create_incident"})
            self.breaker.record(spec.domain, True)
        except ToolError as exc:
            self.breaker.record(spec.domain, True)        # a business error is not a backend failure
            return done("error", {"error": str(exc)})
        except Exception as exc:                          # noqa: BLE001 - backend/network failure
            self.breaker.record(spec.domain, False)
            return done("backend_error", {"error": str(exc)[:200]})
        if not ident.has("pii.read"):
            result = redact(result)
        detail = None
        if spec.untrusted_output:
            found: list[str] = []
            result = screen(result, found)
            if found:   # the agent only learns *that* text was quarantined; the text itself goes to the audit log for review
                flags.append("injection_quarantined")
                detail = "quarantined: " + " | ".join(found)
                result = {"_untrusted": True, "_quarantined_segments": len(found), **(result if isinstance(result, dict) else {"data": result})}
        if idem_key:
            self.backend.idem_put(idem_key, spec.name, result)
        return done("ok", {"result": result}, detail)

    # ------------------------------------------------------------------ human approval
    def decide(self, approval_id: str, approve: bool, user: str) -> dict:
        pending = next((a for a in self.backend.approvals("pending") if a["approval_id"] == approval_id), None)
        if not pending:
            return {"error": "approval not found or already decided"}
        if not approve:
            self.backend.decide_approval(approval_id, "rejected", user)
            self.backend.write_audit({"client_id": user, "tool": pending["tool"], "args": pending["args"], "outcome": "rejected",
                                      "detail": approval_id, "ms": 0.0, "flags": "human_decision"})
            return {"approval_id": approval_id, "status": "rejected"}
        spec = self.specs[pending["tool"]]
        ident = Identity(pending["client_id"], frozenset({"*"}))
        t0 = time.perf_counter()

        def done(outcome, payload, detail=None):
            self.backend.write_audit({"client_id": user, "tool": spec.name, "args": pending["args"], "outcome": f"approved_{outcome}",
                                      "detail": approval_id, "ms": round((time.perf_counter() - t0) * 1000, 1), "flags": "human_decision"})
            return payload

        out = self._execute(spec, pending["args"], ident, done, [], None)
        self.backend.decide_approval(approval_id, "approved", user, out.get("result") or out)
        return {"approval_id": approval_id, "status": "approved", **out}
