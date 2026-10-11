# Threat model (STRIDE-style summary)

| Threat | Example | Mitigation | Test |
|---|---|---|---|
| Spoofing | Call tools without a token / with a guessed token | Token registry; unknown → `unauthenticated` | `missing token is rejected`, HTTP test |
| Tampering | Malformed or hostile arguments (`DROP TABLE`) | Pydantic schemas with patterns and bounds before execution | `invalid arguments rejected` |
| Repudiation | "The agent didn't page anyone" | Audit log of every call and every approval decision | `every call is audited` |
| Information disclosure | Engineer phone numbers in results | PII redaction unless `pii.read` | `PII redacted for agent` |
| Denial of service | Agent loop floods ITSM | Rate limits per risk class; circuit breaker per backend | `write rate limit`, `circuit breaker` |
| Elevation of privilege | Read-only client creates incidents or pages | Scopes per tool | `read-only client cannot write/page` |
| Prompt injection | KB article instructs the agent to page every team | Output screening + quarantine, approval-gated paging, tool-less LLM | `injection quarantined`, agent eval `injection_followed = 0` |
| Excessive agency | Agent sends pages autonomously | `high` risk → approval request | `page requires approval`, `unapproved_pages_sent = 0` |

Residual risks: pattern-based injection detection; static tokens instead of OAuth; single-tenant policy configuration.
