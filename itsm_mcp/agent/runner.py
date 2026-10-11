"""Run the incident commander against an in-process gateway over the MCP protocol (memory streams)."""
from __future__ import annotations

import asyncio

from mcp.shared.memory import create_connected_server_and_client_session

from itsm_mcp.agent.commander import Commander
from itsm_mcp.gateway.registry import Registry
from itsm_mcp.llm import LLMClient
from itsm_mcp.servers.build import build_server


async def _triage_many(reg: Registry, alert_ids: list[str], token: str, act: bool, llm: LLMClient | None, reset_limits: bool) -> list[dict]:
    server = build_server(reg, default_token=token)
    out = []
    async with create_connected_server_and_client_session(server._mcp_server) as session:
        for aid in alert_ids:
            if reset_limits:
                reg.limiter.reset()      # alerts arrive minutes apart in reality; evaluation replays them back to back
            out.append(await Commander(session, llm).triage(aid, act=act))
    return out


def triage(reg: Registry, alert_ids: list[str] | str, token: str = "agent-token", act: bool = True, llm: LLMClient | None = None,
           reset_limits: bool = False):
    single = isinstance(alert_ids, str)
    res = asyncio.run(_triage_many(reg, [alert_ids] if single else alert_ids, token, act, llm, reset_limits))
    return res[0] if single else res
