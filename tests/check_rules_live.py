"""Live check (gpt-6-luna) of two shop rules, on a scratch copy of the database.

1. Vendor restriction: a vendor with ANY unpaid invoice is restricted, even if
   the invoice isn't overdue. The scratch DB gives Elm City Gifts (vendor 2) an
   open invoice due 2026-09-30, after the shop date of 2026-08-31.
2. Rent urgency: there's no fixed threshold. MCP reports days_until_due
   (next_due minus desk.date_today) and the Facilities Agent judges urgency from
   it. The scratch DB adds a test lease (id 2) due 2026-09-20, 20 days out.

The real database, tickets 101-103, approvals, and audit trail are not touched:
the MCP server and audit log point at scratch files.

Run:  .venv/bin/python tests/check_rules_live.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REAL_DB = ROOT / "data" / "campus_customs_new.db"
TMP = Path(tempfile.mkdtemp(prefix="campus_rules_live_"))
os.environ["CAMPUS_DB_PATH"] = str(TMP / "campus.db")
os.environ["CAMPUS_APPROVALS_PATH"] = str(TMP / "approvals.json")
os.environ["CAMPUS_AUDIT_PATH"] = str(TMP / "audit.json")
sys.path.insert(0, str(ROOT))

from backend.agents import CampusTeam, run_team  # noqa: E402


def make_scratch_db() -> None:
    shutil.copy(REAL_DB, TMP / "campus.db")
    with sqlite3.connect(TMP / "campus.db") as conn:
        conn.execute("INSERT INTO invoices (id, vendor_id, amount, due_date, status, description) "
                     "VALUES (9001, 2, 120.0, '2026-09-30', 'open', 'TEST ONLY: mug restock, not yet due')")
        conn.execute("INSERT INTO leases (id, space_name, landlord, monthly_rent, next_due, notes) "
                     "VALUES (2, 'TEST ONLY storage unit', 'Test Landlord', 300.0, '2026-09-20', 'scratch test lease')")


async def main() -> int:
    real_before = hashlib.sha256(REAL_DB.read_bytes()).hexdigest()
    make_scratch_db()
    results = {}
    async with CampusTeam() as team:
        _, inv = await run_team(
            "TEST ONLY. CC-MUG-CREST size OS: 5 are needed. Check stock, pick the vendor whose specialty fits, "
            "check that vendor's status, and give one replenishment plan. Do not consult other agents.",
            entry_agent="inventory", team=team)
        _, fac = await run_team(
            "TEST ONLY. Assess the rent obligation for lease 2: how many days until it is due and how urgent it is. "
            "Do not consult other agents.",
            entry_agent="facilities", team=team)
    plan = inv.replenishment_plans[0] if inv.replenishment_plans else None
    rent = next((r for r in fac.rent_obligations if r.lease_id == 2), None)

    checks = {
        "inventory chose Elm City Gifts (vendor 2)": plan is not None and plan.vendor_id == 2,
        "vendor 2 reported restricted although its invoice is not overdue": plan is not None and plan.vendor_restricted,
        "restricted vendor not orderable now": plan is not None and plan.can_order_now is False,
        "facilities reported lease 2": rent is not None,
        "days_until_due = 20 (2026-09-20 minus desk.date_today 2026-08-31)": rent is not None and rent.days_until_due == 20,
        "urgency is a written assessment with reasoning": rent is not None and bool(rent.urgency.strip())
        and bool(rent.urgency_reasoning.strip()),
        "real database unchanged": hashlib.sha256(REAL_DB.read_bytes()).hexdigest() == real_before,
    }
    results = {
        "inventory_plan": plan.model_dump() if plan else None,
        "facilities_rent": rent.model_dump() if rent else None,
        "checks": checks,
    }
    print(json.dumps(results, indent=2))
    shutil.rmtree(TMP)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
