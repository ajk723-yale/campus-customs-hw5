"""FastAPI backend tests (backend/main.py) on scratch copies, with no model calls.

The app and its MCP server point at temp copies of the database, approvals
file, and audit trail, so the real data is never touched. `run_team` is
replaced by a scripted stand-in (no gpt-6-luna calls), because these tests check
the API plumbing: routes, approvals, payment execution, ticket status, reset.
The agents themselves are tested in tests/check_agents_live.py.

Run:  .venv/bin/python tests/test_api.py
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REAL_DB = ROOT / "data" / "campus_customs_new.db"
ORIGINAL = ROOT / "data" / "campus_customs.db"
TMP = Path(tempfile.mkdtemp(prefix="campus_api_test_"))
shutil.copy(ORIGINAL, TMP / "original.db")
shutil.copy(ORIGINAL, TMP / "working.db")
os.environ.update(
    CAMPUS_DB_PATH=str(TMP / "working.db"),
    CAMPUS_ORIGINAL_DB_PATH=str(TMP / "original.db"),
    CAMPUS_APPROVALS_PATH=str(TMP / "approvals.json"),
    CAMPUS_AUDIT_PATH=str(TMP / "audit.json"),
    CAMPUS_APPROVALS_ARCHIVE_DIR=str(TMP / "archive"),
    CAMPUS_MANAGER_EVENTS_PATH=str(TMP / "manager_events.json"),
)
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402  (imported the same way uvicorn does: `main:app` from backend/)
from backend import audit  # noqa: E402
from backend.models import AccountingReport, BossDecision, PaymentForHumanApproval, TicketDecision  # noqa: E402

PASSED: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise AssertionError(f"FAILED: {name} {detail}")
    PASSED.append(name)
    print(f"  ok  {name}")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


RUN_COUNT: dict[int, int] = {}


def decision(ticket_id, resolution, *, status="proposed", remaining=(), pays=(), payments=()):
    return BossDecision(summary=f"Decision for {ticket_id}", ticket_decisions=[TicketDecision(
        ticket_id=ticket_id, priority=1, decision=f"Plan for {ticket_id}", owner="boss", status=status,
        resolution=resolution, remaining_actions=list(remaining), resolves_when_payments_executed=list(pays))],
        payments_needing_human_approval=list(payments))


async def fake_run_team(task, *, team, run_id, ticket_id=None, entry_agent="boss", human_approved_payment_ids=()):
    """Scripted stand-in for the agent team. Uses the real MCP tools for any action, like Accounting would."""
    approved = list(human_approved_payment_ids)
    audit.record("run_started", run_id=run_id, agent=entry_agent, depth=0, task=task, ticket_id=ticket_id,
                 human_approved_payment_ids=approved)
    RUN_COUNT[ticket_id] = RUN_COUNT.get(ticket_id, 0) + 1
    if entry_agent == "accounting":
        result = await main.mcp("execute_payment", approval_id=approved[0])
        audit.record("payment_executed" if result.get("executed") else "payment_refused", run_id=run_id,
                     agent="accounting", depth=0, approval_id=approved[0], result=result)
        output = AccountingReport(summary="Executed the approved payment.", cash_available=3400,
                                  cash_after_plan=3400, payments_executed=[approved[0]] if result.get("executed") else [])
    elif ticket_id == 102:
        # Accounting files the rent request; paying it is the only thing left.
        req = await main.mcp("request_payment_approval", kind="rent", ref_id=1, requested_by="accounting_agent",
                             reason="rent due in 2 days", ticket_id=102)
        output = decision(102, "awaiting_human", status="awaiting_human_approval", pays=[req["approval_id"]],
                          payments=[PaymentForHumanApproval(kind="rent", ref_id=1, payee="Elm City Properties",
                                                            amount=2400, reason="due", approval_id=req["approval_id"])])
    elif ticket_id == 101 and RUN_COUNT[101] == 1:
        # Accounting files invoice 501; paying it does NOT finish the ticket (the tee is still out of stock).
        req = await main.mcp("request_payment_approval", kind="invoice", ref_id=501, requested_by="accounting_agent",
                             reason="unblock the reprint vendor", ticket_id=101)
        output = decision(101, "open", status="awaiting_human_approval",
                          remaining=["Reorder CC-TEE-WHITE S once invoice 501 is paid", "Reply to Tauhid Zaman"],
                          payments=[PaymentForHumanApproval(kind="invoice", ref_id=501, payee="Bulldog Print Co",
                                                            amount=840, reason="unblock", approval_id=req["approval_id"])])
    elif ticket_id == 101:
        # Re-run after the payment and purchase: the Boss judges the ticket handled.
        output = decision(101, "resolved", status="no_action")
    else:
        # 103: discount needs a human sign-off that isn't an approval request; stays open.
        output = decision(ticket_id, "open", remaining=["Human sign-off on a 10% discount for 8 hoodies"])
    audit.record("agent_finished", run_id=run_id, agent=entry_agent, depth=0, output=output)
    audit.record("run_finished", run_id=run_id, agent=entry_agent, depth=0, usage={}, delegations=0)
    return run_id, output


def wait_for(client: TestClient, run_id: str) -> dict:
    for _ in range(100):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not finish")


def main_test() -> None:
    real_before = sha(REAL_DB)
    main.run_team = fake_run_team
    with TestClient(main.app) as c:
        def portal_call(fn, *args, **kwargs):
            return c.portal.call(functools.partial(fn, *args, **kwargs))

        def approve(approval_id, who="Test Human"):
            return c.post(f"/api/approvals/{approval_id}/approve",
                          json={"approver": who, "confirm_approval_id": approval_id})

        print("read routes")
        h = c.get("/api/health").json()
        check("health ok, gpt-6-luna, 24 MCP tools", h["status"] == "ok" and h["model"] == "gpt-6-luna"
              and h["mcp_tools"] == 24, h)
        tickets = c.get("/api/tickets").json()
        check("3 tickets, all open, 'not run yet'", [(t["id"], t["status"]) for t in tickets]
              == [(101, "open"), (102, "open"), (103, "open")] and all("Not run yet" in t["next_step"] for t in tickets),
              tickets)
        check("unknown ticket 404", c.get("/api/tickets/999").status_code == 404)
        check("cash: checking 3400", c.get("/api/cash").json()["balance"] == 3400.0)
        check("no approvals yet", c.get("/api/approvals").json() == [])
        check("CORS allows the React dev server", c.options("/api/tickets", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}).headers.get(
            "access-control-allow-origin") == "http://localhost:5173")

        print("ticket 103: finished run with remaining work stays open")
        r = c.post("/api/tickets/103/run")
        check("run returns 202 with a run_id", r.status_code == 202 and r.json()["run_id"].startswith("run-"), r.text)
        run = wait_for(c, r.json()["run_id"])
        check("run finished with the Boss decision", run["status"] == "finished" and run["output"]["summary"])
        t103 = c.get("/api/tickets/103").json()
        check("finished run != resolved: 103 open, remaining action shown", t103["status"] == "open"
              and t103["resolution"] == "open" and "discount" in t103["next_step"], t103)
        ev = c.get("/api/events", params={"ticket_id": 103}).json()
        check("events for ticket 103 include the run and the decision", any(e["event"] == "run_started" for e in ev)
              and any(e["category"] == "message" for e in ev), ev)

        print("ticket 102: payment is the only remaining action -> resolved after execution")
        wait_for(c, c.post("/api/tickets/102/run").json()["run_id"])
        t102 = c.get("/api/tickets/102").json()
        check("102 open, waiting for a human", t102["status"] == "open" and t102["pending_approvals"] == 1
              and "Waiting for a human decision" in t102["next_step"], t102)
        pay = c.get("/api/approvals", params={"ticket_id": 102}).json()[0]
        check("rent request filed by Accounting ($2400, from DB)", pay["amount"] == 2400
              and pay["requested_by"] == "accounting_agent", pay)
        bad = c.post(f"/api/approvals/{pay['approval_id']}/approve", json={"approver": "Kohei", "confirm_approval_id": "x"})
        check("approve without the right confirmation -> 400", bad.status_code == 400, bad.text)
        check("approve without a name -> 422", c.post(f"/api/approvals/{pay['approval_id']}/approve",
              json={"approver": "", "confirm_approval_id": pay["approval_id"]}).status_code == 422)
        ok = approve(pay["approval_id"]).json()
        check("payment approval starts Accounting execution; approving itself moves no money",
              ok["execution_run_id"] and ok["effects"]["payment_execution_started"]
              and ok["effects"]["cash_changed_now"] is False and ok["effects"]["order_placed"] is False, ok)
        wait_for(c, ok["execution_run_id"])
        check("payment executed, cash 3400 -> 1000", c.get("/api/cash").json()["balance"] == 1000.0)
        check("102 resolved: the Boss named this payment as the only thing left",
              c.get("/api/tickets/102").json()["status"] == "resolved")
        check("resolved ticket can't be re-run (409)", c.post("/api/tickets/102/run").status_code == 409)
        check("approved request can't be approved again (409)", approve(pay["approval_id"]).status_code == 409)

        print("ticket 101: paying invoice 501 does NOT resolve it (tee still out of stock)")
        wait_for(c, c.post("/api/tickets/101/run").json()["run_id"])
        inv = c.get("/api/approvals", params={"ticket_id": 101}).json()[0]
        check("invoice 501 request filed by Accounting, not the backend",
              inv["requested_by"] == "accounting_agent" and inv["amount"] == 840, inv)
        wait_for(c, approve(inv["approval_id"]).json()["execution_run_id"])
        t101 = c.get("/api/tickets/101").json()
        check("invoice 501 paid (cash 1000 -> 160)", c.get("/api/cash").json()["balance"] == 160.0)
        check("101 still open after the payment, with remaining actions",
              t101["status"] == "open" and "Reorder CC-TEE-WHITE S" in t101["next_step"], t101)

        print("purchase approval only records the decision")
        dup = portal_call(main.mcp, "request_purchase_approval", sku="CC-TEE-WHITE", size="S", quantity=5,
                          vendor_id=1, requested_by="inventory_agent", reason="reprint", ticket_id=101)
        check("purchase for ticket 101's item refused: its linked invoice 501 is the restock", dup["created"] is False
              and dup["linked_invoice"]["invoice_id"] == 501, dup)
        buy = portal_call(main.mcp, "request_purchase_approval", sku="CC-TEE-WHITE", size="S", quantity=5,
                          vendor_id=1, requested_by="inventory_agent", reason="general restock", ticket_id=None)
        check("an unlinked purchase is allowed (5 x $8) with a possible-duplicate warning",
              buy["created"] and buy["amount"] == 40.0 and buy["duplicate_warnings"], buy)
        b = approve(buy["approval_id"]).json()
        check("purchase approval: recorded only, no order, no cash or inventory change, no execution run",
              b["approval"]["status"] == "approved" and b["execution_run_id"] is None
              and b["effects"] == {"decision_recorded": True, "payment_execution_started": False,
                                   "order_placed": False, "cash_changed_now": False, "inventory_changed": False}
              and "only records the decision" in b["message"], b)
        check("cash unchanged by the purchase approval", c.get("/api/cash").json()["balance"] == 160.0)
        check("tee stock unchanged (still 0)",
              portal_call(main.mcp, "get_product_info", sku="CC-TEE-WHITE", size="S")["qty"] == 0)
        check("purchase approval alone doesn't resolve 101", c.get("/api/tickets/101").json()["status"] == "open")
        wait_for(c, c.post("/api/tickets/101/run").json()["run_id"])
        check("101 resolved only when the Boss's re-run says so", c.get("/api/tickets/101").json()["status"] == "resolved")

        print("rejection keeps the ticket open")
        buy2 = portal_call(main.mcp, "request_purchase_approval", sku="CC-HOOD-NAVY", size="M", quantity=12,
                           vendor_id=1, requested_by="inventory_agent", reason="bulk order", ticket_id=103)
        rj = c.post(f"/api/approvals/{buy2['approval_id']}/reject",
                    json={"approver": "Test Human", "confirm_approval_id": buy2["approval_id"], "reason": "Cash too low"}).json()
        check("rejection reason stored and shown in the activity text", rj["approval"]["rejection_reason"] == "Cash too low"
              and any(e["event"] == "approval_rejected" and e["text"].endswith(": Cash too low")
                      for e in c.get("/api/events", params={"limit": 2000}).json()), rj)
        t103 = c.get("/api/tickets/103").json()
        check("reject: nothing ordered or paid", rj["approval"]["status"] == "rejected"
              and rj["effects"]["order_placed"] is False and c.get("/api/cash").json()["balance"] == 160.0, rj)
        check("103 stays open and asks for a re-run", t103["status"] == "open" and "rejected" in t103["next_step"], t103)
        refused = portal_call(main.mcp, "request_purchase_approval", sku="CC-MUG-CREST", size="OS", quantity=5,
                              vendor_id=9, requested_by="inventory_agent", reason="x")
        check("purchase from an unknown vendor refused", refused["created"] is False, refused)

        print("manager actions (human-only routes)")
        M = {"recorded_by": "Test Human", "simulated": True, "basis": "Simulated for a test"}
        u = c.get("/api/tickets/103/updates").json()
        check("ticket updates route", u["found"] and u["events"] == [] and u["quantity_still_to_fulfil"] == 20, u)
        check("updates for an unknown ticket -> 404", c.get("/api/tickets/999/updates").status_code == 404)
        r = c.post("/api/tickets/103/customer-response", json={**M, "confirm": "1", "choice": "partial", "summary": "8 now"})
        check("customer response needs the ticket ID typed (400)", r.status_code == 400, r.text)
        r = c.post("/api/tickets/103/customer-response", json={**M, "basis": "", "confirm": "103", "choice": "partial", "summary": "8 now"})
        check("customer response needs a basis (422)", r.status_code == 422, r.text)
        r = c.post("/api/tickets/103/customer-response", json={**M, "confirm": "103", "choice": "partial",
                                                               "summary": "Takes the 8 in stock now", "channel": "simulated"})
        ok = r.json()
        check("customer response recorded, labelled simulated, nothing sent, cash unchanged", r.status_code == 200
              and ok["event"]["simulated"] and ok["message"].startswith("Recorded (simulated).")
              and ok["effects"] == {"cash_changed": False, "message_sent": False, "inventory_changed": False}, ok)
        t103 = c.get("/api/tickets/103").json()
        check("103 stays open and asks for a re-run after a manager event", t103["status"] == "open"
              and "Run the team again" in t103["next_step"], t103["next_step"])
        r = c.post("/api/tickets/103/fulfilment", json={**M, "confirm": "103", "sku": "CC-HOOD-NAVY", "size": "M", "quantity": 8})
        check("fulfilment before a pricing decision refused (409)", r.status_code == 409 and "pricing" in r.text, r.text)
        r = c.post("/api/tickets/103/pricing-decision", json={**M, "simulated": False, "confirm": "103", "sku": "CC-HOOD-NAVY",
                                                              "size": "M", "quantity": 8, "discount_pct": 10, "decision": "approved"})
        check("pricing decision recorded ($52.20, not simulated, no revenue)", r.status_code == 200
              and r.json()["event"]["details"]["unit_price"] == 52.2 and r.json()["event"]["simulated"] is False, r.text)
        r = c.post("/api/tickets/103/fulfilment", json={**M, "confirm": "103", "sku": "CC-HOOD-NAVY", "size": "M", "quantity": 8})
        check("fulfil 8: stock 8 -> 0, cash unchanged", r.status_code == 200 and r.json()["effects"]["qty_after"] == 0
              and c.get("/api/cash").json()["balance"] == 160.0, r.text)
        r = c.post("/api/tickets/103/fulfilment", json={**M, "confirm": "103", "sku": "CC-HOOD-NAVY", "size": "M", "quantity": 1})
        check("no stock left: further fulfilment refused (409)", r.status_code == 409, r.text)
        # purchases: the approved tee-S purchase (5 x CC-TEE-WHITE S) from the purchases section
        r = c.post(f"/api/approvals/{buy['approval_id']}/place-order", json={**M, "confirm": buy["approval_id"]})
        check("ordering a possible duplicate of invoice 501 needs acknowledgement (409 + warning)", r.status_code == 409
              and r.json()["detail"]["needs_acknowledgement"] == ["possible-duplicate warning"]
              and r.json()["detail"]["duplicate_warnings"][0]["invoice_id"] == 501, r.text)
        r = c.post(f"/api/approvals/{buy['approval_id']}/place-order",
                   json={**M, "confirm": buy["approval_id"], "acknowledge_duplicate_warning": True})
        check("place order once acknowledged; an open vendor invoice is created, cash unchanged", r.status_code == 200
              and r.json()["effects"]["purchase_status"] == "ordered" and r.json()["effects"]["vendor_invoice_created"]
              and c.get("/api/cash").json()["balance"] == 160.0, r.text)
        r = c.post(f"/api/approvals/{buy['approval_id']}/place-order",
                   json={**M, "confirm": buy["approval_id"], "acknowledge_duplicate_warning": True})
        check("ordering twice refused (409)", r.status_code == 409, r.text)
        rec = {**M, "sku": "CC-TEE-WHITE", "size": "S", "quantity": 5, "source_kind": "purchase_order", "source_id": buy["approval_id"]}
        check("receipt needs the source ID typed (400)", c.post("/api/inventory/receipts", json={**rec, "confirm": "x"}).status_code == 400)
        r = c.post("/api/inventory/receipts", json={**rec, "confirm": buy["approval_id"]})
        check("stock receipt: +5 tees, no vendor invoice, cash unchanged", r.status_code == 200
              and r.json()["effects"]["qty_after"] == 5 and r.json()["effects"]["vendor_invoice_created"] is False
              and c.get("/api/cash").json()["balance"] == 160.0, r.text)
        check("receiving twice refused (409)", c.post("/api/inventory/receipts", json={**rec, "confirm": buy["approval_id"]}).status_code == 409)
        big = portal_call(main.mcp, "request_purchase_approval", sku="CC-HAT-BLUE", size="OS", quantity=40, vendor_id=3,
                          requested_by="inventory_agent", reason="test", ticket_id=None)
        check("purchase over available cash carries a cash warning", big["created"] and big["cash_warning"]["shortfall"] > 0, big)
        approve(big["approval_id"])
        r = c.post(f"/api/approvals/{big['approval_id']}/place-order", json={**M, "confirm": big["approval_id"]})
        check("ordering it without acknowledging the cash warning refused (409 + warning)", r.status_code == 409
              and "cash warning" in r.json()["detail"]["needs_acknowledgement"], r.text)
        r = c.post(f"/api/approvals/{big['approval_id']}/cancel", json={"recorded_by": "Test Human", "confirm": big["approval_id"],
                                                                         "reason": "Too expensive right now"})
        check("cancel the approved, unordered purchase", r.status_code == 200 and r.json()["effects"]["purchase_status"] == "cancelled", r.text)
        main.state.active_run = "run-busy"
        r = c.post("/api/tickets/103/customer-response", json={**M, "confirm": "103", "choice": "other", "summary": "x"})
        check("manager actions refused while an agent run is active (409)", r.status_code == 409, r.text)
        main.state.active_run = None
        ev = c.get("/api/events", params={"limit": 2000}).json()
        mev = [e for e in ev if e["category"] == "manager"]
        check("every manager action is in the audit trail as a 'manager' event", len(mev) == 6
              and all(e["agent"] is None and e["details"]["by"] == "Test Human" for e in mev), [e["event"] for e in mev])
        check("simulated manager events say so in the activity text", any(e["text"].startswith("Manager recorded (simulated)") for e in mev))

        print("one run at a time")
        main.state.active_run = "run-busy"
        check("run while another is active -> 409", c.post("/api/tickets/103/run").status_code == 409)
        check("reset while a run is active -> 409", c.post("/api/reset", json={"confirm": "RESET"}).status_code == 409)
        main.state.active_run = None

        print("events and reset")
        ev = c.get("/api/events", params={"limit": 500}).json()
        cats = {e["category"] for e in ev}
        check("events cover runs, messages, approvals, payments", {"run", "message", "approval", "payment"} <= cats, cats)
        check("no backend-filed requests anywhere", not any(
            (e["details"].get("result") or {}).get("requested_by") == "boss_decision" for e in ev))
        check("reset needs the word RESET (422)", c.post("/api/reset", json={"confirm": "yes"}).status_code == 422)
        rs = c.post("/api/reset", json={"confirm": "RESET"}).json()
        check("reset restores the original database", sha(TMP / "working.db") == sha(TMP / "original.db"), rs)
        check("approvals archived", rs["approvals_archived_to"] and Path(rs["approvals_archived_to"]).exists()
              and c.get("/api/approvals").json() == [], rs)
        check("after reset: all tickets open, cash 3400, no runs",
              [t["status"] for t in c.get("/api/tickets").json()] == ["open"] * 3
              and c.get("/api/cash").json()["balance"] == 3400.0 and c.get("/api/runs").json() == [])
        check("audit trail kept across the reset", len(json.loads((TMP / "audit.json").read_text())) > 10
              and any(e["event"] == "database_reset" for e in json.loads((TMP / "audit.json").read_text())))

    check("real campus_customs_new.db unchanged", sha(REAL_DB) == real_before)
    shutil.rmtree(TMP)
    print(f"\n{len(PASSED)} checks passed")


if __name__ == "__main__":
    try:
        main_test()
    except AssertionError as e:
        print(e)
        sys.exit(1)
