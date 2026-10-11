"""Command line.

    python -m itsm_mcp.cli seed                  # (re)seed the configured database
    python -m itsm_mcp.cli triage ALR-001        # run the incident commander on one alert
    python -m itsm_mcp.cli smoke                 # triage every alert against the configured database and check accuracy
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from itsm_mcp.agent.runner import triage
from itsm_mcp.container import build, get_registry

FIELDS = ("root_ci", "root_change", "duplicate_of", "kb_article", "team", "on_call", "priority")


def main() -> None:
    logging.disable(logging.INFO)
    ap = argparse.ArgumentParser(prog="itsm-mcp")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    t = sub.add_parser("triage")
    t.add_argument("alert_id")
    sub.add_parser("smoke")
    a = ap.parse_args()
    if a.cmd == "seed":
        build(reseed=True)
        print("seeded")
    elif a.cmd == "triage":
        r = triage(get_registry(), a.alert_id)
        print(json.dumps({k: v for k, v in r.items() if k not in ("trace", "alert")}, indent=2, default=str))
    else:
        reg = build(reseed=True)
        truth = {t["alert_id"]: t for t in reg.backend.truth()}
        res = triage(reg, sorted(truth), reset_limits=True)
        wrong = [(r["alert"]["alert_id"], f) for r in res for f in FIELDS
                 if r[f] != truth[r["alert"]["alert_id"]][f] and not (f == "root_change" and truth[r["alert"]["alert_id"]]["scenario"] == "duplicate")]
        print(f"{len(res)} alerts triaged on {reg.backend.engine.url.get_backend_name()}; mismatches: {wrong}")
        sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    main()
