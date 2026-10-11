"""Run the MCP gateway.

    python -m itsm_mcp.servers.gateway                       # streamable HTTP on :8000/mcp (Bearer token per request)
    MCP_TOKEN=agent-token python -m itsm_mcp.servers.gateway --stdio
"""
from __future__ import annotations

import argparse
import os

from itsm_mcp import logging_setup
from itsm_mcp.container import get_registry
from itsm_mcp.servers.build import build_server


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdio", action="store_true")
    ap.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    a = ap.parse_args()
    logging_setup.configure()
    mcp = build_server(get_registry())
    if a.stdio:
        mcp.run("stdio")
    else:
        mcp.settings.host, mcp.settings.port = a.host, a.port
        mcp.run("streamable-http")


if __name__ == "__main__":
    main()
