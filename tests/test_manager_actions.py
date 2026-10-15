"""Manager-action MCP tools, over a real stdio MCP connection, on SCRATCH copies only.

Walks through Ticket 101- and 103-style sequences to prove every guard:
duplicate orders / receipts / fulfilment are refused, cash warnings must be
acknowledged, fulfilment needs a recorded customer response (and a pricing
decision for price requests), a different size needs the customer's recorded
'alternative' choice, and cash never changes. The "human approval" step is
simulated by editing the scratch approvals file, only to reach later states.

Run:  .venv/bin/python tests/test_manager_actions.py
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
ORIGINAL = ROOT / "data" / "campus_customs.db"
REAL = [ROOT / "data" / "campus_customs_new.db", ROOT / "output" / "payment_approvals.json"]
PASSED: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise AssertionError(f"FAILED: {name} {detail}")
    PASSED.append(name)
    print(f"  ok  {name}")


def sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


async def main() -> None:
    real_before = {p: sha(p) for p in REAL}
    tmp = Path(tempfile.mkdtemp(prefix="campus_manager_test_"))
    db, approvals, events = tmp / "campus.db", tmp / "approvals.json", tmp / "events.json"
    shutil.copy(ORIGINAL, db)
    transport = StdioTransport(
        command=str(ROOT / ".venv" / "bin" / "python"), args=[str(ROOT / "mcp_server" / "server.py")],
        env={"CAMPUS_DB_PATH": str(db), "CAMPUS_APPROVALS_PATH": str(approvals), "CAMPUS_MANAGER_EVENTS_PATH": str(events)},
    )

    def human_approves(approval_id: str) -> None:
        recs = json.loads(approvals.read_text())
        for r in recs:
            if r["approval_id"] == approval_id:
                r.update(status="approved", approved_by="Test Human", approved_at="2026-08-31T12:00:00+00:00")
        approvals.write_text(json.dumps(recs))

    def qty(sku: str, size: str) -> int:
        with sqlite3.connect(db) as c:
            return c.execute("SELECT qty FROM inventory WHERE sku=? AND size=?", (sku, size)).fetchone()[0]

    def balance() -> float:
        with sqlite3.connect(db) as c:
            return c.execute("SELECT balance FROM cash_accounts WHERE name='checking'").fetchone()[0]

    def invoice_count() -> int:
        with sqlite3.connect(db) as c:
            return c.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]

    M = dict(recorded_by="Test Human", simulated=True, basis="Simulated for a test: no real customer or vendor")

    async with Client(transport) as client:
        async def call(name, **args):
            r = await client.call_tool(name, args)
            d = r.structured_content
            return d["result"] if isinstance(d, dict) and set(d) == {"result"} else d

        names = {t.name for t in await client.list_tools()}
        check("24 tools: 17 earlier + get_ticket_updates + 6 manager actions", len(names) == 24, sorted(names))

        print("setup: pay invoice 501 on the scratch copy")
        pay = await call("request_payment_approval", kind="invoice", ref_id=501, requested_by="t", reason="t", ticket_id=101)
        human_approves(pay["approval_id"])
        await call("execute_payment", approval_id=pay["approval_id"])
        cash0, inv0 = balance(), invoice_count()
        check("scratch: invoice 501 paid, checking 2560", cash0 == 2560.0)
        rent = await call("request_payment_approval", kind="rent", ref_id=1, requested_by="t", reason="t", ticket_id=102)
        human_approves(rent["approval_id"])
        await call("execute_payment", approval_id=rent["approval_id"])
        pos = await call("get_cash_position")
        check("paid rent is marked already_paid and not counted again (lease next_due unchanged)",
              pos["checking_balance"] == 160.0 and pos["upcoming_rent"][0]["already_paid"] is True
              and pos["upcoming_rent"][0]["next_due"] == "2026-09-02" and pos["total_listed_obligations"] == 0, pos)
        cash0 = balance()

        print("Ticket 101: possible overlap with invoice 501")
        u = await call("get_ticket_updates", ticket_id=101)
        check("get_ticket_updates: no events yet", u["found"] and u["events"] == [] and u["quantity_still_to_fulfil"] == 1)
        u = await call("get_ticket_updates", ticket_id=101)
        check("ticket 101's linked invoice 501 is reported as the restock for the item (no quantity assumed)",
              u["linked_invoice"]["invoice_id"] == 501 and u["linked_invoice"]["covers_requested_item"]
              and "not recorded" in u["linked_invoice"]["note"], u["linked_invoice"])
        r = await call("request_purchase_approval", sku="CC-TEE-WHITE", size="S", quantity=1, vendor_id=1,
                       requested_by="inventory_agent", reason="t", ticket_id=101)
        check("purchase request for ticket 101's item refused: its linked invoice 501 is the restock", r["created"] is False
              and "invoice 501" in r["error"], r)
        # Without a ticket link, the same purchase is allowed but warned as a possible duplicate.
        buy = await call("request_purchase_approval", sku="CC-TEE-WHITE", size="S", quantity=1, vendor_id=1,
                         requested_by="inventory_agent", reason="t", ticket_id=None)
        check("unlinked purchase of the same item warns it may duplicate invoice 501",
              buy["created"] and any(w.get("invoice_id") == 501 for w in buy["duplicate_warnings"]), buy)
        human_approves(buy["approval_id"])
        r = await call("record_stock_receipt", sku="CC-TEE-WHITE", size="S", quantity=1, source_kind="invoice",
                       source_id="501", ticket_id=101, **M)
        check("receipt against invoice 501 refused while the BUY is still active", r["recorded"] is False
              and buy["approval_id"] in r["error"], r)
        r = await call("place_purchase_order", approval_id=buy["approval_id"], vendor_reference="", acknowledge_cash_warning=False,
                       acknowledge_duplicate_warning=False, **M)
        check("ordering needs the possible-duplicate warning acknowledged",
              r["recorded"] is False and r["needs_acknowledgement"] == ["possible-duplicate warning"], r)
        r = await call("cancel_purchase", approval_id=buy["approval_id"], reason="Covered by invoice 501 reprint (test)",
                       recorded_by="Test Human")
        check("cancel an approved, not-ordered purchase", r["recorded"] and r["status"] == "cancelled", r)
        r = await call("cancel_purchase", approval_id=buy["approval_id"], reason="again", recorded_by="Test Human")
        check("cancel twice refused", r["recorded"] is False, r)
        r = await call("place_purchase_order", approval_id=buy["approval_id"], vendor_reference="", acknowledge_cash_warning=True,
                       acknowledge_duplicate_warning=True, **M)
        check("a cancelled purchase can't be ordered", r["recorded"] is False, r)
        r = await call("record_stock_receipt", sku="CC-TEE-WHITE", size="S", quantity=1, source_kind="invoice",
                       source_id="501", ticket_id=101, **M)
        check("receipt against invoice 501 after cancelling: stock 0 -> 1", r["recorded"] and qty("CC-TEE-WHITE", "S") == 1, r)
        r = await call("record_stock_receipt", sku="CC-TEE-WHITE", size="S", quantity=1, source_kind="invoice",
                       source_id="501", ticket_id=101, **M)
        check("second receipt against the same invoice refused (no duplicate receipts)", r["recorded"] is False
              and qty("CC-TEE-WHITE", "S") == 1, r)
        r = await call("record_fulfilment", ticket_id=101, sku="CC-TEE-WHITE", size="S", quantity=1, **M)
        check("fulfilment refused without a recorded customer response", r["recorded"] is False and "customer" in r["error"], r)
        r = await call("record_customer_response", ticket_id=101, choice="wait", summary="Will wait for size S",
                       channel="simulated", **M)
        check("customer response recorded, marked simulated", r["recorded"] and r["event"]["simulated"] is True, r)
        r = await call("record_fulfilment", ticket_id=101, sku="CC-TEE-WHITE", size="M", quantity=1, **M)
        check("different size refused unless the customer chose 'alternative'", r["recorded"] is False
              and "alternative" in r["error"], r)
        r = await call("record_fulfilment", ticket_id=101, sku="CC-TEE-WHITE", size="S", quantity=1, **M)
        check("fulfil 1 size S: stock 1 -> 0, revenue not recorded", r["recorded"] and qty("CC-TEE-WHITE", "S") == 0
              and r["event"]["details"]["revenue_recorded"] is False, r)
        r = await call("record_fulfilment", ticket_id=101, sku="CC-TEE-WHITE", size="S", quantity=1, **M)
        check("fulfilling again refused (no duplicate fulfilment)", r["recorded"] is False, r)

        print("Ticket 103: $264 restock vs $160 cash")
        cash0 = balance()  # 160 after rent and invoice 501, as in the real shop
        buy2 = await call("request_purchase_approval", sku="CC-HOOD-NAVY", size="M", quantity=12, vendor_id=1,
                          requested_by="inventory_agent", reason="t", ticket_id=103)
        check("purchase request shows a cash warning ($264 > $160)", buy2["created"] and buy2["cash_warning"]
              and buy2["cash_warning"]["shortfall"] == 104.0, buy2)
        human_approves(buy2["approval_id"])
        r = await call("place_purchase_order", approval_id=buy2["approval_id"], vendor_reference="", acknowledge_cash_warning=False,
                       acknowledge_duplicate_warning=False, **M)
        check("ordering needs the cash warning acknowledged", r["recorded"] is False
              and r["needs_acknowledgement"] == ["cash warning"], r)
        r = await call("place_purchase_order", approval_id=buy2["approval_id"], vendor_reference="TEST-PO-1",
                       acknowledge_cash_warning=True, acknowledge_duplicate_warning=False, **M)
        check("order recorded with acknowledgement; arrival = shop date + 5 days; cash unchanged",
              r["recorded"] and r["expected_arrival"] == "2026-09-05" and balance() == 160.0, r)
        bill = r["vendor_invoice_id"]
        with sqlite3.connect(db) as c:
            row = c.execute("SELECT vendor_id, amount, due_date, status FROM invoices WHERE id=?", (bill,)).fetchone()
        check("ordering created an OPEN vendor invoice: $264 due 2026-09-05, no cash movement",
              row == (1, 264.0, "2026-09-05", "open") and invoice_count() == inv0 + 1 and balance() == 160.0, row)
        v = await call("get_vendor_status", vendor_id=1)
        check("the vendor is now restricted by the unpaid bill", v["restricted"] is True, v)
        u = await call("get_ticket_updates", ticket_id=103)
        check("ticket updates show the unpaid vendor invoice and the cash", len(u["unpaid_vendor_invoices"]) == 1
              and u["cash"]["open_invoices_total"] == 264.0 and u["cash"]["checking_balance"] == 160.0, u["cash"])
        pr = await call("request_payment_approval", kind="invoice", ref_id=bill, requested_by="accounting_agent",
                        reason="pay the hoodie bill", ticket_id=103)
        check("paying the $264 bill is refused while checking holds $160 (cash never goes negative)",
              pr["created"] is False and "negative" in pr["error"], pr)
        u = await call("get_ticket_updates", ticket_id=103)
        check("ticket updates show the open step (ordered, not received)", len(u["open_steps"]) == 1, u["open_steps"])
        r = await call("request_purchase_approval", sku="CC-HOOD-NAVY", size="M", quantity=12, vendor_id=1,
                       requested_by="inventory_agent", reason="t", ticket_id=103)
        check("a second purchase for the same item is refused while one is ordered", r["created"] is False, r)

        print("human rejections are respected")
        sys.path.insert(0, str(ROOT / "mcp_server"))
        import os as _os
        _os.environ["CAMPUS_APPROVALS_PATH"] = str(approvals)
        import importlib, approvals as appr_mod
        importlib.reload(appr_mod)
        rej = await call("request_purchase_approval", sku="CC-HAT-BLUE", size="OS", quantity=40, vendor_id=2,
                         requested_by="inventory_agent", reason="t", ticket_id=103)
        appr_mod.record_human_decision(rej["approval_id"], "Test Human", approve=False, reason="Not enough cash right now")
        rec = next(x for x in json.loads(approvals.read_text()) if x["approval_id"] == rej["approval_id"])
        check("rejection reason stored on the request", rec["status"] == "rejected" and rec["rejection_reason"] == "Not enough cash right now")
        r = await call("request_purchase_approval", sku="CC-HAT-BLUE", size="OS", quantity=40, vendor_id=2,
                       requested_by="inventory_agent", reason="again", ticket_id=103)
        check("re-requesting a human-rejected purchase refused while nothing changed (reason quoted)", r["created"] is False
              and "Not enough cash right now" in r["error"] and r["previous_rejection"]["approval_id"] == rej["approval_id"], r)
        r = await call("request_purchase_approval", sku="CC-HAT-BLUE", size="OS", quantity=10, vendor_id=2,
                       requested_by="inventory_agent", reason="smaller", ticket_id=103)
        check("changing only the quantity doesn't get around the rejection", r["created"] is False, r)
        u = await call("get_ticket_updates", ticket_id=103)
        check("ticket updates list the rejection with who and why", any(x["approval_id"] == rej["approval_id"]
              and x["rejection_reason"] == "Not enough cash right now" for x in u["rejected_purchases"]), u["rejected_purchases"])
        await asyncio.sleep(1.2)  # timestamps are second-precise; the response must come after the rejection
        await call("record_customer_response", ticket_id=103, choice="accept", summary="Wants the caps too",
                   channel="simulated", **M)
        r = await call("request_purchase_approval", sku="CC-HAT-BLUE", size="OS", quantity=40, vendor_id=2,
                       requested_by="inventory_agent", reason="customer confirmed", ticket_id=103)
        check("allowed again once a newer customer response is recorded (circumstances changed)", r["created"] is True, r)
        r = await call("record_stock_receipt", sku="CC-HOOD-NAVY", size="M", quantity=13, source_kind="purchase_order",
                       source_id=buy2["approval_id"], **M)
        check("receiving more than ordered refused", r["recorded"] is False, r)
        r = await call("record_stock_receipt", sku="CC-HOOD-NAVY", size="M", quantity=12, source_kind="purchase_order",
                       source_id=buy2["approval_id"], **M)
        check("receipt against the order: stock 8 -> 20, no second vendor invoice created", r["recorded"]
              and qty("CC-HOOD-NAVY", "M") == 20 and invoice_count() == inv0 + 1, r)
        r = await call("record_stock_receipt", sku="CC-HOOD-NAVY", size="M", quantity=12, source_kind="purchase_order",
                       source_id=buy2["approval_id"], **M)
        check("receiving the same order twice refused", r["recorded"] is False and qty("CC-HOOD-NAVY", "M") == 20, r)
        await call("record_customer_response", ticket_id=103, choice="accept", summary="Accepts", channel="simulated", **M)
        r = await call("record_fulfilment", ticket_id=103, sku="CC-HOOD-NAVY", size="M", quantity=20, **M)
        check("price request can't be fulfilled before a pricing decision", r["recorded"] is False and "pricing" in r["error"], r)
        r = await call("record_pricing_decision", ticket_id=103, sku="CC-HOOD-NAVY", size="M", quantity=20, discount_pct=70,
                       decision="approved", recorded_by="Test Human", note="", simulated=False, basis="test")
        check("approving a price below cost refused", r["recorded"] is False and "below" in r["error"], r)
        r = await call("record_pricing_decision", ticket_id=103, sku="CC-HOOD-NAVY", size="M", quantity=20, discount_pct=10,
                       decision="approved", recorded_by="Test Human", note="", simulated=False, basis="test")
        check("10% approved: $52.20 each, $30.20 margin, recomputed from pricing", r["recorded"]
              and r["event"]["details"]["unit_price"] == 52.2 and r["event"]["details"]["margin_per_unit"] == 30.2, r)
        r = await call("record_fulfilment", ticket_id=103, sku="CC-HOOD-NAVY", size="M", quantity=21, **M)
        check("fulfilling more than the ticket's 20 refused", r["recorded"] is False, r)
        r = await call("record_fulfilment", ticket_id=103, sku="CC-HOOD-NAVY", size="M", quantity=20, **M)
        check("fulfil 20: stock 20 -> 0", r["recorded"] and qty("CC-HOOD-NAVY", "M") == 0, r)

        print("money and records")
        check("cash never changed by any manager action", balance() == cash0)
        evs = json.loads(events.read_text())
        check("every event has recorded_by, simulated flag, and basis",
              all(e["recorded_by"] and isinstance(e["simulated"], bool) and e["basis"] for e in evs), evs[:1])
        check("event kinds recorded", {e["kind"] for e in evs} == {"purchase_cancelled", "stock_receipt", "customer_response",
                                                                   "fulfilment", "purchase_order", "pricing_decision"})

    check("real database and approvals unchanged", all(sha(p) == h for p, h in real_before.items()))
    shutil.rmtree(tmp)
    print(f"\n{len(PASSED)} checks passed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as e:
        print(e)
        sys.exit(1)
