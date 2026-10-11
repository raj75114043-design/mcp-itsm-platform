"""Backend systems of record (ITSM, CMDB, knowledge, on-call) plus gateway state (approvals, audit, idempotency).

PostgreSQL in production, SQLite in lite mode. In a real deployment each domain would be a separate product
(ServiceNow, a CMDB, Confluence, PagerDuty); the MCP servers would call their APIs instead of these tables.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, Text, create_engine, insert, inspect, or_, select, update
from sqlalchemy.engine import Engine

from itsm_mcp.data.generator import Estate

md = MetaData()
T = {
    "services": Table("services", md, Column("service", String, primary_key=True), Column("tier", Integer), Column("owner_team", String),
                      Column("customer_facing", Integer)),
    "cis": Table("cis", md, Column("ci_id", String, primary_key=True), Column("ci_type", String), Column("service", String),
                 Column("owner_team", String), Column("environment", String), Column("status", String)),
    "dependencies": Table("dependencies", md, Column("id", Integer, primary_key=True, autoincrement=True), Column("ci_id", String, index=True),
                          Column("depends_on", String, index=True)),
    "teams": Table("teams", md, Column("team", String, primary_key=True), Column("manager", String), Column("escalation_minutes", String)),
    "engineers": Table("engineers", md, Column("engineer_id", String, primary_key=True), Column("name", String), Column("team", String),
                       Column("email", String), Column("phone", String), Column("role", String)),
    "rotations": Table("rotations", md, Column("id", Integer, primary_key=True, autoincrement=True), Column("team", String, index=True),
                       Column("start", String), Column("end", String), Column("primary", String), Column("secondary", String)),
    "changes": Table("changes", md, Column("change_id", String, primary_key=True), Column("ci_id", String, index=True), Column("change_type", String),
                     Column("description", Text), Column("risk", String), Column("status", String), Column("start", String), Column("end", String),
                     Column("implementer", String)),
    "incidents": Table("incidents", md, Column("incident_id", String, primary_key=True), Column("title", String), Column("ci_id", String, index=True),
                       Column("service", String), Column("priority", String), Column("state", String, index=True), Column("opened_at", String),
                       Column("resolved_at", String), Column("caller_name", String), Column("caller_email", String), Column("caller_phone", String),
                       Column("description", Text), Column("assignment_team", String), Column("related_change", String), Column("work_notes", Text)),
    "kb": Table("kb", md, Column("article_id", String, primary_key=True), Column("title", String), Column("ci_type", String), Column("service", String),
                Column("symptoms", Text), Column("resolution", Text), Column("updated", String)),
    "alerts": Table("alerts", md, Column("alert_id", String, primary_key=True), Column("ci_id", String), Column("fired_at", String),
                    Column("source", String), Column("metric", String), Column("message", Text), Column("severity", String)),
    "truth": Table("truth", md, Column("alert_id", String, primary_key=True), Column("scenario", String), Column("root_ci", String),
                   Column("root_change", String), Column("duplicate_of", String), Column("kb_article", String), Column("team", String),
                   Column("on_call", String), Column("priority", String)),
}
approvals = Table("approvals", md, Column("approval_id", String, primary_key=True), Column("created_at", String), Column("client_id", String),
                  Column("tool", String), Column("args", Text), Column("reason", Text), Column("status", String, index=True),
                  Column("decided_by", String), Column("decided_at", String), Column("result", Text))
audit = Table("audit_log", md, Column("id", Integer, primary_key=True, autoincrement=True), Column("ts", String), Column("client_id", String),
              Column("tool", String), Column("args", Text), Column("outcome", String, index=True), Column("detail", Text), Column("ms", Float),
              Column("flags", String))
idem = Table("idempotency", md, Column("key", String, primary_key=True), Column("tool", String), Column("result", Text), Column("ts", String))
pages = Table("pages", md, Column("page_id", String, primary_key=True), Column("ts", String), Column("engineer_id", String),
              Column("incident_id", String), Column("message", Text))


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_engine(url: str) -> Engine:
    kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    return create_engine(url, future=True, **kw)


def seed(engine: Engine, estate: Estate) -> None:
    md.drop_all(engine)
    md.create_all(engine)
    with engine.begin() as c:
        for name, table in T.items():
            rows = getattr(estate, name)
            if rows:
                c.execute(insert(table), rows)


def is_seeded(engine: Engine) -> bool:
    return "incidents" in inspect(engine).get_table_names()


class Backend:
    def __init__(self, engine: Engine):
        self.engine = engine

    def q(self, stmt) -> list[dict]:
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(stmt)]

    def exec(self, stmt) -> int:
        with self.engine.begin() as c:
            return c.execute(stmt).rowcount

    # ------------------------------------------------------------------ ITSM
    def search_incidents(self, ci_id=None, state=None, text=None, since=None, limit=20):
        t = T["incidents"]
        s = select(t)
        if ci_id:
            s = s.where(t.c.ci_id == ci_id)
        if state == "open":
            s = s.where(t.c.state.in_(["new", "in_progress", "on_hold"]))
        elif state:
            s = s.where(t.c.state == state)
        if text:
            s = s.where(or_(t.c.title.ilike(f"%{text}%"), t.c.description.ilike(f"%{text}%")))
        if since:
            s = s.where(t.c.opened_at >= since)
        return self.q(s.order_by(t.c.opened_at.desc()).limit(limit))

    def get_incident(self, incident_id):
        r = self.q(select(T["incidents"]).where(T["incidents"].c.incident_id == incident_id))
        return r[0] if r else None

    def create_incident(self, row: dict) -> dict:
        t = T["incidents"]
        n = len(self.q(select(t.c.incident_id))) + 1
        row = {"incident_id": f"INC-{n:05d}", "state": "new", "opened_at": now(), "resolved_at": None, "caller_name": "MCP agent",
               "caller_email": None, "caller_phone": None, "work_notes": "", **row}
        with self.engine.begin() as c:
            c.execute(insert(t), [row])
        return row

    def add_work_note(self, incident_id, note, author):
        inc = self.get_incident(incident_id)
        if not inc:
            return None
        notes = (inc["work_notes"] or "") + f"\n[{now()} {author}] {note}"
        self.exec(update(T["incidents"]).where(T["incidents"].c.incident_id == incident_id).values(work_notes=notes.strip()))
        return self.get_incident(incident_id)

    def list_changes(self, ci_ids=None, start=None, end=None, limit=50):
        t = T["changes"]
        s = select(t)
        if ci_ids:
            s = s.where(t.c.ci_id.in_(ci_ids))
        if start:
            s = s.where(t.c.end >= start)
        if end:
            s = s.where(t.c.start <= end)
        return self.q(s.order_by(t.c.start.desc()).limit(limit))

    # ------------------------------------------------------------------ CMDB
    def get_ci(self, ci_id):
        r = self.q(select(T["cis"]).where(T["cis"].c.ci_id == ci_id))
        return r[0] if r else None

    def dependencies(self, ci_id, direction="downstream"):
        d = T["dependencies"]
        if direction == "downstream":   # what this CI depends on
            return [r["depends_on"] for r in self.q(select(d.c.depends_on).where(d.c.ci_id == ci_id))]
        return [r["ci_id"] for r in self.q(select(d.c.ci_id).where(d.c.depends_on == ci_id))]

    def service(self, name):
        r = self.q(select(T["services"]).where(T["services"].c.service == name))
        return r[0] if r else None

    # ------------------------------------------------------------------ knowledge
    def kb_articles(self):
        return self.q(select(T["kb"]))

    def get_article(self, article_id):
        r = self.q(select(T["kb"]).where(T["kb"].c.article_id == article_id))
        return r[0] if r else None

    # ------------------------------------------------------------------ on-call
    def on_call(self, team, at):
        r = self.q(select(T["rotations"]).where(T["rotations"].c.team == team).where(T["rotations"].c.start <= at).where(T["rotations"].c.end > at))
        return r[0] if r else None

    def engineer(self, eid):
        r = self.q(select(T["engineers"]).where(T["engineers"].c.engineer_id == eid))
        return r[0] if r else None

    def team(self, name):
        r = self.q(select(T["teams"]).where(T["teams"].c.team == name))
        return r[0] if r else None

    def record_page(self, row):
        with self.engine.begin() as c:
            c.execute(insert(pages), [row])

    def pages(self):
        return self.q(select(pages).order_by(pages.c.ts.desc()))

    # ------------------------------------------------------------------ alerts (monitoring feed) and evaluation truth
    def alerts(self):
        return self.q(select(T["alerts"]).order_by(T["alerts"].c.alert_id))

    def truth(self):
        return self.q(select(T["truth"]))

    # ------------------------------------------------------------------ gateway state
    def write_audit(self, row):
        with self.engine.begin() as c:
            c.execute(insert(audit), [{**row, "ts": now(), "args": json.dumps(row.get("args"), default=str)}])

    def audit_log(self, limit=200, client_id=None):
        s = select(audit).order_by(audit.c.id.desc()).limit(limit)
        if client_id:
            s = s.where(audit.c.client_id == client_id)
        return self.q(s)

    def create_approval(self, row):
        with self.engine.begin() as c:
            c.execute(insert(approvals), [{**row, "created_at": now(), "status": "pending", "args": json.dumps(row["args"])}])

    def approvals(self, status=None):
        s = select(approvals).order_by(approvals.c.created_at.desc())
        if status:
            s = s.where(approvals.c.status == status)
        return [{**r, "args": json.loads(r["args"])} for r in self.q(s)]

    def decide_approval(self, approval_id, status, user, result=None) -> bool:
        return self.exec(update(approvals).where(approvals.c.approval_id == approval_id).where(approvals.c.status == "pending")
                         .values(status=status, decided_by=user, decided_at=now(), result=json.dumps(result, default=str) if result else None)) == 1

    def idem_get(self, key):
        r = self.q(select(idem).where(idem.c.key == key))
        return json.loads(r[0]["result"]) if r else None

    def idem_put(self, key, tool, result):
        with self.engine.begin() as c:
            c.execute(insert(idem), [{"key": key, "tool": tool, "result": json.dumps(result, default=str), "ts": now()}])
