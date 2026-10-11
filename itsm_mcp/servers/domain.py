"""Run one domain server over stdio, e.g. for a desktop MCP client:

    MCP_TOKEN=readonly-token python -m itsm_mcp.servers.domain cmdb
"""
from __future__ import annotations

import sys

from itsm_mcp.container import get_registry
from itsm_mcp.servers.build import build_server

DOMAINS = ("itsm", "cmdb", "knowledge", "oncall", "monitoring")


def main() -> None:
    domain = sys.argv[1] if len(sys.argv) > 1 else ""
    if domain not in DOMAINS:
        sys.exit(f"usage: python -m itsm_mcp.servers.domain {{{'|'.join(DOMAINS)}}}")
    build_server(get_registry(), domain).run("stdio")


if __name__ == "__main__":
    main()
