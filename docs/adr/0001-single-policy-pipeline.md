# ADR-0001: One policy pipeline for every transport

**Status:** Accepted · 2026-10-11

## Context
The same tools are served over stdio (desktop clients), streamable HTTP (remote agents) and in-process (the
incident commander, tests). Implementing checks inside each server or each tool leads to drift: one path forgets
redaction, another forgets audit.

## Decision
Tool handlers are plain functions with no policy. `Registry.invoke()` is the only way to run them and applies, in order:
authenticate → scope → rate limit → validate → idempotency → approval (high risk) → circuit breaker → execute →
PII redaction → injection screening → audit. FastMCP servers are generated from the registry; each generated tool
calls `invoke()` with the caller's token.

## Consequences
+ A policy is written and tested once; the security suite exercises the registry directly and through MCP.
+ Adding a tool means declaring its scope and risk class; it inherits every control.
− The registry is a choke point; at scale it would be a separate service with its own SLOs.
