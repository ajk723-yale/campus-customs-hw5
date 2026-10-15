"""Campus Customs MCP server: the only way the agents read or change shop data.

Every shop fact comes from data/campus_customs_new.db. All tools open the
database read-only except execute_payment, which runs only for a payment a
human has approved (see scripts/approve_payment.py) and never lets cash go
below zero. Payment approval requests are kept in output/payment_approvals.json,
outside the shop database.

Run (stdio):  ../.venv/bin/python server.py
Run (HTTP):   ../.venv/bin/python server.py --http
HTTP URL:     http://127.0.0.1:8002/mcp

Environment overrides (used by tests to work on scratch copies):
  CAMPUS_DB_PATH          path to the SQLite database
  CAMPUS_APPROVALS_PATH   path to the payment approvals JSON file
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

from approvals import APPROVALS_PATH, PURCHASE_KIND, approvals_file, read_approvals
from manager_events import append_event, read_events

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB_PATH = Path(os.getenv("CAMPUS_DB_PATH", ROOT / "data" / "campus_customs_new.db"))

# Payments made by the agents always come out of this account.
PAYMENT_ACCOUNT = "checking"

mcp = FastMCP("campus-customs")
READ_ONLY = {"readOnlyHint": True}


def connect() -> sqlite3.Connection:
    """Open the database read-only so a lookup tool can't change it."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def shop_today(conn: sqlite3.Connection) -> str:
    """The shop's 'today' from the desk table (not the real clock)."""
    row = conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
    return row["date_today"]


def days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days


# --------------------------------------------------------------------------
# What a payment would pay (amount always read from the database)
# --------------------------------------------------------------------------

def payment_target(conn: sqlite3.Connection, kind: str, ref_id: int) -> dict:
    """Look up what a payment would pay, straight from the database.

    Returns amount, due date, payee, and whether it is still payable, so the
    amount always comes from the shop records rather than from an agent.
    """
    if kind == "invoice":
        row = conn.execute(
            """SELECT inv.id, inv.amount, inv.due_date, inv.status, inv.description, v.name AS payee
               FROM invoices AS inv LEFT JOIN vendors AS v ON v.id = inv.vendor_id
               WHERE inv.id = ?""",
            (ref_id,),
        ).fetchone()
        if row is None:
            return {"found": False, "error": f"No invoice with id={ref_id}."}
        return {
            "found": True, "kind": "invoice", "ref_id": row["id"], "amount": row["amount"],
            "due_date": row["due_date"], "payee": row["payee"], "description": row["description"],
            "payable": row["status"] == "open",
            "not_payable_reason": None if row["status"] == "open" else f"invoice status is {row['status']!r}",
        }
    if kind == "rent":
        row = conn.execute("SELECT * FROM leases WHERE id = ?", (ref_id,)).fetchone()
        if row is None:
            return {"found": False, "error": f"No lease with id={ref_id}."}
        already_paid = any(
            r["kind"] == "rent" and r["ref_id"] == ref_id and r["status"] == "executed"
            and r["due_date"] == row["next_due"]
            for r in read_approvals()
        )
        return {
            "found": True, "kind": "rent", "ref_id": row["id"], "amount": row["monthly_rent"],
            "due_date": row["next_due"], "payee": row["landlord"],
            "description": f"Rent for {row['space_name']}",
            "payable": not already_paid,
            "not_payable_reason": "rent for this due date was already paid" if already_paid else None,
        }
    return {"found": False, "error": f"Unknown payment kind {kind!r}; use 'invoice' or 'rent'."}


# --------------------------------------------------------------------------
# Lookup tools (read-only)
# --------------------------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
def get_shop_date() -> dict:
    """Return the shop's current date and desk notes (desk table).

    Use this date, not the real clock, for every due-date and overdue check.
    """
    with closing(connect()) as conn:
        row = conn.execute("SELECT date_today, notes FROM desk LIMIT 1").fetchone()
    return {"date_today": row["date_today"], "notes": row["notes"]}


