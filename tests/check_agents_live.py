"""Live connection and delegation test for the five agents (calls gpt-6-luna via Portkey).

Read-only: it does not work on tickets 101-103, request approvals, or pay
anything. It snapshots the database, tickets, and payment approvals before and
after, checks the audit trail for this run, and saves a summary to
output/agent_connection_test.json.

Run:  .venv/bin/python tests/check_agents_live.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.agents import run_team  # noqa: E402
from backend.config import AUDIT_PATH, MODEL_NAME  # noqa: E402
from backend.mcp_client import AGENT_TOOLS  # noqa: E402

DB = ROOT / "data" / "campus_customs_new.db"
APPROVALS = ROOT / "output" / "payment_approvals.json"
RESULT_PATH = ROOT / "output" / "agent_connection_test.json"

TASK = """CONNECTION AND DELEGATION TEST ONLY.
Do not analyze, decide, or resolve tickets 101, 102, or 103. Do not request payment approvals or execute payments.
Leave ticket_decisions and payments_needing_human_approval empty.

Delegate exactly one short check to each specialist (ticket_ids = []):
1. inventory: call get_product_sizes for CC-HAT-BLUE and get_vendor_status for vendor 2, and report the results.
2. accounting: call get_shop_date and get_cash_position, and report the shop date and checking balance. Do not request or execute any payment.
3. facilities: call get_shop_date, then consult accounting once, asking it to call get_cash_position and report the checking balance.
4. customer_service: call quote_price for CC-MUG-CREST, quantity 1, discount 0, then consult inventory once, asking it to call get_product_sizes for CC-MUG-CREST. Do not draft customer replies.

Then say in `summary` which specialists responded and which tools they used."""


def snapshot() -> dict:
    with sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True) as conn:
        tables = {t: conn.execute(f"SELECT * FROM {t}").fetchall()
                  for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {
        "db_sha256": hashlib.sha256(DB.read_bytes()).hexdigest(),
        "tickets": tables["tickets"],
        "payments_rows": len(tables["payments"]),
        "approvals": APPROVALS.read_text() if APPROVALS.exists() else None,
    }


async def main() -> int:
    before = snapshot()
    run_id, output = await run_team(TASK)
    after = snapshot()

    events = [e for e in json.loads(AUDIT_PATH.read_text()) if e["run_id"] == run_id]
    delegations = [(e["agent"], e["to"], e["depth"] + 1) for e in events if e["event"] == "delegation_started"]
    tool_calls = [(e["agent"], e["tool"]) for e in events if e["event"] == "tool_call"]
    finished = [e for e in events if e["event"] == "agent_finished"]
    run_end = next(e for e in events if e["event"] in ("run_finished", "run_failed"))

    checks = {
        "run finished": run_end["event"] == "run_finished",
        "boss delegated to all four specialists": {t for a, t, d in delegations if a == "boss"}
        == {"inventory", "accounting", "facilities", "customer_service"},
        "specialist-to-specialist delegation (depth 2) happened": any(d == 2 for _, _, d in delegations),
        "every agent run finished with a structured output": len(finished) == len(delegations) + 1,
        "every tool call was allowed for its agent": all(t in AGENT_TOOLS[a] for a, t in tool_calls),
        "every agent used gpt-6-luna": all(e["model"] == MODEL_NAME for e in events if e["event"] == "agent_started"),
        "no approval requests or payments": not any(e["event"] in ("approval_requested", "payment_executed",
                                                                   "payment_blocked") for e in events),
        "ticket decisions left empty": not output.ticket_decisions and not output.payments_needing_human_approval,
        "database unchanged (sha256)": before["db_sha256"] == after["db_sha256"],
        "tickets 101-103 unchanged": before["tickets"] == after["tickets"],
        "no payments rows added": before["payments_rows"] == after["payments_rows"] == 0,
        "payment approvals unchanged": before["approvals"] == after["approvals"],
    }
    summary = {
        "run_id": run_id,
        "model": MODEL_NAME,
        "task": TASK,
        "delegations": [{"from": a, "to": t, "depth": d} for a, t, d in delegations],
        "tool_calls": [{"agent": a, "tool": t} for a, t in tool_calls],
        "usage": run_end.get("usage"),
        "boss_output": output.model_dump(mode="json"),
        "checks": checks,
        "all_passed": all(checks.values()),
    }
    RESULT_PATH.write_text(json.dumps(summary, indent=2))

    print(f"run {run_id}  usage {run_end.get('usage')}")
    print("delegations:", *[f"{a} -> {t} (depth {d})" for a, t, d in delegations], sep="\n  ")
    print("tool calls:", *[f"{a}: {t}" for a, t in tool_calls], sep="\n  ")
    print("\nBoss summary:", output.summary, "\n")
    for name, ok in checks.items():
        print(f"  {'ok ' if ok else 'FAIL'} {name}")
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
