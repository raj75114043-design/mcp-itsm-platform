"""Tool catalogue for the four domain servers. Handlers are plain functions over the Backend; the gateway
registry wraps them with policy. Each tool declares: domain (server), required scope and risk class."""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import snowballstemmer
from pydantic import BaseModel, Field

from itsm_mcp.store import Backend

CI = Field(pattern=r"^[a-z0-9-]{3,40}$", description="Configuration item id, e.g. payments-db")
TS = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", description="UTC timestamp, e.g. 2026-10-11T13:00:00Z")


class ToolError(Exception):
    pass


# ---------------------------------------------------------------------------------------------- argument models
class SearchIncidents(BaseModel):
    ci_id: str | None = CI
    state: Literal["open", "new", "in_progress", "resolved"] | None = None
    text: str | None = Field(default=None, max_length=100)
    since: str | None = TS
    limit: int = Field(default=10, ge=1, le=50)


class IncidentId(BaseModel):
    incident_id: str = Field(pattern=r"^INC-\d{5}$")


class CreateIncident(BaseModel):
    title: str = Field(min_length=5, max_length=160)
    ci_id: str = CI
    priority: Literal["P1", "P2", "P3", "P4"]
    description: str = Field(min_length=10, max_length=4000)
    related_change: str | None = Field(default=None, pattern=r"^CHG-\d{4}$")
    idempotency_key: str | None = Field(default=None, max_length=80, description="Repeat calls with the same key return the first result")


class WorkNote(BaseModel):
    incident_id: str = Field(pattern=r"^INC-\d{5}$")
    note: str = Field(min_length=3, max_length=4000)


class ListChanges(BaseModel):
    ci_ids: list[str] = Field(min_length=1, max_length=25)
    since: str | None = TS
    until: str | None = TS


class CiId(BaseModel):
    ci_id: str = CI


class Dependencies(BaseModel):
    ci_id: str = CI
    direction: Literal["downstream", "upstream"] = Field(default="downstream", description="downstream = what this CI depends on")
    depth: int = Field(default=2, ge=1, le=3)


class SearchKB(BaseModel):
    query: str = Field(min_length=3, max_length=300)
    ci_type: str | None = None
    service: str | None = None
    limit: int = Field(default=3, ge=1, le=10)


class ArticleId(BaseModel):
    article_id: str = Field(pattern=r"^KB-\d{4}$")


class OnCall(BaseModel):
    team: str = Field(min_length=3, max_length=60)
    at: str | None = TS


class Team(BaseModel):
    team: str = Field(min_length=3, max_length=60)


class Page(BaseModel):
    engineer_id: str = Field(pattern=r"^ENG-\d{3}$")
    incident_id: str | None = Field(default=None, pattern=r"^INC-\d{5}$")
    message: str = Field(min_length=5, max_length=500)


class AlertId(BaseModel):
    alert_id: str = Field(pattern=r"^ALR-\d{3}$")


class NoArgs(BaseModel):
    pass


@dataclass
class ToolSpec:
    name: str
    domain: str                  # itsm | cmdb | knowledge | oncall | monitoring
    scope: str
    risk: str                    # read | write | high (requires human approval)
    description: str
    args: type[BaseModel]
    handler: Callable[..., dict]
    untrusted_output: bool = False   # output contains human-authored free text → injection screening

    @property
    def annotations(self) -> dict:
        return {"readOnlyHint": self.risk == "read", "destructiveHint": self.risk == "high", "idempotentHint": self.risk == "read"}


_TOK = re.compile(r"[a-z0-9]+")
_STEM = snowballstemmer.stemmer("english")


def stems(text: str) -> list[str]:
    return _STEM.stemWords(_TOK.findall(text.lower()))


def _kb_score(query: str, art: dict, ci_type: str | None, service: str | None) -> float:
    q = Counter(stems(query))
    body = Counter(stems(f"{art['title']} {art['symptoms']} {art['symptoms']}"))
    overlap = sum(min(q[t], body[t]) / math.sqrt(1 + body[t]) for t in q)
    type_fit = 0.0 if not ci_type or not art["ci_type"] else (1.5 if art["ci_type"] == ci_type else -1.0)   # wrong technology → penalise
    return overlap + type_fit + (1.0 if service and art["service"] == service else 0)


