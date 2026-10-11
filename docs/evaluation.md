# Evaluation notes

## Failure modes found during development (and fixed)
| Symptom | Cause | Fix |
|---|---|---|
| Upstream root cause missed for 2 of 4 alerts | Agent ignored changes still **in progress** when the alert fired | Candidate if `start ≤ alert time`; recency measured from change start |
| Duplicate alert attributed to an unrelated change | Root-cause search ran before duplicate detection | Check open incidents on the alerting CI first |
| Wrong KB article (service match, no symptom match) | KB ranking rewarded the service alone | Require a shared symptom term; penalise articles for a different technology |
| "restarting" ≠ "restarts" | No stemming in KB search | Snowball stemming |
| Injected text visible to the client | Quarantine list echoed in a flag field | Return only a count; original text to the audit log |
| Agent crashed under rate limiting | Tool errors returned `None` and were dereferenced | Graceful degradation; evaluation resets limits between alerts that would be minutes apart |

## What the numbers do not show
The five scenario types are fixed. Seeds vary timing, rotations and noise, so the evaluation checks robustness to
those, not to new kinds of incidents. Real estates have missing CMDB relationships, unlinked changes and noisy
alert text; expect lower accuracy and use the console's trace to see why a candidate won.
