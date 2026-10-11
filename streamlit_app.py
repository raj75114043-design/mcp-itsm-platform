"""Operations console for the MCP ITSM platform (Streamlit)."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)

import streamlit as st  # noqa: E402

try:
    for key in ("GROQ_API_KEY", "LLM_PROVIDER", "LLM_MODEL"):
        if key in st.secrets:
            os.environ[key] = str(st.secrets[key])
except Exception:
    pass

import pandas as pd  # noqa: E402

from itsm_mcp.agent.runner import triage  # noqa: E402
from itsm_mcp.config import get_settings  # noqa: E402
from itsm_mcp.container import get_registry  # noqa: E402
from itsm_mcp.data.generator import generate  # noqa: E402
from itsm_mcp.llm import build_llm  # noqa: E402
from itsm_mcp.store import seed  # noqa: E402

logging.disable(logging.INFO)
st.set_page_config(page_title="MCP ITSM Platform", page_icon="🛠️", layout="wide")
reg = get_registry()
llm = build_llm(get_settings())
CLIENTS = {"incident-commander (agent-token)": "agent-token", "ops-dashboard (readonly-token)": "readonly-token", "sre-admin (admin-token)": "admin-token"}

with st.sidebar:
    st.markdown("### 🛠️ MCP ITSM Platform")
    st.caption("Policy-enforcing MCP gateway + incident-commander agent · Northwind Retail (fictional)")
    st.markdown(f"**Servers:** itsm · cmdb · knowledge · oncall · monitoring  \n**Tools:** {len(reg.specs)}  \n"
                f"**Summary writer:** `{llm.provider if llm.available else 'template (no LLM)'}`")
    pend = reg.backend.approvals("pending")
    st.markdown(f"**Pending approvals:** {len(pend)}")
    if st.button("Reset demo data", width="stretch", help="Re-seed the estate; clears incidents created in this session"):
        seed(reg.backend.engine, generate())
        reg.limiter.reset()
        st.session_state.pop("last", None)
        st.rerun()
    st.caption("The agent calls tools only through the MCP protocol. Paging always waits for a human decision.")

tabs = st.tabs(["🚨 Incident commander", "✅ Approvals", "🧰 Tool catalogue", "🧪 Playground", "📜 Audit log", "🛡️ Evaluation", "🏗️ Architecture"])

with tabs[0]:
    alerts = pd.DataFrame(reg.backend.alerts())
    truth = {t["alert_id"]: t["scenario"] for t in reg.backend.truth()}
    alerts["scenario (for demo)"] = alerts["alert_id"].map(truth)
    st.markdown("**Firing alerts**")
    st.dataframe(alerts[["alert_id", "fired_at", "ci_id", "severity", "message", "scenario (for demo)"]], hide_index=True, width="stretch", height=250)
    c1, c2 = st.columns([3, 1])
    aid = c1.selectbox("Alert to triage", alerts["alert_id"], format_func=lambda a: f"{a} · {truth[a]} · "
                       + alerts.set_index("alert_id").loc[a, "message"][:60])
    if c2.button("Run incident commander", type="primary", width="stretch"):
        reg.limiter.reset()
        with st.spinner("Agent calling MCP tools…"):
            st.session_state["last"] = triage(reg, aid, llm=llm)
    r = st.session_state.get("last")
    if r and "error" not in r:
        m = st.columns(5)
        m[0].metric("Root-cause CI", r["root_ci"])
        m[1].metric("Causal change", r["root_change"] or "—")
        m[2].metric("Priority", r["priority"])
        m[3].metric("On-call", r["on_call_name"] or "—")
        m[4].metric("MCP calls", len(r["trace"]))
        if r["duplicate_of"]:
            st.info(f"Duplicate of open incident {r['duplicate_of']} — a work note was added instead of a new incident.")
        if r["security_flags"]:
            st.error("Security: " + ", ".join(r["security_flags"]) + " — instruction-like text in a knowledge article was quarantined by the "
                     "gateway and was not acted on.")
        st.markdown("**Summary**")
        st.write(r["summary"])
        st.caption(f"summary: {r['summary_mode']} · {r['latency_ms']} ms")
        for a in r["actions"]:
            if a["action"] == "page_engineer":
                st.warning(f"Page to on-call engineer is **{a['status']}** (`{a['approval_id']}`) — decide in the Approvals tab.")
            else:
                st.success(f"{a['action']} → {a['incident_id']}")
        left, right = st.columns(2)
        with left:
            st.markdown("**Root-cause candidates** (changes in the 3 h before the alert)")
            st.dataframe(pd.DataFrame(r["candidates"]), hide_index=True, width="stretch")
        with right:
            st.markdown("**MCP call trace**")
            st.dataframe(pd.DataFrame(r["trace"])[["tool", "outcome", "ms", "flags"]], hide_index=True, width="stretch")
        with st.expander("Tool arguments"):
            st.json(r["trace"], expanded=False)

with tabs[1]:
    pend = reg.backend.approvals("pending")
    if not pend:
        st.info("No pending approvals. Run the incident commander on an alert first.")
    for a in pend:
        with st.container(border=True):
            st.markdown(f"**{a['tool']}** requested by `{a['client_id']}` · `{a['approval_id']}`  \n{a['reason']}")
            st.json(a["args"])
            x, y, _ = st.columns([1, 1, 5])
            if x.button("Approve", key="ok" + a["approval_id"], type="primary"):
                st.session_state["decision"] = reg.decide(a["approval_id"], True, "sre.lead")
                st.rerun()
            if y.button("Reject", key="no" + a["approval_id"]):
                st.session_state["decision"] = reg.decide(a["approval_id"], False, "sre.lead")
                st.rerun()
    if "decision" in st.session_state:
        st.json(st.session_state.pop("decision"))
    st.markdown("**Decision history**")
    st.dataframe(pd.DataFrame([a for a in reg.backend.approvals() if a["status"] != "pending"]), hide_index=True, width="stretch")
    st.markdown("**Pages actually sent**")
    st.dataframe(pd.DataFrame(reg.backend.pages()), hide_index=True, width="stretch")

with tabs[2]:
    cat = pd.DataFrame(reg.catalogue())
    st.dataframe(cat[["server", "name", "scope", "risk", "untrusted_output", "description"]], hide_index=True, width="stretch")
    pick = st.selectbox("Input schema", cat["name"])
    st.json(next(t["input_schema"] for t in reg.catalogue() if t["name"] == pick))

with tabs[3]:
    st.markdown("Call any tool through the gateway policy pipeline as a chosen client.")
    examples = {
        "Read-only client tries to create an incident": ("ops-dashboard (readonly-token)", "create_incident",
                                                         {"title": "Test from dashboard", "ci_id": "payments-db", "priority": "P3", "description": "should be refused"}),
        "Knowledge article with injected instructions": ("incident-commander (agent-token)", "get_article", {"article_id": "KB-0016"}),
        "On-call lookup (PII redacted)": ("incident-commander (agent-token)", "who_is_on_call", {"team": "Payments Squad", "at": "2026-10-11T13:00:00Z"}),
        "On-call lookup as admin (pii.read)": ("sre-admin (admin-token)", "who_is_on_call", {"team": "Payments Squad", "at": "2026-10-11T13:00:00Z"}),
        "Invalid arguments": ("incident-commander (agent-token)", "get_ci", {"ci_id": "DROP TABLE"}),
        "Blast radius of a database": ("incident-commander (agent-token)", "impacted_services", {"ci_id": "payments-db"}),
    }
    ex = st.selectbox("Example", list(examples))
    client, tool, args = examples[ex]
    c1, c2 = st.columns(2)
    client = c1.selectbox("Client", list(CLIENTS), index=list(CLIENTS).index(client))
    tool = c2.selectbox("Tool", list(reg.specs), index=list(reg.specs).index(tool))
    raw = st.text_area("Arguments (JSON)", json.dumps(args, indent=2), height=140)
    if st.button("Invoke", type="primary"):
        try:
            st.json(reg.invoke(CLIENTS[client], tool, json.loads(raw)))
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON: {exc}")

with tabs[4]:
    log = pd.DataFrame(reg.backend.audit_log(300))
    if not log.empty:
        f = st.multiselect("Outcome", sorted(log["outcome"].unique()))
        st.dataframe(log[log["outcome"].isin(f)] if f else log, hide_index=True, width="stretch")

with tabs[5]:
    st.markdown("Agent accuracy over regenerated estates (17 alert scenarios per seed), the gateway security suite and the tool-contract check.")
    n = st.slider("Seeds", 1, 5, 2)
    if st.button("Run evaluation", type="primary"):
        from itsm_mcp.eval.run import agent_accuracy, contract_check, gate, security_suite
        with st.spinner("Triaging alerts over MCP and running security tests…"):
            acc, sec, con = agent_accuracy(list(range(11, 11 + n))), security_suite(), contract_check()
        m = acc["metrics"]
        cols = st.columns(4)
        for col, k in zip(cols * 2, ["root_ci", "root_change", "duplicate_of", "kb_article", "on_call", "priority", "actions_correct", "team"], strict=False):
            col.metric(k.replace("_", " "), f"{m[k]:.0%}")
        st.metric("Injected instructions followed", m["injection_followed"])
        st.table(pd.DataFrame(m["by_scenario"].items(), columns=["scenario", "fully correct"]))
        st.dataframe(pd.DataFrame(sec), hide_index=True, width="stretch")
        breaches = gate(m, sec, con)
        (st.error if breaches else st.success)("Quality gate " + ("FAILED: " + "; ".join(breaches) if breaches else "PASSED"))

with tabs[6]:
    st.graphviz_chart("""
    digraph G { rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#f4f4f4", fontname=Helvetica];
      A [label="Incident commander\\n(MCP client)"]; D [label="Desktop MCP client\\n(stdio)"]; H [label="Other agents\\n(streamable HTTP + Bearer)"];
      subgraph cluster_g { label="MCP gateway"; style=dashed;
        P [label="Policy pipeline\\nauth · scopes · rate limit · validation\\nidempotency · approvals · circuit breaker\\nPII redaction · injection screening · audit"]; }
      I [label="ITSM"]; C [label="CMDB"]; K [label="Knowledge"]; O [label="On-call"]; M [label="Monitoring"]; U [label="Human approver"];
      A -> P; D -> P; H -> P; P -> I; P -> C; P -> K; P -> O; P -> M; U -> P [label="approve / reject"]; }""")