@mcp.tool(annotations=READ_ONLY)
def list_tickets(status: str | None = None) -> list[dict]:
    """List tickets (tickets table), optionally only those with a given status such as 'open'."""
    with closing(connect()) as conn:
        if status:
            rows = conn.execute("SELECT * FROM tickets WHERE status = ? ORDER BY id", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM tickets ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@mcp.tool(annotations=READ_ONLY)
def get_ticket(ticket_id: int) -> dict:
    """Return one ticket (tickets table): type, requester, product/lease/invoice links, status, notes."""
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        return {"found": False, "error": f"No ticket with id={ticket_id}."}
    return {"found": True, **dict(row)}


@mcp.tool(annotations=READ_ONLY)
def get_product_info(sku: str, size: str) -> dict:
    """Look up one product size: quantity on hand, unit cost, and list price.

    Reads the inventory and pricing tables. Use it to check whether an order
    can be filled from stock and what margin a discount would leave.
    """
    with closing(connect()) as conn:
        row = conn.execute(
            """
            SELECT i.sku, i.name, i.size, i.qty, i.location,
                   p.unit_cost, p.list_price
            FROM inventory AS i
            LEFT JOIN pricing AS p ON p.sku = i.sku
            WHERE i.sku = ? AND i.size = ?
            """,
            (sku.strip(), size.strip().upper()),
        ).fetchone()
        if row is None:
            sizes = conn.execute(
                "SELECT size, qty FROM inventory WHERE sku = ?", (sku.strip(),)
            ).fetchall()
            return {
                "found": False,
                "error": f"No inventory row for sku={sku!r}, size={size!r}.",
                "sizes_for_sku": [dict(r) for r in sizes],
            }
    return {"found": True, **dict(row)}


@mcp.tool(annotations=READ_ONLY)
def get_product_sizes(sku: str) -> dict:
    """List every size of one product with quantity on hand, plus its cost and list price.

    Reads the inventory and pricing tables. Use it to see the total stock across
    sizes, e.g. when one size can't cover an order.
    """
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT size, qty, location, name FROM inventory WHERE sku = ? ORDER BY rowid",
            (sku.strip(),),
        ).fetchall()
        price = conn.execute("SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (sku.strip(),)).fetchone()
    if not rows:
        return {"found": False, "error": f"No inventory rows for sku={sku!r}."}
    return {
        "found": True,
        "sku": sku.strip(),
        "name": rows[0]["name"],
        "sizes": [{"size": r["size"], "qty": r["qty"], "location": r["location"]} for r in rows],
        "total_qty": sum(r["qty"] for r in rows),
        "unit_cost": price["unit_cost"] if price else None,
        "list_price": price["list_price"] if price else None,
    }


@mcp.tool(annotations=READ_ONLY)
def quote_price(sku: str, quantity: int, discount_pct: float = 0.0) -> dict:
    """Work out a price quote from the pricing table: unit price after discount, margin, and totals.

    Flags any quote below unit cost as not allowed. A quote is only a proposal:
    it is not a sale and must never be counted as revenue or cash.
    """
    if quantity <= 0:
        return {"found": False, "error": "quantity must be positive."}
    if not 0 <= discount_pct < 100:
        return {"found": False, "error": "discount_pct must be between 0 and 100."}
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM pricing WHERE sku = ?", (sku.strip(),)).fetchone()
    if row is None:
        return {"found": False, "error": f"No pricing for sku={sku!r}."}
    unit_price = round(row["list_price"] * (1 - discount_pct / 100), 2)
    margin = round(unit_price - row["unit_cost"], 2)
    return {
        "found": True,
        "sku": row["sku"],
        "quantity": quantity,
        "list_price": row["list_price"],
        "unit_cost": row["unit_cost"],
        "discount_pct": discount_pct,
        "unit_price": unit_price,
        "margin_per_unit": margin,
        "margin_pct_of_price": round(100 * margin / unit_price, 1) if unit_price else None,
        "quote_total": round(unit_price * quantity, 2),
        "total_margin": round(margin * quantity, 2),
        "max_discount_pct_at_cost": round(100 * (1 - row["unit_cost"] / row["list_price"]), 1),
        "allowed": unit_price >= row["unit_cost"],
        "note": "Proposal only. Not a sale, not revenue, not cash.",
    }


@mcp.tool(annotations=READ_ONLY)
def get_invoice_info(invoice_id: int) -> dict:
    """Look up one invoice with its vendor: amount, due date, status, and lead time.

    Reads the invoices and vendors tables. Use it to see whether a vendor bill
    is still unpaid and how many days the vendor needs to deliver.
    """
    with closing(connect()) as conn:
        row = conn.execute(
            """
            SELECT inv.id AS invoice_id, inv.amount, inv.due_date, inv.status,
                   inv.description, v.id AS vendor_id, v.name AS vendor_name,
                   v.specialty AS vendor_specialty, v.lead_days
            FROM invoices AS inv
            LEFT JOIN vendors AS v ON v.id = inv.vendor_id
            WHERE inv.id = ?
            """,
            (invoice_id,),
        ).fetchone()
    if row is None:
        return {"found": False, "error": f"No invoice with id={invoice_id}."}
    return {"found": True, **dict(row)}


@mcp.tool(annotations=READ_ONLY)
def list_open_invoices() -> dict:
    """List every invoice with status 'open', with vendor name and days overdue as of the shop date.

    Reads the invoices, vendors, and desk tables.
    """
    with closing(connect()) as conn:
        today = shop_today(conn)
        rows = conn.execute(
            """SELECT inv.id AS invoice_id, inv.amount, inv.due_date, inv.status, inv.description,
                      v.id AS vendor_id, v.name AS vendor_name
               FROM invoices AS inv LEFT JOIN vendors AS v ON v.id = inv.vendor_id
               WHERE inv.status = 'open' ORDER BY inv.due_date"""
        ).fetchall()
    invoices = []
    for r in rows:
        overdue = days_between(r["due_date"], today)
        invoices.append({**dict(r), "days_overdue": max(overdue, 0), "overdue": overdue > 0})
    return {"shop_date": today, "open_invoices": invoices, "total_open": round(sum(r["amount"] for r in rows), 2)}


@mcp.tool(annotations=READ_ONLY)
def list_vendors() -> list[dict]:
    """List all vendors (vendors table): id, name, specialty, and lead time in days."""
    with closing(connect()) as conn:
        rows = conn.execute("SELECT * FROM vendors ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@mcp.tool(annotations=READ_ONLY)
def get_vendor_status(vendor_id: int) -> dict:
    """Check whether a vendor can take a new order (vendors, invoices, and desk tables).

    Shop rule: a vendor with any unpaid (status 'open') invoice is restricted,
    whether or not it is overdue, so no new order may be placed with them until
    every open invoice is paid. days_overdue is shown for information only.
    """
    with closing(connect()) as conn:
        vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if vendor is None:
            return {"found": False, "error": f"No vendor with id={vendor_id}."}
        today = shop_today(conn)
        open_rows = conn.execute(
            "SELECT id, amount, due_date, description FROM invoices WHERE vendor_id = ? AND status = 'open'",
            (vendor_id,),
        ).fetchall()
    open_invoices = [
        {**dict(r), "days_overdue": max(days_between(r["due_date"], today), 0)} for r in open_rows
    ]
    return {
        "found": True,
        **dict(vendor),
        "shop_date": today,
        "open_invoices": open_invoices,
        "restricted": bool(open_invoices),
        "restriction_reason": (
            "Unpaid invoice(s): " + ", ".join(f"#{r['id']} ${r['amount']:.2f} due {r['due_date']}" for r in open_invoices)
            if open_invoices else None
        ),
    }


@mcp.tool(annotations=READ_ONLY)
def get_rent_info(lease_id: int) -> dict:
    """Look up one lease: rent amount, due date, days until due, rent payments made, and checking balance.

    Reads the leases, payments, cash_accounts, and desk tables. days_until_due is
    next_due minus the shop date (desk.date_today); negative means past due.
    Payments count as rent for this lease when kind is 'rent' or 'lease' and
    ref_id is the lease id.
    """
    with closing(connect()) as conn:
        lease = conn.execute(
            "SELECT * FROM leases WHERE id = ?", (lease_id,)
        ).fetchone()
        if lease is None:
            return {"found": False, "error": f"No lease with id={lease_id}."}
        payments = conn.execute(
            """
            SELECT * FROM payments
            WHERE ref_id = ? AND LOWER(kind) IN ('rent', 'lease')
            ORDER BY paid_at
            """,
            (lease_id,),
        ).fetchall()
        checking = conn.execute(
            "SELECT name, balance, date FROM cash_accounts WHERE name = 'checking'"
        ).fetchone()
        today = shop_today(conn)
    return {
        "found": True,
        "lease_id": lease["id"],
        "space_name": lease["space_name"],
        "landlord": lease["landlord"],
        "monthly_rent": lease["monthly_rent"],
        "next_due": lease["next_due"],
        "shop_date": today,
        "days_until_due": days_between(today, lease["next_due"]),
        "notes": lease["notes"],
        "rent_payments": [dict(p) for p in payments],
        "checking_account": dict(checking) if checking else None,
    }


@mcp.tool(annotations=READ_ONLY)
def get_cash_position() -> dict:
    """Summarize cash against known obligations (cash_accounts, invoices, leases, payments, desk tables).

    Shows each account balance, open invoices, upcoming rent, recent payments,
    and what cash would remain if every listed obligation were paid. Only money
    already in the accounts counts: no expected sales or other revenue.
    """
    with closing(connect()) as conn:
        today = shop_today(conn)
        accounts = [dict(r) for r in conn.execute("SELECT * FROM cash_accounts ORDER BY name")]
        invoices = [dict(r) for r in conn.execute(
            "SELECT id, vendor_id, amount, due_date, description FROM invoices WHERE status = 'open' ORDER BY due_date"
        )]
        leases = [dict(r) for r in conn.execute(
            "SELECT id, space_name, landlord, monthly_rent, next_due FROM leases ORDER BY next_due"
        )]
        payments = [dict(r) for r in conn.execute("SELECT * FROM payments ORDER BY paid_at DESC LIMIT 20")]
    checking = next((a for a in accounts if a["name"] == PAYMENT_ACCOUNT), None)
    for inv in invoices:
        inv["days_overdue"] = max(days_between(inv["due_date"], today), 0)
    paid_rent = {(r["ref_id"], r["due_date"]) for r in read_approvals() if r["kind"] == "rent" and r["status"] == "executed"}
    for lease in leases:
        lease["days_until_due"] = days_between(today, lease["next_due"])
        # The lease's next_due isn't moved after paying (by design); mark it paid instead of counting it again.
        lease["already_paid"] = (lease["id"], lease["next_due"]) in paid_rent
    obligations = round(sum(i["amount"] for i in invoices)
                        + sum(l["monthly_rent"] for l in leases if not l["already_paid"]), 2)
    return {
        "shop_date": today,
        "accounts": accounts,
        "checking_balance": checking["balance"] if checking else None,
        "open_invoices": invoices,
        "upcoming_rent": leases,
        "recent_payments": payments,
        "total_listed_obligations": obligations,
        "checking_after_all_obligations": round(checking["balance"] - obligations, 2) if checking else None,
        "note": "Cash on hand only. Quotes, orders, and expected sales are not counted. Rent already paid for its "
                "current due date is marked already_paid and not counted as an obligation.",
    }


# --------------------------------------------------------------------------
# Payment tools: request (no money moves), check status, execute (human-approved only)
# --------------------------------------------------------------------------

@mcp.tool
def request_payment_approval(kind: Literal["invoice", "rent"], ref_id: int, requested_by: str, reason: str,
                             ticket_id: int | None = None) -> dict:
    """Ask a human to approve one payment. This moves no money.

    The amount, payee, and due date are taken from the database (invoices or
    leases), never from the caller. The request is refused if the item isn't
    payable, if a request for it is already pending or approved, or if paying it
    would make the checking balance negative. A human must then approve it
    (dashboard or scripts/approve_payment.py) before execute_payment will run.
    ticket_id links the request to the ticket it is for.
    """
    with closing(connect()) as conn:
        target = payment_target(conn, kind, ref_id)
        if not target["found"]:
            return {"created": False, "error": target["error"]}
        if not target["payable"]:
            return {"created": False, "error": f"Not payable: {target['not_payable_reason']}."}
        checking = conn.execute("SELECT balance FROM cash_accounts WHERE name = ?", (PAYMENT_ACCOUNT,)).fetchone()
        today = shop_today(conn)
    balance = checking["balance"] if checking else 0.0
    if target["amount"] > balance:
        return {
            "created": False,
            "error": f"Refused: paying ${target['amount']:.2f} would make {PAYMENT_ACCOUNT} negative (balance ${balance:.2f}).",
        }
    with approvals_file() as records:
        for r in records:
            if r["kind"] == kind and r["ref_id"] == ref_id and r["due_date"] == target["due_date"] \
                    and r["status"] in ("pending", "approved"):
                return {"created": False, "error": f"A {r['status']} request already exists: {r['approval_id']}.",
                        "existing": r}
        record = {
            "approval_id": "PAY-" + uuid.uuid4().hex[:8].upper(),
            "status": "pending",
            "kind": kind,
            "ref_id": ref_id,
            "amount": target["amount"],
            "payee": target["payee"],
            "due_date": target["due_date"],
            "description": target["description"],
            "account": PAYMENT_ACCOUNT,
            "balance_when_requested": balance,
            "requested_by": requested_by,
            "reason": reason,
            "ticket_id": ticket_id,
            "requested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "shop_date_when_requested": today,
            "approved_by": None,
            "approved_at": None,
            "payment_id": None,
        }
        records.append(record)
    return {
        "created": True,
        **record,
        "next_step": "A human must approve this (dashboard or scripts/approve_payment.py). No money has moved.",
    }


@mcp.tool(annotations=READ_ONLY)
def list_payment_approvals(status: str | None = None) -> list[dict]:
    """List payment and purchase approval requests, optionally filtered by status
    (pending, approved, rejected, executed)."""
    records = read_approvals()
    return [r for r in records if status is None or r["status"] == status]


@mcp.tool
def request_purchase_approval(sku: str, size: str, quantity: int, vendor_id: int, requested_by: str, reason: str,
                              ticket_id: int | None = None) -> dict:
    """Ask a human to approve a restock purchase from a vendor. This places no order and moves no money.

    The unit cost comes from the pricing table and the vendor from the vendors
    table. Refused if the product/size or vendor doesn't exist, the quantity
    isn't positive, the vendor is restricted (any unpaid invoice), or a pending,
    approved, or ordered purchase for the same item and vendor already exists.
    Also returns cash_warning and duplicate_warnings (information only).
    After a human approves, a person records the order with place_purchase_order.
    """
    if quantity <= 0:
        return {"created": False, "error": "quantity must be positive."}
    with closing(connect()) as conn:
        item = conn.execute(
            """SELECT i.sku, i.name, i.size, i.qty, p.unit_cost FROM inventory AS i
               LEFT JOIN pricing AS p ON p.sku = i.sku WHERE i.sku = ? AND i.size = ?""",
            (sku.strip(), size.strip().upper()),
        ).fetchone()
        if item is None or item["unit_cost"] is None:
            return {"created": False, "error": f"No priced inventory row for sku={sku!r}, size={size!r}."}
        vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if vendor is None:
            return {"created": False, "error": f"No vendor with id={vendor_id}."}
        unpaid = conn.execute(
            "SELECT id, amount, due_date FROM invoices WHERE vendor_id = ? AND status = 'open'", (vendor_id,)
        ).fetchall()
        today = shop_today(conn)
        ticket = _ticket(conn, ticket_id) if ticket_id is not None else None
        link = linked_invoice(conn, ticket) if ticket is not None else None
    estimated_cost = round(item["unit_cost"] * quantity, 2)
    with closing(connect()) as conn:
        available = cash_snapshot(conn)["available_after_commitments"]
    for prev in read_approvals():
        if not (prev["kind"] == PURCHASE_KIND and prev["status"] == "rejected" and prev.get("ticket_id") == ticket_id
                and prev.get("sku") == item["sku"] and prev.get("size") == item["size"]):
            continue
        # Relevant change since the human rejection: cash now covers it, or a newer customer response was recorded.
        newer_response = ticket_id is not None and any(
            e["kind"] == "customer_response" and e["recorded_at"][:19] > (prev.get("rejected_at") or "")[:19]
            for e in read_events(ticket_id))
        if available >= estimated_cost or newer_response:
            continue
        why = prev.get("rejection_reason") or "no reason recorded"
        return {"created": False, "previous_rejection": {k: prev.get(k) for k in (
                    "approval_id", "quantity", "amount", "rejected_by", "rejected_at", "rejection_reason")},
                "error": (f"Refused: {prev['rejected_by']} rejected {prev['approval_id']} ({prev['quantity']} x {prev['sku']} "
                          f"{prev['size']}, ${prev['amount']:,.2f}) on {(prev.get('rejected_at') or '')[:10]}; reason: {why}. "
                          f"Nothing relevant has changed: ${available:,.2f} available vs ${estimated_cost:,.2f} needed, and no "
                          "customer response recorded since. Report the rejection instead of requesting it again.")}
    if link and link["covers_requested_item"] and (ticket["sku"], ticket["size"]) == (item["sku"], item["size"]):
        return {"created": False, "linked_invoice": link,
                "error": (f"Refused to avoid a duplicate: ticket {ticket_id} already links to invoice {link['invoice_id']} "
                          f"('{link['description']}', {link['status']}), which is the restock for this item. Its quantity "
                          "and delivery date aren't recorded; a person should confirm with the vendor before ordering more.")}
    if unpaid:
        return {"created": False,
                "error": f"Refused: {vendor['name']} is restricted by unpaid invoice(s) "
                         + ", ".join(f"#{r['id']} ${r['amount']:.2f}" for r in unpaid) + "."}
    with approvals_file() as records:
        for r in records:
            if r["kind"] == PURCHASE_KIND and r.get("sku") == item["sku"] and r.get("size") == item["size"] \
                    and r.get("vendor_id") == vendor_id and r["status"] in ACTIVE_PURCHASE:
                return {"created": False, "error": f"A {r['status']} request already exists: {r['approval_id']}.",
                        "existing": r}
        record = {
            "approval_id": "BUY-" + uuid.uuid4().hex[:8].upper(),
            "status": "pending",
            "kind": PURCHASE_KIND,
            "ref_id": vendor_id,
            "sku": item["sku"],
            "size": item["size"],
            "product_name": item["name"],
            "quantity": quantity,
            "unit_cost": item["unit_cost"],
            "amount": round(item["unit_cost"] * quantity, 2),
            "payee": vendor["name"],
            "vendor_id": vendor_id,
            "lead_days": vendor["lead_days"],
            "due_date": None,
            "description": f"Restock {quantity} x {item['name']} ({item['size']}) from {vendor['name']}",
            "requested_by": requested_by,
            "reason": reason,
            "ticket_id": ticket_id,
            "requested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "shop_date_when_requested": today,
            "approved_by": None,
            "approved_at": None,
        }
        records.append(record)
    with closing(connect()) as conn:
        warnings = purchase_warnings(conn, record)
    return {
        "created": True,
        **record,
        **warnings,
        "next_step": "A human must approve this purchase. No order has been placed and no money has moved.",
    }



# --------------------------------------------------------------------------
# Manager actions (human-only). No agent has these tools; the backend calls
# them from dashboard routes that need a name and a typed confirmation.
# Every action is appended to output/manager_events.json and says whether it
# is simulated. None of them changes cash or invents revenue.
# --------------------------------------------------------------------------

ACTIVE_PURCHASE = ("pending", "approved", "ordered")
CUSTOMER_CHOICES = ("accept", "decline", "wait", "alternative", "partial", "other")


def _write_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _need(value: str, what: str) -> str | None:
    return None if value and value.strip() else f"{what} is required."


def cash_snapshot(conn: sqlite3.Connection, exclude_id: str | None = None) -> dict:
    """Checking balance and money already committed, each counted once.

    Committed = open (unpaid) invoices, including vendor bills created when a
    purchase is ordered + rent or other non-invoice payment requests not yet
    executed + any ordered purchase that has no bill (older records).
    """
    row = conn.execute("SELECT balance FROM cash_accounts WHERE name = ?", (PAYMENT_ACCOUNT,)).fetchone()
    balance = row["balance"] if row else 0.0
    open_invoices = round(sum(r["amount"] for r in conn.execute("SELECT amount FROM invoices WHERE status = 'open'")), 2)
    committed = open_invoices
    for r in read_approvals():
        if r["approval_id"] == exclude_id:
            continue
        if r["kind"] not in ("invoice", PURCHASE_KIND) and r["status"] in ("pending", "approved"):
            committed += r["amount"]
        elif r["kind"] == PURCHASE_KIND and r["status"] == "ordered" and not r.get("vendor_invoice_id"):
            committed += r["amount"]
    return {"checking_balance": balance, "open_invoices_total": open_invoices, "committed": round(committed, 2),
            "available_after_commitments": round(balance - committed, 2)}


def invoice_covers(inv: sqlite3.Row | dict, sku: str | None, size: str | None) -> bool:
    """True if an invoice's description names this exact SKU and size (e.g. 'Rush reprint CC-TEE-WHITE S')."""
    words = (inv["description"] or "").split()
    return bool(sku and size and sku in words and size in words)


def linked_invoice(conn: sqlite3.Connection, ticket: sqlite3.Row) -> dict | None:
    """The invoice the ticket itself links to (tickets.invoice_id), if any."""
    if not ticket["invoice_id"]:
        return None
    inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (ticket["invoice_id"],)).fetchone()
    if inv is None:
        return None
    covers = invoice_covers(inv, ticket["sku"], ticket["size"])
    return {
        "invoice_id": inv["id"], "vendor_id": inv["vendor_id"], "amount": inv["amount"], "due_date": inv["due_date"],
        "status": inv["status"], "description": inv["description"], "covers_requested_item": covers,
        "note": ("The ticket links to this invoice and it names the requested item: treat it as the restock already "
                 "in progress for this ticket. Its quantity and delivery date are not recorded; don't assume them."
                 if covers else "The ticket links to this invoice, but it doesn't name the requested item."),
    }


def purchase_warnings(conn: sqlite3.Connection, record: dict) -> dict:
    """Cash warning and possible-duplicate warnings for a purchase request (information only)."""
    cash = cash_snapshot(conn, exclude_id=record["approval_id"])
    cost = record["amount"]
    cash_warning = None
    if cost > cash["available_after_commitments"]:
        cash_warning = {
            "estimated_cost": cost, **cash,
            "shortfall": round(cost - cash["available_after_commitments"], 2),
            "message": (f"Estimated cost ${cost:,.2f} exceeds the ${cash['available_after_commitments']:,.2f} available "
                        f"(checking ${cash['checking_balance']:,.2f} minus ${cash['committed']:,.2f} already committed). "
                        "Projection only: no money moves when a purchase is approved or ordered."),
        }
    duplicates = []
    for inv in conn.execute("SELECT id, amount, status, description FROM invoices WHERE vendor_id = ?",
                            (record["vendor_id"],)):
        words = (inv["description"] or "").split()
        if record["sku"] in words and record["size"] in words:
            duplicates.append({"invoice_id": inv["id"], "amount": inv["amount"], "status": inv["status"],
                               "description": inv["description"],
                               "message": f"Invoice {inv['id']} ({inv['status']}) is '{inv['description']}' from the same "
                                          "vendor. This purchase may duplicate it; a person should check."})
    for r in read_approvals():
        if r["approval_id"] != record["approval_id"] and r["kind"] == PURCHASE_KIND and r.get("sku") == record["sku"] \
                and r.get("size") == record["size"] and r["status"] in ("ordered", "received"):
            duplicates.append({"approval_id": r["approval_id"], "status": r["status"],
                               "message": f"{r['approval_id']} for the same item is already {r['status']}."})
    return {"cash_warning": cash_warning, "duplicate_warnings": duplicates}


def _ticket(conn: sqlite3.Connection, ticket_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()


def _latest(ticket_id: int, kind: str) -> dict | None:
    events = [e for e in read_events(ticket_id) if e["kind"] == kind]
    return events[-1] if events else None


@mcp.tool(annotations=READ_ONLY)
def get_ticket_updates(ticket_id: int) -> dict:
    """Manager-recorded events and purchase/payment status for one ticket (read-only).

    Events are things a person recorded: customer responses, pricing decisions,
    purchase orders, cancellations, stock receipts, fulfilment. Each says whether
    it is simulated (no real customer or vendor in this assignment). Agents can
    read these but can't create or change them.
    """
    with closing(connect()) as conn:
        t = _ticket(conn, ticket_id)
        if t is None:
            return {"found": False, "error": f"No ticket with id={ticket_id}."}
        approvals = [r for r in read_approvals() if r.get("ticket_id") == ticket_id]
        purchases = [{**r, **purchase_warnings(conn, r)} if r["status"] in ACTIVE_PURCHASE else r
                     for r in approvals if r["kind"] == PURCHASE_KIND]
        on_hand = None
        if t["sku"]:
            row = conn.execute("SELECT qty FROM inventory WHERE sku = ? AND size = ?", (t["sku"], t["size"])).fetchone()
            on_hand = row["qty"] if row else None
        link = linked_invoice(conn, t)
        bills = []
        for r in purchases:
            if r.get("vendor_invoice_id"):
                inv = conn.execute("SELECT id, amount, due_date, status, description FROM invoices WHERE id = ?",
                                   (r["vendor_invoice_id"],)).fetchone()
                if inv:
                    bills.append({"approval_id": r["approval_id"], "invoice_id": inv["id"], "amount": inv["amount"],
                                  "due_date": inv["due_date"], "status": inv["status"], "description": inv["description"]})
        cash = cash_snapshot(conn)
    events = read_events(ticket_id)
    fulfilled = sum(e["details"]["quantity"] for e in events if e["kind"] == "fulfilment")
    open_steps = [f"{r['approval_id']} is ordered but not received (expected around {r.get('expected_arrival')})"
                  for r in purchases if r["status"] == "ordered"]
    return {
        "found": True,
        "ticket_id": ticket_id,
        "ticket_status": t["status"],
        "ticket_type": t["type"],
        "requested": {"sku": t["sku"], "size": t["size"], "qty": t["qty"]},
        "events": events,
        "latest_customer_response": _latest(ticket_id, "customer_response"),
        "latest_pricing_decision": _latest(ticket_id, "pricing_decision"),
        "purchases": purchases,
        "payments": [r for r in approvals if r["kind"] != PURCHASE_KIND],
        "quantity_fulfilled": fulfilled,
        "quantity_still_to_fulfil": max((t["qty"] or 0) - fulfilled, 0),
        "on_hand": on_hand,
        "linked_invoice": link,
        "vendor_invoices": bills,
        "rejected_purchases": [{k: r.get(k) for k in ("approval_id", "sku", "size", "quantity", "amount", "rejected_by",
                                                       "rejected_at", "rejection_reason")}
                               for r in purchases if r["status"] == "rejected"],
        "unpaid_vendor_invoices": [b for b in bills if b["status"] != "paid"] + (
            [link] if link and link["status"] != "paid" else []),
        "cash": cash,
        "open_steps": open_steps,
        "note": "Manager-recorded events are entered by a person. Campus Customs is a fictional shop: its customers "
                "and vendors exist only in this assignment, so customer and vendor events are recorded as simulated. "
                "Within this fictional shop, a labelled simulated event is a valid business event. Current stock "
                "may be 0 after fulfilment because the item was handed over; use quantity_fulfilled. A ticket is "
                "resolved when every action the shop can take now is done, required human decisions are made, and "
                "the reply is drafted; future deliveries and customer responses are follow-ups, not blockers.",
    }


@mcp.tool
def record_customer_response(ticket_id: int, choice: Literal["accept", "decline", "wait", "alternative", "partial", "other"],
                             summary: str, channel: str, recorded_by: str, simulated: bool, basis: str) -> dict:
    """Record what a customer decided (human-only). The agents never contact customers."""
    for err in (_need(summary, "summary"), _need(recorded_by, "recorded_by"), _need(basis, "basis")):
        if err:
            return {"recorded": False, "error": err}
    with closing(connect()) as conn:
        if _ticket(conn, ticket_id) is None:
            return {"recorded": False, "error": f"No ticket with id={ticket_id}."}
        today = shop_today(conn)
    event = append_event("customer_response", ticket_id=ticket_id, recorded_by=recorded_by.strip(), shop_date=today,
                         simulated=simulated, basis=basis.strip(),
                         details={"choice": choice, "summary": summary.strip(), "channel": channel.strip() or "unspecified"})
    return {"recorded": True, "event": event}


@mcp.tool
def record_pricing_decision(ticket_id: int, sku: str, size: str, quantity: int, discount_pct: float,
                            decision: Literal["approved", "declined"], recorded_by: str, note: str,
                            simulated: bool = False, basis: str = "Manager decision recorded in the dashboard") -> dict:
    """Record a person's decision on a discounted price (human-only).

    Price and margin are recalculated from the pricing table. An approved price
    below unit cost is refused (the shop never sells below cost).
    """
    for err in (_need(recorded_by, "recorded_by"), _need(basis, "basis")):
        if err:
            return {"recorded": False, "error": err}
    if quantity <= 0 or not 0 <= discount_pct < 100:
        return {"recorded": False, "error": "quantity must be positive and discount_pct between 0 and 100."}
    with closing(connect()) as conn:
        t = _ticket(conn, ticket_id)
        if t is None:
            return {"recorded": False, "error": f"No ticket with id={ticket_id}."}
        if t["sku"] != sku.strip():
            return {"recorded": False, "error": f"Ticket {ticket_id} is about {t['sku']}, not {sku}."}
        price = conn.execute("SELECT * FROM pricing WHERE sku = ?", (sku.strip(),)).fetchone()
        today = shop_today(conn)
    unit_price = round(price["list_price"] * (1 - discount_pct / 100), 2)
    if decision == "approved" and unit_price < price["unit_cost"]:
        return {"recorded": False, "error": f"Refused: ${unit_price:.2f} is below the ${price['unit_cost']:.2f} unit cost."}
    event = append_event("pricing_decision", ticket_id=ticket_id, recorded_by=recorded_by.strip(), shop_date=today,
                         simulated=simulated, basis=basis.strip(),
                         details={"decision": decision, "sku": sku.strip(), "size": size.strip().upper(),
                                  "quantity": quantity, "discount_pct": discount_pct, "list_price": price["list_price"],
                                  "unit_cost": price["unit_cost"], "unit_price": unit_price,
                                  "margin_per_unit": round(unit_price - price["unit_cost"], 2), "note": note.strip(),
                                  "revenue_recorded": False})
    return {"recorded": True, "event": event}


@mcp.tool
def place_purchase_order(approval_id: str, recorded_by: str, vendor_reference: str, acknowledge_cash_warning: bool,
                         acknowledge_duplicate_warning: bool, simulated: bool, basis: str) -> dict:
    """Record that a human-approved purchase was ordered from the vendor (human-only). approved -> ordered.

    Refused unless the request is approved, the vendor isn't restricted, no other
    order for the same item and vendor is already open, and any cash or
    possible-duplicate warning has been acknowledged. Creates an OPEN vendor
    invoice for the order (due on the expected delivery date), which makes the
    vendor restricted until it is paid through Accounting and human approval.
    No money moves now.
    """
    for err in (_need(recorded_by, "recorded_by"), _need(basis, "basis")):
        if err:
            return {"recorded": False, "error": err}
    with closing(connect()) as conn:
        today = shop_today(conn)
        with approvals_file() as records:
            r = next((x for x in records if x["approval_id"] == approval_id), None)
            if r is None or r["kind"] != PURCHASE_KIND:
                return {"recorded": False, "error": f"No purchase request {approval_id!r}."}
            if r["status"] != "approved":
                return {"recorded": False, "error": f"Refused: {approval_id} is {r['status']!r}; only an approved purchase can be ordered."}
            unpaid = conn.execute("SELECT id FROM invoices WHERE vendor_id = ? AND status = 'open'", (r["vendor_id"],)).fetchall()
            if unpaid:
                return {"recorded": False, "error": f"Refused: {r['payee']} is restricted by unpaid invoice(s)."}
            other = next((x for x in records if x["approval_id"] != approval_id and x["kind"] == PURCHASE_KIND
                          and x.get("sku") == r["sku"] and x.get("size") == r["size"]
                          and x.get("vendor_id") == r["vendor_id"] and x["status"] == "ordered"), None)
            if other:
                return {"recorded": False, "error": f"Refused: {other['approval_id']} for the same item is already ordered."}
            warnings = purchase_warnings(conn, r)
            missing = []
            if warnings["cash_warning"] and not acknowledge_cash_warning:
                missing.append("cash warning")
            if warnings["duplicate_warnings"] and not acknowledge_duplicate_warning:
                missing.append("possible-duplicate warning")
            if missing:
                return {"recorded": False, "needs_acknowledgement": missing, **warnings,
                        "error": "Acknowledge the " + " and ".join(missing) + " before recording this order."}
            arrival = (date.fromisoformat(today) + timedelta(days=r["lead_days"])).isoformat()
            # The vendor bills for the order: an OPEN invoice (amount from the approved request, i.e. pricing.unit_cost
            # x quantity), due on the expected delivery date. No money moves; it is paid later through the normal
            # Accounting -> human approval -> execute_payment flow, and the vendor is restricted until then.
            wconn = _write_conn()
            try:
                wconn.execute("BEGIN IMMEDIATE")
                invoice_id = wconn.execute(
                    "INSERT INTO invoices (vendor_id, amount, due_date, status, description) VALUES (?, ?, ?, 'open', ?)",
                    (r["vendor_id"], r["amount"], arrival,
                     f"Purchase order {approval_id}: {r['quantity']} x {r['product_name']} ({r['size']})"),
                ).lastrowid
                event = append_event("purchase_order", ticket_id=r.get("ticket_id"), recorded_by=recorded_by.strip(),
                                     shop_date=today, simulated=simulated, basis=basis.strip(),
                                     details={"sku": r["sku"], "size": r["size"], "quantity": r["quantity"],
                                              "estimated_cost": r["amount"], "vendor": r["payee"],
                                              "vendor_reference": vendor_reference.strip() or None,
                                              "expected_arrival": arrival, "vendor_invoice_id": invoice_id,
                                              "vendor_invoice_due": arrival, **warnings,
                                              "acknowledged": {"cash_warning": acknowledge_cash_warning,
                                                               "duplicate_warning": acknowledge_duplicate_warning},
                                              "cash_changed": False},
                                     refs={"approval_id": approval_id, "invoice_id": invoice_id})
                wconn.commit()
            except Exception:
                wconn.rollback()
                raise
            finally:
                wconn.close()
            r.update(status="ordered", ordered_by=recorded_by.strip(), ordered_at=event["recorded_at"],
                     order_shop_date=today, expected_arrival=arrival, order_event_id=event["event_id"],
                     order_simulated=simulated, vendor_invoice_id=invoice_id)
    return {"recorded": True, "event": event, "approval_id": approval_id, "status": "ordered", "expected_arrival": arrival,
            "vendor_invoice_id": invoice_id, "cash_changed": False}


@mcp.tool
def cancel_purchase(approval_id: str, reason: str, recorded_by: str) -> dict:
    """Cancel an approved purchase that has not been ordered (human-only). approved -> cancelled. No money moves."""
    for err in (_need(reason, "reason"), _need(recorded_by, "recorded_by")):
        if err:
            return {"recorded": False, "error": err}
    with closing(connect()) as conn:
        today = shop_today(conn)
    with approvals_file() as records:
        r = next((x for x in records if x["approval_id"] == approval_id), None)
        if r is None or r["kind"] != PURCHASE_KIND:
            return {"recorded": False, "error": f"No purchase request {approval_id!r}."}
        if r["status"] != "approved":
            return {"recorded": False, "error": f"Refused: {approval_id} is {r['status']!r}; only an approved, "
                                                "not-yet-ordered purchase can be cancelled (reject pending ones instead)."}
        event = append_event("purchase_cancelled", ticket_id=r.get("ticket_id"), recorded_by=recorded_by.strip(),
                             shop_date=today, simulated=False, basis="Manager decision recorded in the dashboard",
                             details={"reason": reason.strip(), "sku": r["sku"], "size": r["size"],
                                      "quantity": r["quantity"]},
                             refs={"approval_id": approval_id})
        r.update(status="cancelled", cancelled_by=recorded_by.strip(), cancelled_at=event["recorded_at"],
                 cancel_reason=reason.strip(), cancel_event_id=event["event_id"])
    return {"recorded": True, "event": event, "approval_id": approval_id, "status": "cancelled"}


@mcp.tool
def record_stock_receipt(sku: str, size: str, quantity: int, source_kind: Literal["purchase_order", "invoice"],
                         source_id: str, recorded_by: str, simulated: bool, basis: str,
                         ticket_id: int | None = None) -> dict:
    """Record stock arriving and add it to inventory (human-only).

    source_kind 'purchase_order': source_id is an ordered BUY-… request; the
    quantity can't exceed what was ordered, and it becomes 'received'.
    source_kind 'invoice': source_id is an invoice id (e.g. a paid reprint);
    refused while a pending, approved, or ordered purchase for the same item and
    vendor is still active, and only one receipt per invoice and item.
    No money moves and no vendor invoice is created.
    """
    for err in (_need(recorded_by, "recorded_by"), _need(basis, "basis")):
        if err:
            return {"recorded": False, "error": err}
    if quantity <= 0:
        return {"recorded": False, "error": "quantity must be positive."}
    sku, size = sku.strip(), size.strip().upper()
    conn = _write_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        today = shop_today(conn)
        if conn.execute("SELECT 1 FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone() is None:
            conn.rollback()
            return {"recorded": False, "error": f"No inventory row for {sku} {size}."}
        with approvals_file() as records:
            refs: dict = {}
            if source_kind == "purchase_order":
                r = next((x for x in records if x["approval_id"] == source_id and x["kind"] == PURCHASE_KIND), None)
                if r is None:
                    conn.rollback()
                    return {"recorded": False, "error": f"No purchase {source_id!r}."}
                if r["status"] != "ordered":
                    conn.rollback()
                    return {"recorded": False, "error": f"Refused: {source_id} is {r['status']!r}; only an ordered purchase can be received."}
                if (r["sku"], r["size"]) != (sku, size) or quantity > r["quantity"]:
                    conn.rollback()
                    return {"recorded": False, "error": f"Refused: {source_id} was for {r['quantity']} x {r['sku']} {r['size']}."}
                refs = {"approval_id": source_id}
                ticket_id = ticket_id or r.get("ticket_id")
            else:
                try:
                    inv_id = int(source_id)
                except ValueError:
                    conn.rollback()
                    return {"recorded": False, "error": "source_id must be an invoice id for source_kind 'invoice'."}
                inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (inv_id,)).fetchone()
                if inv is None:
                    conn.rollback()
                    return {"recorded": False, "error": f"No invoice {inv_id}."}
                active = [x["approval_id"] for x in records if x["kind"] == PURCHASE_KIND and x.get("sku") == sku
                          and x.get("size") == size and x.get("vendor_id") == inv["vendor_id"] and x["status"] in ACTIVE_PURCHASE]
                if active:
                    conn.rollback()
                    return {"recorded": False, "error": f"Refused to avoid a duplicate: {', '.join(active)} for the same item "
                                                        "and vendor is still active. Cancel or reject it first if invoice "
                                                        f"{inv_id} covers this stock."}
                if any(e["kind"] == "stock_receipt" and e["refs"].get("invoice_id") == inv_id
                       and e["details"]["sku"] == sku and e["details"]["size"] == size for e in read_events()):
                    conn.rollback()
                    return {"recorded": False, "error": f"Refused: a receipt for {sku} {size} against invoice {inv_id} is already recorded."}
                refs = {"invoice_id": inv_id}
            conn.execute("UPDATE inventory SET qty = qty + ? WHERE sku = ? AND size = ?", (quantity, sku, size))
            new_qty = conn.execute("SELECT qty FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone()["qty"]
            event = append_event("stock_receipt", ticket_id=ticket_id, recorded_by=recorded_by.strip(), shop_date=today,
                                 simulated=simulated, basis=basis.strip(),
                                 details={"sku": sku, "size": size, "quantity": quantity, "source_kind": source_kind,
                                          "qty_after": new_qty, "cash_changed": False}, refs=refs)
            if source_kind == "purchase_order":
                r.update(status="received", received_qty=quantity, received_at=event["recorded_at"],
                         received_event_id=event["event_id"])
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"recorded": True, "event": event, "qty_after": new_qty}


@mcp.tool
def record_fulfilment(ticket_id: int, sku: str, size: str, quantity: int, recorded_by: str, simulated: bool,
                      basis: str) -> dict:
    """Record handing an order to the customer and remove it from inventory (human-only).

    Requires a recorded customer response (not 'decline'); a size other than the
    ticket's needs the customer's recorded 'alternative' choice; a price request
    needs a recorded pricing decision. Total fulfilled can't exceed the ticket's
    quantity, and stock can't go below zero. No revenue is recorded.
    """
    for err in (_need(recorded_by, "recorded_by"), _need(basis, "basis")):
        if err:
            return {"recorded": False, "error": err}
    if quantity <= 0:
        return {"recorded": False, "error": "quantity must be positive."}
    sku, size = sku.strip(), size.strip().upper()
    conn = _write_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        t = _ticket(conn, ticket_id)
        if t is None or not t["sku"]:
            conn.rollback()
            return {"recorded": False, "error": f"Ticket {ticket_id} has no product to fulfil."}
        if sku != t["sku"]:
            conn.rollback()
            return {"recorded": False, "error": f"Ticket {ticket_id} is for {t['sku']}, not {sku}."}
        response = _latest(ticket_id, "customer_response")
        if response is None:
            conn.rollback()
            return {"recorded": False, "error": "Refused: record the customer's response before fulfilment."}
        if response["details"]["choice"] == "decline":
            conn.rollback()
            return {"recorded": False, "error": "Refused: the latest recorded customer response is 'decline'."}
        if size != t["size"] and response["details"]["choice"] != "alternative":
            conn.rollback()
            return {"recorded": False, "error": f"Refused: the ticket asks for size {t['size']}; a different size needs the "
                                                "customer's recorded 'alternative' choice."}
        if t["type"] == "price_override" and _latest(ticket_id, "pricing_decision") is None:
            conn.rollback()
            return {"recorded": False, "error": "Refused: record the pricing decision for this price request first."}
        done = sum(e["details"]["quantity"] for e in read_events(ticket_id) if e["kind"] == "fulfilment")
        if done + quantity > (t["qty"] or 0):
            conn.rollback()
            return {"recorded": False, "error": f"Refused: {done} of {t['qty']} already fulfilled; {quantity} more would exceed the order."}
        updated = conn.execute("UPDATE inventory SET qty = qty - ? WHERE sku = ? AND size = ? AND qty >= ?",
                               (quantity, sku, size, quantity)).rowcount
        if updated != 1:
            conn.rollback()
            return {"recorded": False, "error": f"Refused: not enough {sku} {size} in stock."}
        new_qty = conn.execute("SELECT qty FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone()["qty"]
        today = shop_today(conn)
        event = append_event("fulfilment", ticket_id=ticket_id, recorded_by=recorded_by.strip(), shop_date=today,
                             simulated=simulated, basis=basis.strip(),
                             details={"sku": sku, "size": size, "quantity": quantity, "qty_after": new_qty,
                                      "fulfilled_total": done + quantity, "ordered_qty": t["qty"],
                                      "revenue_recorded": False, "cash_changed": False})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"recorded": True, "event": event, "qty_after": new_qty, "fulfilled_total": done + quantity}


@mcp.tool
def set_ticket_status(ticket_id: int, status: Literal["open", "resolved"]) -> dict:
    """Set a ticket's status (tickets table). Used by the backend only; no agent has this tool."""
    conn = sqlite3.connect(DB_PATH)
    try:
        with conn:
            changed = conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id)).rowcount
    finally:
        conn.close()
    if changed != 1:
        return {"updated": False, "error": f"No ticket with id={ticket_id}."}
    return {"updated": True, "ticket_id": ticket_id, "status": status}


