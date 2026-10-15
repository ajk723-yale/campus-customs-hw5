"""MCP server tests over a real stdio connection, on scratch copies of the data.

The real data/campus_customs_new.db and output/payment_approvals.json are never
touched: the server is pointed at copies in a temp folder via CAMPUS_DB_PATH
and CAMPUS_APPROVALS_PATH. The "human approval" step is simulated by editing
the scratch approvals file, only to prove execute_payment's guards.

Run:  .venv/bin/python tests/test_mcp_server.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = Path(__file__).resolve().parent.parent
REAL_DB = ROOT / "data" / "campus_customs_new.db"
ORIGINAL_DB = ROOT / "data" / "campus_customs.db"  # scratch copies start from the untouched original
PASSED: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise AssertionError(f"FAILED: {name} {detail}")
    PASSED.append(name)
    print(f"  ok  {name}")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def human_approves(approvals: Path, approval_id: str) -> None:
    """Test stand-in for scripts/approve_payment.py, on the scratch file only."""
    records = json.loads(approvals.read_text())
    for r in records:
        if r["approval_id"] == approval_id:
            r.update(status="approved", approved_by="Test Human", approved_at="2026-08-31T12:00:00+00:00")
    approvals.write_text(json.dumps(records))


async def main() -> None:
    real_before = sha(REAL_DB)
    tmp = Path(tempfile.mkdtemp(prefix="campus_mcp_test_"))
    db, approvals = tmp / "campus.db", tmp / "approvals.json"
    shutil.copy(ORIGINAL_DB, db)
    transport = StdioTransport(
        command=str(ROOT / ".venv" / "bin" / "python"),
        args=[str(ROOT / "mcp_server" / "server.py")],
        env={"CAMPUS_DB_PATH": str(db), "CAMPUS_APPROVALS_PATH": str(approvals)},
    )

    async with Client(transport) as client:
        async def call(name: str, **args):
            result = await client.call_tool(name, args)
            data = result.structured_content
            return data["result"] if isinstance(data, dict) and set(data) == {"result"} else data

        print("tools")
        names = {t.name for t in await client.list_tools()}
        check("24 tools listed", len(names) == 24, sorted(names))
        check("original 3 tools kept", {"get_product_info", "get_invoice_info", "get_rent_info"} <= names)

        print("lookups")
        check("shop date", (await call("get_shop_date"))["date_today"] == "2026-08-31")
        check("3 open tickets", [t["id"] for t in await call("list_tickets", status="open")] == [101, 102, 103])
        check("tee S out of stock", (await call("get_product_info", sku="CC-TEE-WHITE", size="S"))["qty"] == 0)
        sizes = await call("get_product_sizes", sku="CC-HOOD-NAVY")
        check("hoodie sizes total 32", sizes["total_qty"] == 32, sizes)
        q = await call("quote_price", sku="CC-HOOD-NAVY", quantity=20, discount_pct=10)
        check("quote 10% off hoodie = 52.20", q["unit_price"] == 52.2 and q["allowed"], q)
        q = await call("quote_price", sku="CC-HOOD-NAVY", quantity=20, discount_pct=70)
        check("quote below cost not allowed", q["allowed"] is False, q)
        v = await call("get_vendor_status", vendor_id=1)
        check("Bulldog Print Co restricted (invoice 501 unpaid)", v["restricted"] is True, v)
        check("Elm City Gifts not restricted", (await call("get_vendor_status", vendor_id=2))["restricted"] is False)
        inv = await call("list_open_invoices")
        check("invoice 501 3 days overdue", inv["open_invoices"][0]["days_overdue"] == 3, inv)
        cash = await call("get_cash_position")
        check("cash 3400, 160 after all obligations",
              cash["checking_balance"] == 3400 and cash["checking_after_all_obligations"] == 160, cash)

        print("vendor restriction: any unpaid invoice")
        # Scratch DB only: give Elm City Gifts an unpaid invoice that is NOT overdue yet.
        with sqlite3.connect(db) as conn:
            conn.execute("INSERT INTO invoices (id, vendor_id, amount, due_date, status, description) "
                         "VALUES (9001, 2, 50.0, '2026-09-30', 'open', 'test invoice, not yet due')")
        v2 = await call("get_vendor_status", vendor_id=2)
        check("vendor with an unpaid but NOT overdue invoice is restricted",
              v2["restricted"] is True and v2["open_invoices"][0]["days_overdue"] == 0, v2)
        check("restriction reason names the unpaid invoice", "#9001" in v2["restriction_reason"], v2)
        check("QuickShip CT (no invoices) not restricted",
              (await call("get_vendor_status", vendor_id=3))["restricted"] is False)
        with sqlite3.connect(db) as conn:
            conn.execute("DELETE FROM invoices WHERE id = 9001")

        print("rent: days until due from desk.date_today")
        rent_info = await call("get_rent_info", lease_id=1)
        check("rent due 2026-09-02, shop date 2026-08-31 -> 2 days until due",
              rent_info["shop_date"] == "2026-08-31" and rent_info["days_until_due"] == 2, rent_info)
        check("get_cash_position agrees on days until due",
              cash["upcoming_rent"][0]["days_until_due"] == 2, cash["upcoming_rent"])
        check("no urgency label or threshold in MCP output",
              not any(k in rent_info for k in ("urgency", "due_soon")), rent_info)

        print("payment guards")
        r = await call("execute_payment", approval_id="PAY-DOESNOTEXIST")
        check("execute unknown id refused", r["executed"] is False, r)
        req = await call("request_payment_approval", kind="invoice", ref_id=501,
                         requested_by="test", reason="test", )
        check("request creates pending, amount from DB", req["created"] and req["status"] == "pending"
              and req["amount"] == 840.0, req)
        dup = await call("request_payment_approval", kind="invoice", ref_id=501, requested_by="test", reason="dup")
        check("duplicate request refused", dup["created"] is False, dup)
        r = await call("execute_payment", approval_id=req["approval_id"])
        check("execute PENDING (not human-approved) refused", r["executed"] is False, r)
        check("balance unchanged after refusals", (await call("get_cash_position"))["checking_balance"] == 3400)

        human_approves(approvals, req["approval_id"])
        r = await call("execute_payment", approval_id=req["approval_id"])
        check("execute human-approved invoice works", r["executed"] and r["balance_after"] == 2560.0, r)
        check("invoice 501 now paid", (await call("get_invoice_info", invoice_id=501))["status"] == "paid")
        check("Bulldog Print Co no longer restricted once its invoice is paid",
              (await call("get_vendor_status", vendor_id=1))["restricted"] is False)
        r = await call("execute_payment", approval_id=req["approval_id"])
        check("same approval can't be used twice", r["executed"] is False, r)
        again = await call("request_payment_approval", kind="invoice", ref_id=501, requested_by="t", reason="t")
        check("paid invoice can't be requested again", again["created"] is False, again)

        rent = await call("request_payment_approval", kind="rent", ref_id=1, requested_by="test", reason="test")
        check("rent request amount 2400 from lease", rent["created"] and rent["amount"] == 2400.0, rent)
        # Drain cash in the scratch DB so paying rent would go negative, then approve.
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE cash_accounts SET balance = 100 WHERE name = 'checking'")
        human_approves(approvals, rent["approval_id"])
        r = await call("execute_payment", approval_id=rent["approval_id"])
        check("approved payment refused when balance would go negative", r["executed"] is False, r)
        check("balance still 100", (await call("get_cash_position"))["checking_balance"] == 100)
        r = await call("request_payment_approval", kind="invoice", ref_id=999, requested_by="t", reason="t")
        check("unknown invoice refused", r["created"] is False, r)

        # Scratch DB only: move the shop date past the rent due date.
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE desk SET date_today = '2026-09-05'")
        late = await call("get_rent_info", lease_id=1)
        check("days_until_due follows desk.date_today and goes negative when past due",
              late["days_until_due"] == -3, late)

    check("real campus_customs_new.db unchanged", sha(REAL_DB) == real_before)
    shutil.rmtree(tmp)
    print(f"\n{len(PASSED)} checks passed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as e:
        print(e)
        sys.exit(1)
