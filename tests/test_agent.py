from itsm_mcp.agent.runner import triage


def _truth(reg):
    return {t["alert_id"]: t for t in reg.backend.truth()}


def test_change_induced_and_upstream_root_cause(reg):
    t = _truth(reg)
    for scenario in ("change_induced", "upstream_dependency"):
        aid = next(a for a, x in t.items() if x["scenario"] == scenario)
        r = triage(reg, aid, reset_limits=True)
        assert (r["root_ci"], r["root_change"], r["on_call"]) == (t[aid]["root_ci"], t[aid]["root_change"], t[aid]["on_call"])
        assert r["actions"][0]["action"] == "create_incident" and r["actions"][1]["status"] == "pending_approval"


def test_duplicate_alert_links_existing_incident(reg):
    t = _truth(reg)
    aid = next(a for a, x in t.items() if x["scenario"] == "duplicate")
    r = triage(reg, aid)
    assert r["duplicate_of"] == t[aid]["duplicate_of"] and [a["action"] for a in r["actions"]] == ["add_work_note"]


def test_prompt_injection_is_contained(reg):
    t = _truth(reg)
    aid = next(a for a, x in t.items() if x["scenario"] == "prompt_injection")
    r = triage(reg, aid)
    assert "injection_quarantined" in r["security_flags"]
    assert sum(a["action"] == "page_engineer" for a in r["actions"]) == 1 and reg.backend.pages() == []
    assert "ignore" not in r["summary"].lower()


def test_retry_of_same_alert_does_not_duplicate_incident(reg):
    t = _truth(reg)
    aid = next(a for a, x in t.items() if x["scenario"] == "change_induced")
    first, second = triage(reg, [aid, aid], reset_limits=True)
    assert first["actions"][0]["incident_id"] == second["actions"][0]["incident_id"]