@mcp.tool
def execute_payment(approval_id: str) -> dict:
    """Pay one human-approved payment request from checking.

    Runs only if a human approved this exact request (dashboard or
    scripts/approve_payment.py). Amount and target come from the approved record
    and are re-checked against the database. Refused if the balance would go
    negative, the item is no longer payable, or the request was already used.
    On success it adds a payments row, lowers the checking balance, and marks a
    paid invoice as 'paid', all in one transaction.
    """
    with approvals_file() as records:
        record = next((r for r in records if r["approval_id"] == approval_id), None)
        if record is None:
            return {"executed": False, "error": f"No approval request {approval_id!r}."}
        if record["status"] != "approved" or not record.get("approved_by") or not record.get("approved_at"):
            return {"executed": False,
                    "error": f"Refused: request {approval_id} is {record['status']!r}, not approved by a human."}

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            target = payment_target(conn, record["kind"], record["ref_id"])
            if not target["found"] or not target["payable"]:
                conn.rollback()
                return {"executed": False,
                        "error": f"Refused: no longer payable ({target.get('not_payable_reason') or target.get('error')})."}
            if abs(target["amount"] - record["amount"]) > 0.005 or target["due_date"] != record["due_date"]:
                conn.rollback()
                return {"executed": False, "error": "Refused: database amount or due date no longer matches the approval."}
            updated = conn.execute(
                "UPDATE cash_accounts SET balance = balance - ? WHERE name = ? AND balance >= ?",
                (record["amount"], record["account"], record["amount"]),
            ).rowcount
            if updated != 1:
                conn.rollback()
                return {"executed": False, "error": f"Refused: {record['account']} balance would go negative."}
            paid_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            payment_id = conn.execute(
                "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, ?, ?, ?)",
                (record["kind"], record["ref_id"], record["amount"], record["account"], paid_at, record["approved_by"]),
            ).lastrowid
            if record["kind"] == "invoice":
                conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ? AND status = 'open'", (record["ref_id"],))
            balance = conn.execute("SELECT balance FROM cash_accounts WHERE name = ?", (record["account"],)).fetchone()[0]
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        record.update(status="executed", payment_id=payment_id, executed_at=paid_at)
    return {"executed": True, "approval_id": approval_id, "payment_id": payment_id, "kind": record["kind"],
            "ref_id": record["ref_id"], "amount": record["amount"], "account": record["account"],
            "approved_by": record["approved_by"], "balance_after": balance}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Campus Customs MCP server")
    parser.add_argument("--http", action="store_true", help="serve over HTTP instead of stdio")
    args = parser.parse_args()
    if args.http:
        mcp.run(transport="http", host="127.0.0.1", port=8002, show_banner=False)
    else:
        mcp.run(show_banner=False)
