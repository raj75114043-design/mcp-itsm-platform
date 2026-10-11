# ADR-0004: Tool schemas are a versioned contract

**Status:** Accepted · 2026-10-11

## Context
MCP clients (other teams' agents, desktop users) build prompts and code around tool names and arguments.

## Decision
`contracts/tools.json` records each tool's name, server, scope, risk class and JSON input schema. CI compares the
running catalogue with it and fails on removed tools, new required arguments, scope/risk changes or any unreviewed
change. Intentional changes are accepted with `make contract`, which shows up in the pull request diff.

## Consequences
+ Breaking changes are visible in review instead of in a client's incident.
− Every schema change needs an explicit contract update.
