# ADR-0002: High-impact actions become approval requests

**Status:** Accepted · 2026-10-11

## Context
An agent that can page engineers can wake a whole organisation at 3 a.m. through a bug, a loop or an injected instruction.

## Decision
Tools have a risk class: `read`, `write` (reversible, idempotent, rate-limited) and `high`. A `high` call does not
execute; it stores the validated arguments as an approval request and returns `pending_approval` with an ID. A human
approves (the stored call executes exactly once) or rejects (nothing is sent). Approvals are audited with the decider.

## Consequences
+ The worst an agent can do unaided is create or annotate incidents, which are idempotent and reversible.
+ Approvers see exactly the arguments that will run, not a re-generated request.
− Adds latency to paging; teams that want auto-paging for P1s would grant a narrower, separately audited scope.