def build_specs(b: Backend) -> list[ToolSpec]:
    def search_incidents(ci_id=None, state=None, text=None, since=None, limit=10):
        rows = b.search_incidents(ci_id, state, text, since, limit)
        return {"count": len(rows), "incidents": rows}

    def get_incident(incident_id):
        inc = b.get_incident(incident_id)
        if not inc:
            raise ToolError(f"NOT_FOUND: {incident_id}")
        return inc

    def create_incident(title, ci_id, priority, description, related_change=None, idempotency_key=None):
        ci = b.get_ci(ci_id)
        if not ci:
            raise ToolError(f"NOT_FOUND: {ci_id}")
        return b.create_incident({"title": title, "ci_id": ci_id, "service": ci["service"], "priority": priority, "description": description,
                                  "assignment_team": ci["owner_team"], "related_change": related_change})

    def add_work_note(incident_id, note):
        inc = b.add_work_note(incident_id, note, "mcp-gateway")
        if not inc:
            raise ToolError(f"NOT_FOUND: {incident_id}")
        return {"incident_id": incident_id, "work_notes": inc["work_notes"]}

    def list_changes(ci_ids, since=None, until=None):
        rows = b.list_changes(ci_ids, since, until)
        return {"count": len(rows), "changes": rows}

    def get_ci(ci_id):
        ci = b.get_ci(ci_id)
        if not ci:
            raise ToolError(f"NOT_FOUND: {ci_id}")
        svc = b.service(ci["service"])
        return {**ci, "service_tier": svc["tier"], "customer_facing": bool(svc["customer_facing"])}

    def get_dependencies(ci_id, direction="downstream", depth=2):
        if not b.get_ci(ci_id):
            raise ToolError(f"NOT_FOUND: {ci_id}")
        out, frontier, seen = [], [(ci_id, 0)], {ci_id}
        while frontier:
            cur, d = frontier.pop(0)
            if d == depth:
                continue
            for nxt in b.dependencies(cur, direction):
                if nxt not in seen:
                    seen.add(nxt)
                    ci = b.get_ci(nxt)
                    out.append({"ci_id": nxt, "via": cur, "hops": d + 1, "ci_type": ci["ci_type"], "service": ci["service"],
                                "owner_team": ci["owner_team"]})
                    frontier.append((nxt, d + 1))
        return {"ci_id": ci_id, "direction": direction, "items": out}

    def impacted_services(ci_id):
        deps = get_dependencies(ci_id, "upstream", 3)["items"]
        services = {b.get_ci(ci_id)["service"]} | {d["service"] for d in deps}
        rows = [b.service(s) for s in sorted(services)]
        return {"ci_id": ci_id, "services": rows, "highest_tier": min(r["tier"] for r in rows)}

    def search_kb(query, ci_type=None, service=None, limit=3):
        scored = sorted(((round(_kb_score(query, a, ci_type, service), 2), a) for a in b.kb_articles()), key=lambda x: -x[0])
        return {"results": [{"article_id": a["article_id"], "title": a["title"], "score": s, "symptoms": a["symptoms"]}
                            for s, a in scored[:limit] if s > 0]}

    def get_article(article_id):
        a = b.get_article(article_id)
        if not a:
            raise ToolError(f"NOT_FOUND: {article_id}")
        return a

    def who_is_on_call(team, at=None):
        at = at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = b.on_call(team, at)
        if not r:
            raise ToolError(f"NO_SCHEDULE: {team} at {at}")
        p, s = b.engineer(r["primary"]), b.engineer(r["secondary"])
        return {"team": team, "at": at, "shift": {"start": r["start"], "end": r["end"]},
                "primary": {k: p[k] for k in ("engineer_id", "name", "email", "phone")},
                "secondary": {k: s[k] for k in ("engineer_id", "name", "email", "phone")}}

    def get_escalation_policy(team):
        t = b.team(team)
        if not t:
            raise ToolError(f"NOT_FOUND: {team}")
        return {"team": team, "policy": t["escalation_minutes"], "manager": b.engineer(t["manager"])["name"]}

    def page_engineer(engineer_id, message, incident_id=None):
        eng = b.engineer(engineer_id)
        if not eng:
            raise ToolError(f"NOT_FOUND: {engineer_id}")
        page_id = f"PG-{len(b.pages()) + 1:05d}"
        from itsm_mcp.store import now
        b.record_page({"page_id": page_id, "ts": now(), "engineer_id": engineer_id, "incident_id": incident_id, "message": message})
        return {"page_id": page_id, "engineer": eng["name"], "status": "sent"}

    def list_active_alerts():
        return {"alerts": b.alerts()}

    def get_alert(alert_id):
        a = next((x for x in b.alerts() if x["alert_id"] == alert_id), None)
        if not a:
            raise ToolError(f"NOT_FOUND: {alert_id}")
        return a

    S = ToolSpec
    return [
        S("search_incidents", "itsm", "itsm.read", "read", "Search incidents by CI, state, text or opened-since time.", SearchIncidents, search_incidents,
          untrusted_output=True),
        S("get_incident", "itsm", "itsm.read", "read", "Get one incident with work notes.", IncidentId, get_incident, untrusted_output=True),
        S("create_incident", "itsm", "itsm.write", "write", "Create an incident. Use idempotency_key to make retries safe.", CreateIncident, create_incident),
        S("add_work_note", "itsm", "itsm.write", "write", "Append a work note to an incident.", WorkNote, add_work_note),
        S("list_changes", "itsm", "itsm.read", "read", "Change records for CIs overlapping a time window.", ListChanges, list_changes),
        S("get_ci", "cmdb", "cmdb.read", "read", "Configuration item with service, tier and owning team.", CiId, get_ci),
        S("get_dependencies", "cmdb", "cmdb.read", "read", "Dependency tree of a CI (downstream = what it depends on).", Dependencies, get_dependencies),
        S("impacted_services", "cmdb", "cmdb.read", "read", "Business services impacted if a CI fails, with tiers.", CiId, impacted_services),
        S("search_kb", "knowledge", "kb.read", "read", "Search knowledge articles by symptoms.", SearchKB, search_kb, untrusted_output=True),
        S("get_article", "knowledge", "kb.read", "read", "Full knowledge article with resolution steps.", ArticleId, get_article, untrusted_output=True),
        S("who_is_on_call", "oncall", "oncall.read", "read", "Primary and secondary on-call engineers for a team at a time.", OnCall, who_is_on_call),
        S("get_escalation_policy", "oncall", "oncall.read", "read", "Escalation policy and manager for a team.", Team, get_escalation_policy),
        S("page_engineer", "oncall", "oncall.page", "high", "Page an engineer. Requires human approval before it is sent.", Page, page_engineer),
        S("list_active_alerts", "monitoring", "monitoring.read", "read", "Currently firing monitoring alerts.", NoArgs, list_active_alerts),
        S("get_alert", "monitoring", "monitoring.read", "read", "One monitoring alert.", AlertId, get_alert),
    ]
