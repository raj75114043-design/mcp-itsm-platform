import asyncio
import json

from mcp.shared.memory import create_connected_server_and_client_session

from itsm_mcp.servers.build import build_server


def _run(reg, fn, domain=None, token="agent-token"):
    async def go():
        async with create_connected_server_and_client_session(build_server(reg, domain, token)._mcp_server) as s:
            return await fn(s)
    return asyncio.run(go())


def test_gateway_lists_all_tools_with_annotations(reg):
    tools = _run(reg, lambda s: s.list_tools()).tools
    by = {t.name: t for t in tools}
    assert len(tools) == 15
    assert by["page_engineer"].annotations.destructiveHint and by["get_ci"].annotations.readOnlyHint
    assert by["get_ci"].inputSchema["properties"]["ci_id"]["pattern"]


def test_domain_server_exposes_only_its_tools(reg):
    names = {t.name for t in _run(reg, lambda s: s.list_tools(), domain="cmdb").tools}
    assert names == {"get_ci", "get_dependencies", "impacted_services"}


def test_call_resource_prompt_and_errors(reg):
    async def flow(s):
        ok = await s.call_tool("impacted_services", {"ci_id": "payments-db"})
        res = await s.read_resource("incident://INC-00001")
        prompt = await s.get_prompt("triage_alert", {"alert_id": "ALR-001"})
        bad = await s.call_tool("get_incident", {"incident_id": "INC-99999"})
        return ok, res, prompt, bad
    ok, res, prompt, bad = _run(reg, flow)
    assert json.loads(ok.content[0].text)["result"]["highest_tier"] == 1
    assert "[email redacted]" in res.contents[0].text
    assert "get_alert" in prompt.messages[0].content.text
    assert bad.isError and "NOT_FOUND" in bad.content[0].text


def test_readonly_token_gets_error_for_writes(reg):
    r = _run(reg, lambda s: s.call_tool("create_incident", {"title": "x" * 6, "ci_id": "payments-db", "priority": "P3",
                                                            "description": "should be refused"}), token="readonly-token")
    assert r.isError and "forbidden" in r.content[0].text
