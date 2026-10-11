# Operations runbook

| Symptom | Check | Action |
|---|---|---|
| Clients get `unauthenticated` | Token in `MCP_TOKENS`? Bearer header sent? | Fix token mapping; restart gateway |
| `circuit_open` for a domain | `/health` → circuits; backend status | Fix backend; breaker half-opens after 30 s |
| Spike in `rate_limited` | Audit log by client | Agent loop? Revoke token or lower its scopes |
| `injection_quarantined` flags | Audit log `detail` column | Review and clean the source article/incident |
| Pending approvals piling up | `/approvals?status=pending` | Assign an approver rota; consider scoped auto-approval for P1 only |
| CI fails on contract | `reports/eval.json` → contract | Restore compatibility or run `make contract` and review the diff |
