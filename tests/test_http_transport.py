"""Starts the gateway as a real process on streamable HTTP and connects with the MCP client and a Bearer token."""
import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_streamable_http_gateway_with_bearer_tokens():
    port = _free_port()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tempfile.mkdtemp()}/http.db", "PORT": str(port), "HOST": "127.0.0.1"}
    proc = subprocess.Popen([sys.executable, "-m", "itsm_mcp.servers.gateway"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except Exception:
                time.sleep(0.5)

        async def call(token, tool, args):
            async with streamablehttp_client(f"http://127.0.0.1:{port}/mcp", headers={"Authorization": f"Bearer {token}"}) as (r, w, _):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    return len((await s.list_tools()).tools), await s.call_tool(tool, args)

        n, ok = asyncio.run(call("agent-token", "get_ci", {"ci_id": "payments-db"}))
        assert n == 15 and not ok.isError
        _, denied = asyncio.run(call("readonly-token", "add_work_note", {"incident_id": "INC-00001", "note": "not allowed"}))
        assert denied.isError and "forbidden" in denied.content[0].text
        _, anon = asyncio.run(call("wrong-token", "get_ci", {"ci_id": "payments-db"}))
        assert anon.isError and "unauthenticated" in anon.content[0].text
        req = urllib.request.Request(f"http://127.0.0.1:{port}/approvals", headers={"Authorization": "Bearer agent-token"})
        try:
            urllib.request.urlopen(req)
            raise AssertionError("approvals must require an admin token")
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        proc.terminate()
        proc.wait(10)
