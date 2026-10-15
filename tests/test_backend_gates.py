"""Backend safety gates, tested without calling the model.

Checks the MCP call hook (per-agent tool access, the execute_payment gate) and
the delegation limits (allowed targets, no loops, max depth, max count). Uses a
scratch audit file, so output/audit_trail.json isn't touched.

Run:  .venv/bin/python tests/test_backend_gates.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
AUDIT = Path(tempfile.mkdtemp(prefix="campus_gate_test_")) / "audit.json"
os.environ["CAMPUS_AUDIT_PATH"] = str(AUDIT)

from pydantic import ValidationError  # noqa: E402
from pydantic_ai import ModelRetry  # noqa: E402

from backend.agents import CampusTeam, _validate  # noqa: E402
from backend.config import MAX_DELEGATIONS_PER_RUN  # noqa: E402
from backend.mcp_client import MANAGER_TOOLS, audited_call  # noqa: E402
from backend.models import (  # noqa: E402
    BossDecision, FacilitiesReport, PaymentForHumanApproval, RentObligation, ReplenishmentPlan, TeamDeps,
    TicketDecision, ToolObservation,
)

PASSED: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise AssertionError(f"FAILED: {name} {detail}")
    PASSED.append(name)
    print(f"  ok  {name}")


async def main() -> None:
    calls: list[str] = []

    async def fake_call_tool(name, args, **_):
        calls.append(name)
        return {"executed": True, "approval_id": args.get("approval_id"), "amount": 1.0}

    def ctx(agent, approved=(), depth=0, path=()):
        return SimpleNamespace(deps=TeamDeps(run_id="test", agent=agent, depth=depth, path=path,
                                             human_approved_payment_ids=frozenset(approved)))

    print("MCP call hook")
    r = await audited_call(ctx("boss"), fake_call_tool, "execute_payment", {"approval_id": "PAY-1"})
    check("boss can't call execute_payment", "error" in r and not calls, r)
    r = await audited_call(ctx("customer_service"), fake_call_tool, "request_payment_approval", {})
    check("customer service can't request payments", "error" in r and not calls, r)
    r = await audited_call(ctx("accounting"), fake_call_tool, "execute_payment", {"approval_id": "PAY-1"})
    check("accounting blocked without human authorization for this run", r["executed"] is False and not calls, r)
    r = await audited_call(ctx("accounting", approved=["PAY-2"]), fake_call_tool, "execute_payment",
                           {"approval_id": "PAY-1"})
    check("accounting blocked for a different approval ID", r["executed"] is False and not calls, r)
    r = await audited_call(ctx("accounting", approved=["PAY-1"]), fake_call_tool, "execute_payment",
                           {"approval_id": "PAY-1"})
    check("authorized ID reaches the MCP server (which re-checks approval)", calls == ["execute_payment"], r)

    calls.clear()
    for agent in ("boss", "inventory", "accounting", "facilities", "customer_service"):
        for tool in sorted(MANAGER_TOOLS):
            r = await audited_call(ctx(agent), fake_call_tool, tool, {"ticket_id": 101})
            assert "error" in r and not calls, (agent, tool, r)
    check(f"no agent can call any of the {len(MANAGER_TOOLS)} human-only tools (ticket status, manager actions)", True)
    r = await audited_call(ctx("boss"), fake_call_tool, "get_ticket_updates", {"ticket_id": 101})
    check("agents can read manager events (get_ticket_updates)", calls == ["get_ticket_updates"], r)
    calls.clear()
    r = await audited_call(ctx("customer_service"), fake_call_tool, "request_purchase_approval", {})
    check("only Inventory may request purchases (customer service blocked)", "error" in r and not calls, r)
    r = await audited_call(ctx("inventory", ), fake_call_tool, "request_purchase_approval", {"sku": "X"})
    check("Inventory's purchase request reaches MCP", calls == ["request_purchase_approval"], r)
    calls.clear()

    print("delegation limits")
    team = CampusTeam()  # agents built, MCP not started; refusals never run a model
    r = await team.delegate(ctx("facilities"), "inventory", "x", [])
    check("facilities can't delegate to inventory", r["delegated"] is False, r)
    r = await team.delegate(ctx("accounting"), "facilities", "x", [])
    check("accounting delegates to no one", r["delegated"] is False, r)
    r = await team.delegate(ctx("customer_service", depth=2, path=("boss", "inventory")), "accounting", "x", [])
    check("depth limit: no delegation from depth 2", r["delegated"] is False and "depth" in r["error"], r)
    r = await team.delegate(ctx("customer_service", depth=1, path=("boss", "inventory")), "inventory", "x", [])
    check("no loops: can't delegate back to an agent in the chain", r["delegated"] is False and "loop" in r["error"], r)
    full = ctx("boss")
    full.deps.budget.delegations = MAX_DELEGATIONS_PER_RUN
    r = await team.delegate(full, "inventory", "x", [])
    check("max delegations per run enforced", r["delegated"] is False and "maximum" in r["error"], r)

    print("corrected rules: vendor restriction and rent urgency")
    try:
        ReplenishmentPlan(sku="X", size="S", on_hand=0, needed=1, shortfall=1, proposed_order_qty=1,
                          vendor_restricted=True, can_order_now=True)
        check("restricted vendor can't be marked orderable", False)
    except ValidationError:
        check("restricted vendor can't be marked orderable", True)

    def rent(days, urgency="Two days left and unpaid: needs approval today."):
        return RentObligation(lease_id=1, space_name="Chapel Street shop", landlord="Elm City Properties",
                              amount=2400.0, due_date="2026-09-02", days_until_due=days, already_paid=False,
                              urgency=urgency, urgency_reasoning="days_until_due=2, unpaid, cash 3400")

    check("urgency is the agent's own words (no fixed categories)",
          rent(2, "pretty urgent, handle first").urgency == "pretty urgent, handle first")
    fac = ctx("facilities")
    report = FacilitiesReport(summary="s", rent_obligations=[rent(2)])
    try:
        _validate(fac, report)
        check("urgency without get_rent_info is rejected", False)
    except ModelRetry:
        check("urgency without get_rent_info is rejected", True)
    fac.deps.budget.observations.append(ToolObservation(
        "facilities", "get_rent_info", {"lease_id": 1},
        {"lease_id": 1, "monthly_rent": 2400.0, "next_due": "2026-09-02", "shop_date": "2026-08-31",
         "days_until_due": 2, "checking_account": {"name": "checking", "balance": 3400.0}}))
    try:
        _validate(fac, FacilitiesReport(summary="s", rent_obligations=[rent(7)]))
        check("days_until_due that doesn't match MCP is rejected", False)
    except ModelRetry:
        check("days_until_due that doesn't match MCP is rejected", True)
    check("days_until_due matching MCP is accepted", _validate(fac, report) is report)

    print("ticket resolution and who files payment requests")

    def td(**kw):
        base = dict(ticket_id=101, priority=1, decision="d", owner="boss", status="proposed", resolution="open")
        return TicketDecision(**{**base, **kw})

    for name, kwargs in [
        ("resolved with remaining actions is rejected", dict(resolution="resolved", remaining_actions=["restock"])),
        ("resolved while awaiting approval is rejected", dict(resolution="resolved", status="awaiting_human_approval")),
        ("payment can't resolve a ticket that has other remaining actions",
         dict(resolution="awaiting_human", resolves_when_payments_executed=["PAY-1"], remaining_actions=["restock"])),
    ]:
        try:
            td(**kwargs)
            check(name, False)
        except ValidationError:
            check(name, True)
    check("payment-only ticket may resolve when the payment executes",
          td(resolution="awaiting_human", resolves_when_payments_executed=["PAY-1"]).resolution == "awaiting_human")

    boss = ctx("boss")
    boss.deps.budget.observations.append(ToolObservation("accounting", "get_invoice_info", {"invoice_id": 501},
                                                         {"invoice_id": 501, "amount": 840.0}))
    pay = PaymentForHumanApproval(kind="invoice", ref_id=501, payee="Bulldog Print Co", amount=840.0, reason="r")

    def boss_out(payment, pays=()):
        return BossDecision(summary="s", payments_needing_human_approval=[payment], ticket_decisions=[
            td(resolution="awaiting_human", status="awaiting_human_approval", resolves_when_payments_executed=list(pays))])

    for name, out in [
        ("Boss payment without an Accounting-filed approval_id is rejected", boss_out(pay)),
        ("Boss can't make up an approval_id", boss_out(pay.model_copy(update={"approval_id": "PAY-FAKE"}))),
    ]:
        try:
            _validate(boss, out)
            check(name, False)
        except ModelRetry:
            check(name, True)
    boss.deps.budget.observations.append(ToolObservation(
        "accounting", "request_payment_approval", {"kind": "invoice", "ref_id": 501},
        {"created": True, "approval_id": "PAY-REAL", "kind": "invoice", "ref_id": 501, "amount": 840.0}))
    good = boss_out(pay.model_copy(update={"approval_id": "PAY-REAL"}), pays=["PAY-REAL"])
    check("Boss payment with Accounting's approval_id is accepted", _validate(boss, good) is good)
    try:
        _validate(boss, boss_out(pay.model_copy(update={"approval_id": "PAY-REAL"}), pays=["BUY-12345678"]))
        check("a purchase ID can't be used to resolve a ticket", False)
    except ModelRetry:
        check("a purchase ID can't be used to resolve a ticket", True)
    refused_ctx = ctx("boss")
    refused_ctx.deps.budget.observations += [
        ToolObservation("accounting", "get_invoice_info", {}, {"amount": 840.0}),
        ToolObservation("accounting", "request_payment_approval", {"kind": "invoice", "ref_id": 501},
                        {"created": False, "error": "Refused: would make checking negative"})]
    out = BossDecision(summary="s", payments_needing_human_approval=[pay])
    check("no approval_id is accepted when Accounting's request was refused", _validate(refused_ctx, out) is out)

    print("resolution check: all current actions done, decisions made, bills paid, reply drafted")
    from backend.models import CustomerResponseDraft, CustomerServiceReport

    def updates(ticket_id=101, ttype="customer_order", still=1, on_hand=0, link=("paid", True), purchases=(),
                payments=(), bills=(), pricing=None, checking=160.0, response=None):
        linked = {"invoice_id": 501, "amount": 840.0, "status": link[0], "covers_requested_item": link[1]} if link else None
        unpaid = [dict(b) for b in bills] + ([linked] if linked and linked["status"] != "paid" else [])
        return ToolObservation("boss", "get_ticket_updates", {"ticket_id": ticket_id}, {
            "found": True, "ticket_id": ticket_id, "ticket_type": ttype,
            "requested": {"sku": "CC-TEE-WHITE" if ttype != "rent_notice" else None, "size": "S", "qty": 1},
            "latest_customer_response": response, "latest_pricing_decision": pricing,
            "purchases": [{"approval_id": i, "status": st, "sku": "CC-TEE-WHITE", "size": "S"} for i, st in purchases],
            "payments": [{"approval_id": i, "status": st} for i, st in payments],
            "quantity_fulfilled": 1 - still, "quantity_still_to_fulfil": still, "on_hand": on_hand,
            "linked_invoice": linked, "unpaid_vendor_invoices": unpaid,
            "cash": {"checking_balance": checking}, "open_steps": []})

    def draft(ticket_id):
        return CustomerServiceReport(summary="s", draft_responses=[CustomerResponseDraft(ticket_id=ticket_id, recipient="r", message="m")])

    def outcome(*obs, ticket_id=101, reports=()):
        c = ctx("boss")
        c.deps.budget.observations.extend(obs)
        c.deps.budget.reports.extend(reports)
        try:
            _validate(c, BossDecision(summary="s", ticket_decisions=[td(ticket_id=ticket_id, resolution="resolved", status="no_action")]))
            return "accepted"
        except ModelRetry as e:
            return str(e)

    check("can't resolve without checking get_ticket_updates in this run", "get_ticket_updates" in outcome())
    check("101: paid linked invoice covers the shortfall + reply drafted -> resolved (no delivery/fulfilment needed)",
          outcome(updates(), reports=[draft(101)]) == "accepted")
    check("101: no reply drafted -> refused", "reply" in outcome(updates()))
    check("101: linked invoice unpaid -> refused (bill must be paid)", "unpaid" in outcome(updates(link=("open", True)), reports=[draft(101)]))
    check("101: no restock secured -> refused", "no restock" in outcome(updates(link=None), reports=[draft(101)]))
    check("pending purchase -> refused (human decision missing)", "human decision" in outcome(
        updates(purchases=(("BUY-1", "pending"),)), reports=[draft(101)]))
    check("approved purchase neither ordered nor cancelled -> refused", "neither ordered nor cancelled" in outcome(
        updates(purchases=(("BUY-1", "approved"),)), reports=[draft(101)]))
    check("approved payment not executed -> refused", "not yet paid" in outcome(
        updates(payments=(("PAY-1", "approved"),)), reports=[draft(101)]))
    p103 = dict(ticket_id=103, ttype="price_override", still=20, on_hand=8, link=None)
    check("103: pricing decided, restock rejected, reply drafted -> resolved (no fulfilment needed)",
          outcome(updates(**p103, purchases=(("BUY-2", "rejected"),), pricing={"details": {"decision": "approved"}}),
                  ticket_id=103, reports=[draft(103)]) == "accepted")
    check("103: no pricing decision -> refused", "pricing decision" in outcome(updates(**p103), ticket_id=103, reports=[draft(103)]))
    r = outcome(updates(**p103, purchases=(("BUY-2", "ordered"),), pricing={"details": {"decision": "approved"}},
                        bills=[{"invoice_id": 502, "amount": 264.0, "status": "open"}]), ticket_id=103, reports=[draft(103)])
    check("103: ordered restock with unpaid $264 bill vs $160 cash -> refused, cash shortfall named",
          "invoice 502" in r and "checking holds only $160.00" in r, r)
    check("rent ticket: paid, no reply needed -> resolved", outcome(updates(ticket_id=102, ttype="rent_notice", still=0, link=None,
                                                                            payments=(("PAY-9", "executed"),)), ticket_id=102) == "accepted")
    check("fulfilled order with recorded response counts as answered (no new draft needed)",
          outcome(updates(still=0, response={"details": {"choice": "wait"}})) == "accepted")

    events = [e["event"] for e in json.loads(AUDIT.read_text())]
    check("blocked actions recorded in audit", events.count("payment_blocked") == 2
          and events.count("tool_blocked") == 3 + 5 * len(MANAGER_TOOLS) and events.count("delegation_refused") >= 4, events)
    print(f"\n{len(PASSED)} checks passed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as e:
        print(e)
        sys.exit(1)
