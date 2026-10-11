def test_scopes_and_validation(reg):
    assert reg.invoke("bad", "get_ci", {"ci_id": "payments-db"})["outcome"] == "unauthenticated"
    assert reg.invoke("readonly-token", "add_work_note", {"incident_id": "INC-00001", "note": "hi there"})["outcome"] == "forbidden"
    assert reg.invoke("agent-token", "get_ci", {"ci_id": "Not Valid"})["outcome"] == "invalid_arguments"
    assert reg.invoke("agent-token", "nope", {})["outcome"] == "unknown_tool"


def test_idempotent_create_and_audit(reg):
    args = {"title": "Pool exhaustion", "ci_id": "payments-db", "priority": "P1", "description": "test incident body", "idempotency_key": "abc"}
    a = reg.invoke("agent-token", "create_incident", args)
    b = reg.invoke("agent-token", "create_incident", args)
    assert a["result"]["incident_id"] == b["result"]["incident_id"]
    log = reg.backend.audit_log(5)
    assert log[0]["flags"] == "idempotent_replay" and log[0]["client_id"] == "incident-commander"


def test_approval_lifecycle(reg):
    r = reg.invoke("agent-token", "page_engineer", {"engineer_id": "ENG-006", "message": "please look at payments-db"})
    assert r["outcome"] == "pending_approval" and reg.backend.pages() == []
    apr = r["result"]["approval_id"]
    assert reg.decide(apr, True, "sre.lead")["status"] == "approved"
    assert len(reg.backend.pages()) == 1
    assert "error" in reg.decide(apr, False, "sre.lead")      # cannot be decided twice


def test_injection_text_never_reaches_the_client(reg):
    r = reg.invoke("agent-token", "get_article", {"article_id": "KB-0016"})
    assert "injection_quarantined" in r["flags"] and "ignore all previous" not in str(r["result"]).lower()
    assert "quarantined:" in reg.backend.audit_log(1)[0]["detail"]
