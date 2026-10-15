"""Campus Customs FastAPI backend for the React dashboard (Problem 8).

Start it from the backend/ folder:

    ../.venv/bin/uvicorn main:app --reload --port 8010

It reuses the Problem 5 system rather than duplicating it:
  - shop facts are read through the FastMCP server (the same MCP connection the
    agents use), never with SQL here;
  - ticket runs and payment execution go through `run_team` and the five agents;
  - approvals use the shared approvals store (mcp_server/approvals.py), and
    every Problem 5 payment rule still applies.

Safety: agents can only *prepare* payments and purchases (pending requests).
A person approves or rejects them here, typing the approval ID to confirm.
An approved payment is then executed by the Accounting Agent, which the backend
authorizes for that one ID only, and the MCP server re-checks it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Works both as `uvicorn main:app` from backend/ and as `backend.main` from the project root.
ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "mcp_server"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from approvals import APPROVALS_PATH, PURCHASE_KIND, record_human_decision  # noqa: E402
from manager_events import EVENTS_PATH, read_events  # noqa: E402
from backend import audit  # noqa: E402
from backend.agents import CampusTeam, new_run_id, run_team  # noqa: E402
from backend.config import (  # noqa: E402
    APPROVALS_ARCHIVE_DIR, AUDIT_PATH, MODEL_NAME, ORIGINAL_DB_PATH, WORKING_DB_PATH,
)
from backend.mcp_client import build_toolset  # noqa: E402
from backend.models import (  # noqa: E402
    CancelPurchaseIn, CustomerResponseIn, FulfilmentIn, ManagerActionResult, PlaceOrderIn, PricingDecisionIn,
    StockReceiptIn,
    CashView, DecisionEffects, DecisionResult, EventView, HumanDecision, ResetRequest, ResetResult, RunStarted,
    RunView, TicketView,
)

TICKET_TASK = """Handle ticket {id} ({type}: "{subject}" from {requester}).
Read it with get_ticket, delegate to the specialists you need, and decide its priority, decision, owner, status, and next steps.
Prepare, but never execute, anything that needs money or an order:
- Payments: delegate to Accounting to file request_payment_approval for each payment you recommend now, and list each one in payments_needing_human_approval with the approval_id Accounting returns.
- Restocks: ask Inventory to file request_purchase_approval for restocks you recommend now.
A human approves or rejects these on the dashboard. If this ticket was handled before, check get_ticket_updates for earlier outcomes. A purchase a person rejected is a decision: don't ask Inventory to request it again unless the rejection's stated reason no longer applies (e.g. cash now covers it, or a newer recorded customer response changes the need); the server refuses repeats otherwise.
Resolved means: every action the shop can take now is done, every required human decision is made, no vendor invoice for the ticket is unpaid (check cash), and the customer reply is drafted by Customer Service. Future deliveries and customer responses are follow-ups (next_steps / risks), not remaining actions, and must not be invented. Use resolves_when_payments_executed only when executing those payments would satisfy all of that. A purchase approval never finishes a ticket by itself.
Decide only ticket {id}. You may note in `risks` how it affects the other open tickets."""

EXECUTE_TASK = """A human ({approver}) approved payment request {approval_id} on the dashboard.
Check with list_payment_approvals that {approval_id} is approved, then execute it with execute_payment and report the result.
Do not request, approve, or execute anything else."""


# --------------------------------------------------------------------------
# App state
# --------------------------------------------------------------------------

class State:
    def __init__(self) -> None:
        self.toolset = build_toolset()
        self.team: CampusTeam | None = None
        self.runs: dict[str, RunView] = {}
        self.active_run: str | None = None   # one agent run at a time
        self.tasks: set[asyncio.Task] = set()

    def get_team(self) -> CampusTeam:
        """Build the agents on first use (needs PORTKEY_API_KEY); shares the app's MCP connection."""
        if self.team is None:
            try:
                self.team = CampusTeam(toolset=self.toolset)
            except RuntimeError as exc:
                raise HTTPException(503, f"Agents unavailable: {exc}") from exc
        return self.team


state: State


@asynccontextmanager
async def lifespan(app: FastAPI):
    global state
    state = State()
    await state.toolset.__aenter__()
    state.runs = _load_runs_from_audit()
    try:
        yield
    finally:
        for task in list(state.tasks):
            task.cancel()
        await state.toolset.__aexit__(None, None, None)


app = FastAPI(
    title="Campus Customs agent desk",
    description="Backend for the Campus Customs React dashboard: tickets, agent runs, events, approvals, cash, reset.",
    version="1.0",
    lifespan=lifespan,
)

# React dev servers (Vite on 5173, Create React App on 3000). Override with CORS_ORIGINS="a,b".
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
).split(",")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


async def mcp(name: str, **args: Any) -> Any:
    """Call a Campus Customs MCP tool on the shared connection."""
    result = await state.toolset.direct_call_tool(name, args)
    if isinstance(result, dict) and set(result) == {"result"}:
        return result["result"]
    return result


def _read_audit() -> list[dict]:
    if not AUDIT_PATH.exists() or not AUDIT_PATH.stat().st_size:
        return []
    return json.loads(AUDIT_PATH.read_text())


def _load_runs_from_audit() -> dict[str, RunView]:
    """Rebuild run history from the audit trail (runs since the last database reset)."""
    records = _read_audit()
    last_reset = max((i for i, e in enumerate(records) if e["event"] == "database_reset"), default=-1)
    runs: dict[str, RunView] = {}
    for e in records[last_reset + 1:]:
        rid = e["run_id"]
        if e["event"] == "run_started":
            approved = e.get("human_approved_payment_ids") or []
            runs[rid] = RunView(
                run_id=rid, ticket_id=e.get("ticket_id"),
                kind="payment_execution" if approved else ("ticket" if e.get("ticket_id") is not None else "other"),
                approval_id=approved[0] if approved else None, status="running", started_at=e["timestamp"],
            )
        elif rid in runs and e["event"] == "agent_finished" and e.get("depth") == 0:
            runs[rid].output = e.get("output")
        elif rid in runs and e["event"] in ("run_finished", "run_failed"):
            runs[rid].status = "finished" if e["event"] == "run_finished" else "failed"
            runs[rid].finished_at = e["timestamp"]
            runs[rid].error = e.get("error")
    # A run still "running" after a restart was interrupted.
    for run in runs.values():
        if run.status == "running":
            run.status, run.error = "failed", "interrupted (server restarted)"
    return runs


def _last_ticket_run(ticket_id: int) -> RunView | None:
    """The most recently started run on this ticket (state.runs keeps start order)."""
    runs = [r for r in state.runs.values() if r.kind == "ticket" and r.ticket_id == ticket_id]
    return runs[-1] if runs else None


async def _approvals(ticket_id: int | None = None) -> list[dict]:
    records = await mcp("list_payment_approvals")
    return [r for r in records if ticket_id is None or r.get("ticket_id") == ticket_id]


def _ticket_progress(ticket_id: int, approvals: list[dict],
                     completed: RunView | None = None) -> tuple[str | None, str, str | None, list[str]]:
    """Where a ticket stands: (status it should have, next step, Boss resolution, remaining actions).

    Only the Boss resolves a ticket. It is resolved when the Boss's latest
    decision says "resolved", or when every payment the Boss named in
    resolves_when_payments_executed has been executed and the Boss listed no
    other remaining actions. Paying something or approving a purchase never
    resolves a ticket by itself, and a rejection means the team should reassess.
    `completed` is a run that just succeeded but isn't marked finished yet.
    """
    last = _last_ticket_run(ticket_id)
    if last is None:
        return None, "Not run yet. Run the agent team on this ticket.", None, []
    if last.status == "running" and last is not completed:
        return None, "The agents are working on this ticket.", None, []
    if not (last.status == "finished" or (last is completed and last.error is None)) or not last.output:
        return None, f"The last run failed ({last.error}). Run the team again.", None, []
    decision = next((d for d in last.output.get("ticket_decisions", []) if d.get("ticket_id") == ticket_id), None)
    if decision is None:
        return "open", "The Boss gave no decision for this ticket. Run the team again.", None, []
    resolution = decision.get("resolution")
    remaining = decision.get("remaining_actions") or []
    if resolution == "resolved":
        return "resolved", f"Resolved: {decision['decision']}", resolution, []

    mine = [a for a in approvals if a.get("ticket_id") == ticket_id]
    by_id = {a["approval_id"]: a for a in mine}
    pending = [a["approval_id"] for a in mine if a["status"] == "pending"]
    unexecuted = [a["approval_id"] for a in mine if a["status"] == "approved" and a["kind"] != PURCHASE_KIND]
    rejected = [a["approval_id"] for a in mine
                if a["status"] == "rejected" and (a.get("rejected_at") or "")[:19] >= last.started_at[:19]]
    if pending:
        return "open", f"Waiting for a human decision on {', '.join(pending)}.", resolution, remaining
    if unexecuted:
        return "open", f"Approved but not yet paid: {', '.join(unexecuted)}. Retry execution.", resolution, remaining
    if rejected:
        return "open", (f"{', '.join(rejected)} was rejected. Run the team again to reassess this ticket."), \
            resolution, remaining
    ordered = [a for a in mine if a["kind"] == PURCHASE_KIND and a["status"] == "ordered"]
    if ordered:
        return "open", ("Ordered: " + ", ".join(
            f"{a['approval_id']} (expected around {a.get('expected_arrival')}"
            + (f"; vendor invoice {a['vendor_invoice_id']} to pay" if a.get("vendor_invoice_id") else "") + ")"
            for a in ordered) + ". Run the team again so Accounting can plan the bill and the Boss reassesses."), \
            resolution, remaining
    since = [e for e in read_events(ticket_id) if e["recorded_at"][:19] >= last.started_at[:19]]
    if since:
        kinds = ", ".join(dict.fromkeys(e["kind"].replace("_", " ") for e in since))
        return "open", (f"{len(since)} manager event(s) recorded since the last run ({kinds}). "
                        "Run the team again so the Boss reassesses."), resolution, remaining
    pay_ids = decision.get("resolves_when_payments_executed") or []
    if pay_ids and not remaining and all(by_id.get(i, {}).get("status") == "executed" for i in pay_ids):
        return "resolved", f"Resolved: {', '.join(pay_ids)} executed and nothing else was needed.", resolution, []
    if remaining:
        return "open", "Still needed: " + "; ".join(remaining) + ". Run the team again to reassess when ready.", \
            resolution, remaining
    return "open", "Open. Run the team again to reassess.", resolution, remaining


async def _ticket_view(t: dict, approvals: list[dict]) -> TicketView:
    last = _last_ticket_run(t["id"])
    _, next_step, resolution, remaining = _ticket_progress(t["id"], approvals)
    if t["status"] == "resolved" and last is None:
        next_step = "Resolved."
    return TicketView(
        **{k: t.get(k) for k in ("id", "type", "requester", "subject", "sku", "size", "qty", "lease_id",
                                 "invoice_id", "status", "notes", "created_at")},
        running=any(r.status == "running" and r.ticket_id == t["id"] for r in state.runs.values()),
        last_run_id=last.run_id if last else None,
        last_run_status=last.status if last else None,
        pending_approvals=sum(1 for a in approvals if a.get("ticket_id") == t["id"] and a["status"] == "pending"),
        resolution=resolution,
        remaining_actions=remaining,
        next_step=next_step,
    )


async def _refresh_ticket_status(ticket_id: int, completed: RunView | None = None) -> None:
    """Set the ticket's status (via MCP) to what _ticket_progress says it should be."""
    new_status, next_step, _, _ = _ticket_progress(ticket_id, await _approvals(), completed)
    if new_status is None:
        return
    ticket = await mcp("get_ticket", ticket_id=ticket_id)
    if ticket.get("status") != new_status:
        await mcp("set_ticket_status", ticket_id=ticket_id, status=new_status)
        audit.record("ticket_status_changed", run_id="api", agent=None, ticket_id=ticket_id,
                     old_status=ticket.get("status"), new_status=new_status, reason=next_step)


def _start_background(coro) -> None:
    task = asyncio.create_task(coro)
    state.tasks.add(task)
    task.add_done_callback(state.tasks.discard)


def _claim_run_slot(run: RunView) -> None:
    if state.active_run is not None:
        raise HTTPException(409, f"Another agent run is in progress ({state.active_run}). Try again when it finishes.")
    state.active_run = run.run_id
    state.runs[run.run_id] = run


async def _run_in_background(run: RunView, task: str, **kwargs: Any) -> None:
    """Run the team, then update the ticket's status.

    The run is reported as finished/failed only after that, so a client that
    sees "finished" also sees the updated ticket.
    """
    status = "failed"
    try:
        _, output = await run_team(task, team=state.get_team(), run_id=run.run_id, ticket_id=run.ticket_id, **kwargs)
        run.output = output.model_dump(mode="json")
        status = "finished"
    except Exception as exc:  # recorded in the audit trail by run_team
        run.error = f"{type(exc).__name__}: {exc}"
    try:
        if run.ticket_id is not None:
            await _refresh_ticket_status(run.ticket_id, completed=run if status == "finished" else None)
    except Exception as exc:
        audit.record("ticket_status_refresh_failed", run_id=run.run_id, ticket_id=run.ticket_id, error=str(exc))
    finally:
        run.finished_at = _now()
        run.status = status
        state.active_run = None


def _start_payment_execution(record: dict, approver: str) -> str:
    run = RunView(run_id=new_run_id(), kind="payment_execution", ticket_id=record.get("ticket_id"),
                  approval_id=record["approval_id"], status="running", started_at=_now())
    _claim_run_slot(run)
    _start_background(_run_in_background(
        run, EXECUTE_TASK.format(approver=approver, approval_id=record["approval_id"]),
        entry_agent="accounting", human_approved_payment_ids=[record["approval_id"]],
    ))
    return run.run_id


async def _find_approval(approval_id: str) -> dict:
    record = next((r for r in await _approvals() if r["approval_id"] == approval_id), None)
    if record is None:
        raise HTTPException(404, f"No approval request {approval_id}.")
    return record


def _check_confirmation(approval_id: str, body: HumanDecision) -> str:
    if body.confirm_approval_id.strip() != approval_id:
        raise HTTPException(400, "confirm_approval_id must match the approval ID exactly.")
    approver = body.approver.strip()
    if not approver:
        raise HTTPException(400, "approver is required.")
    return approver


# --------------------------------------------------------------------------
# Event formatting for the dashboard
# --------------------------------------------------------------------------

def _short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _describe(e: dict) -> tuple[str, str, str | None]:
    """(category, plain-language text, tool) for one audit record."""
    ev, agent = e["event"], e.get("agent") or "human"
    out = e.get("output") or {}
    match ev:
        case "run_started":
            return "run", f"Run started ({agent}): {_short(e.get('task', '').splitlines()[0] if e.get('task') else '')}", None
        case "run_finished":
            u = e.get("usage") or {}
            return "run", f"Run finished: {u.get('requests', '?')} model requests, {u.get('total_tokens', '?')} tokens, {e.get('delegations', 0)} delegations", None
        case "run_failed":
            return "error", f"Run failed: {e.get('error_type')}: {_short(e.get('error'))}", None
        case "agent_started":
            return "run", f"{agent} started working", None
        case "agent_finished":
            return "message", f"{agent}: {out.get('summary', '(no summary)')}", None
        case "agent_failed":
            return "error", f"{agent} stopped: {_short(e.get('error'))}", None
        case "decision":
            d = e.get("decision") or {}
            return "message", f"Boss decision: {d.get('summary', '')}", None
        case "delegation_started":
            return "delegation", f"{agent} → {e.get('to')}: {_short(e.get('task'), 240)}", None
        case "delegation_result":
            return "delegation", f"{e.get('to')} reported back to {agent}: {(e.get('report') or {}).get('summary', '')}", None
        case "delegation_refused" | "delegation_failed":
            return "error", f"{agent} → {e.get('to')} refused: {e.get('reason') or e.get('error')}", None
        case "tool_call":
            return "tool", f"{agent} called {e.get('tool')}({_short(e.get('args'), 120)})", e.get("tool")
        case "tool_result":
            return "tool", f"{e.get('tool')} returned {_short(e.get('result'))}", e.get("tool")
        case "tool_error" | "tool_blocked":
            return "error", f"{agent}: {e.get('tool')} {ev.replace('tool_', '')}: {e.get('error') or e.get('reason')}", e.get("tool")
        case "approval_requested":
            r = e.get("result") or {}
            return "approval", f"{agent} prepared {r.get('approval_id')}: {r.get('description')} (${r.get('amount')}), waiting for a human", None
        case "approval_request_refused":
            return "approval", f"{agent}'s request was refused: {(e.get('result') or {}).get('error')}", None
        case "approval_granted" | "approval_rejected":
            word = "approved" if ev == "approval_granted" else "rejected"
            return "approval", (f"{e.get('by')} {word} {e.get('approval_id')} ({e.get('kind')}, ${e.get('amount')})"
                                + (f": {e['reason']}" if e.get("reason") else "")), None
        case "payment_executed":
            r = e.get("result") or {}
            return "payment", f"Payment {e.get('approval_id')} executed: ${r.get('amount')} paid, checking now ${r.get('balance_after')}", None
        case "payment_refused" | "payment_blocked":
            return "payment", f"Payment {e.get('approval_id') or ''} {ev.split('_')[1]}: {(e.get('result') or {}).get('error') or e.get('reason')}", None
        case "ticket_status_changed":
            return "run", f"Ticket {e.get('ticket_id')} is now {e.get('new_status')} ({e.get('reason')})", None
        case "database_reset":
            return "run", "Working database reset to the original", None
        case "manager_customer_response" | "manager_pricing_decision" | "manager_purchase_order" \
                | "manager_purchase_cancelled" | "manager_stock_receipt" | "manager_fulfilment":
            ev_ = e.get("event_record") or {}
            label = "Manager recorded (simulated)" if ev_.get("simulated") else "Manager recorded"
            return "manager", f"{label}: {e.get('summary', ev.replace('manager_', '').replace('_', ' '))}", None
    return "run", ev.replace("_", " "), e.get("tool")


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict:
    """Server, MCP connection, and model status."""
    tools = await state.toolset.list_tools()
    return {"status": "ok", "model": MODEL_NAME, "mcp_tools": len(tools), "active_run": state.active_run}


@app.get("/api/tickets", response_model=list[TicketView])
async def list_tickets() -> list[TicketView]:
    """All tickets with their status (open / resolved), run state, and pending approvals."""
    tickets = await mcp("list_tickets")
    approvals = await _approvals()
    return [await _ticket_view(t, approvals) for t in tickets]


@app.get("/api/tickets/{ticket_id}", response_model=TicketView)
async def get_ticket(ticket_id: int) -> TicketView:
    t = await mcp("get_ticket", ticket_id=ticket_id)
    if not t.get("found"):
        raise HTTPException(404, t.get("error", "Ticket not found."))
    return await _ticket_view(t, await _approvals())


@app.post("/api/tickets/{ticket_id}/run", response_model=RunStarted, status_code=202)
async def run_ticket(ticket_id: int) -> RunStarted:
    """Start the agent team (Boss first) on one ticket. Returns at once; follow it with /api/runs/{run_id} and /api/events."""
    t = await mcp("get_ticket", ticket_id=ticket_id)
    if not t.get("found"):
        raise HTTPException(404, t.get("error", "Ticket not found."))
    if t["status"] == "resolved":
        raise HTTPException(409, f"Ticket {ticket_id} is already resolved. Reset the database to run it again.")
    state.get_team()  # fail fast (503) if the agents can't be built
    run = RunView(run_id=new_run_id(), kind="ticket", ticket_id=ticket_id, status="running", started_at=_now())
    _claim_run_slot(run)
    _start_background(_run_in_background(run, TICKET_TASK.format(**t)))
    return RunStarted(run_id=run.run_id, message=f"Agent team started on ticket {ticket_id}.")


@app.get("/api/runs", response_model=list[RunView])
async def list_runs() -> list[RunView]:
    """Agent runs since the last reset, newest first."""
    return list(reversed(state.runs.values()))


@app.get("/api/runs/{run_id}", response_model=RunView)
async def get_run(run_id: str) -> RunView:
    if run_id not in state.runs:
        raise HTTPException(404, f"No run {run_id}.")
    return state.runs[run_id]


@app.get("/api/events", response_model=list[EventView])
async def list_events(
    limit: int = Query(200, ge=1, le=2000),
    run_id: str | None = None,
    ticket_id: int | None = None,
    since: str | None = Query(None, description="Only events after this ISO timestamp (for polling)"),
    include_tool_results: bool = True,
) -> list[EventView]:
    """Recent agent activity from output/audit_trail.json, oldest first: messages, delegations, tool calls, approvals, payments."""
    records = _read_audit()
    run_ticket = {e["run_id"]: e.get("ticket_id") for e in records if e["event"] == "run_started"}
    events = []
    for e in records:
        tid = run_ticket.get(e["run_id"], e.get("ticket_id"))
        if run_id and e["run_id"] != run_id:
            continue
        if ticket_id is not None and tid != ticket_id:
            continue
        if since and e["timestamp"] <= since:
            continue
        if not include_tool_results and e["event"] == "tool_result":
            continue
        category, text, tool = _describe(e)
        details = {k: v for k, v in e.items() if k not in ("timestamp", "run_id", "agent", "depth", "event", "path")}
        events.append(EventView(timestamp=e["timestamp"], run_id=e["run_id"], ticket_id=tid, agent=e.get("agent"),
                                depth=e.get("depth"), event=e["event"], category=category, text=text, tool=tool,
                                details=details))
    return events[-limit:]


@app.get("/api/approvals")
async def list_approvals(status: str | None = None, ticket_id: int | None = None) -> list[dict]:
    """Payment and purchase requests prepared by the agents, newest first."""
    records = [r for r in await _approvals(ticket_id) if status is None or r["status"] == status]
    return sorted(records, key=lambda r: r["requested_at"], reverse=True)


@app.post("/api/approvals/{approval_id}/approve", response_model=DecisionResult)
async def approve(approval_id: str, body: HumanDecision) -> DecisionResult:
    """A person approves a pending request. Payments are then executed by the Accounting Agent."""
    approver = _check_confirmation(approval_id, body)
    record = await _find_approval(approval_id)
    if record["status"] != "pending":
        raise HTTPException(409, f"{approval_id} is {record['status']}; only pending requests can be approved.")
    is_purchase = record["kind"] == PURCHASE_KIND
    if is_purchase:
        vendor = await mcp("get_vendor_status", vendor_id=record["vendor_id"])
        if vendor.get("restricted"):
            raise HTTPException(409, f"Not approved: {vendor.get('name')} is restricted ({vendor.get('restriction_reason')}).")
    elif state.active_run is not None:
        raise HTTPException(409, f"Another agent run is in progress ({state.active_run}). Approve when it finishes.")

    try:
        record = record_human_decision(approval_id, approver, approve=True, reason=body.reason)
    except (LookupError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    audit.record("approval_granted", run_id="human", agent=None, approval_id=approval_id, by=approver,
                 kind=record["kind"], ref_id=record["ref_id"], amount=record["amount"],
                 ticket_id=record.get("ticket_id"), reason=record.get("approval_reason"), via="dashboard")

    if is_purchase:
        if record.get("ticket_id") is not None:
            await _refresh_ticket_status(record["ticket_id"])
        return DecisionResult(approval=record, effects=DecisionEffects(), message=(
            f"Purchase approval recorded: {approver} approved {record['description']} (about "
            f"${record['amount']:,.2f}). This only records the decision. No order was placed, and cash and "
            f"inventory are unchanged. Place the order with {record['payee']} yourself. The ticket stays open "
            "until the Boss confirms nothing else is needed."))
    run_id = _start_payment_execution(record, approver)
    return DecisionResult(approval=record, execution_run_id=run_id,
                          effects=DecisionEffects(payment_execution_started=True), message=(
        f"Payment approved by {approver}. The Accounting Agent is executing it now (run {run_id}). "
        "Paying it doesn't resolve the ticket by itself unless the Boss said nothing else is needed."))


@app.post("/api/approvals/{approval_id}/reject", response_model=DecisionResult)
async def reject(approval_id: str, body: HumanDecision) -> DecisionResult:
    """A person rejects a pending request. Nothing is paid or ordered."""
    approver = _check_confirmation(approval_id, body)
    await _find_approval(approval_id)
    try:
        record = record_human_decision(approval_id, approver, approve=False, reason=body.reason)
    except (LookupError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    audit.record("approval_rejected", run_id="human", agent=None, approval_id=approval_id, by=approver,
                 kind=record["kind"], ref_id=record["ref_id"], amount=record["amount"],
                 ticket_id=record.get("ticket_id"), reason=record.get("rejection_reason"), via="dashboard")
    if record.get("ticket_id") is not None:
        await _refresh_ticket_status(record["ticket_id"])
    return DecisionResult(approval=record, effects=DecisionEffects(), message=(
        f"Rejected by {approver}. Nothing was paid or ordered. The ticket stays open; run the team again to reassess."))


@app.post("/api/approvals/{approval_id}/execute", response_model=DecisionResult)
async def retry_execution(approval_id: str, body: HumanDecision) -> DecisionResult:
    """Retry executing an already-approved payment (e.g. if the Accounting run failed)."""
    approver = _check_confirmation(approval_id, body)
    record = await _find_approval(approval_id)
    if record["kind"] == PURCHASE_KIND or record["status"] != "approved":
        raise HTTPException(409, f"{approval_id} is not an approved, unexecuted payment.")
    run_id = _start_payment_execution(record, approver)
    return DecisionResult(approval=record, execution_run_id=run_id,
                          effects=DecisionEffects(payment_execution_started=True),
                          message=f"The Accounting Agent is executing {approval_id} (run {run_id}).")



# --------------------------------------------------------------------------
# Manager actions: a person records business events the agents can't perform.
# Each route needs a name and a typed confirmation, calls one human-only MCP
# tool, and is written to the audit trail. None of them changes cash, sends a
# message, or resolves a ticket (only the Boss resolves, on its next run).
# --------------------------------------------------------------------------

def _confirm(given: str, expected: str) -> None:
    if given.strip() != expected:
        raise HTTPException(400, f"Type {expected} exactly to confirm.")


def _no_active_run() -> None:
    if state.active_run is not None:
        raise HTTPException(409, f"An agent run is in progress ({state.active_run}). Record manager actions when it finishes.")


async def _manager_action(tool: str, args: dict, *, ticket_id: int | None, summary: str, message: str,
                          effects: dict) -> ManagerActionResult:
    """Call one human-only MCP tool on the person's behalf, audit it, and refresh the ticket's next step."""
    result = await mcp(tool, **args)
    if not result.get("recorded"):
        detail: Any = result.get("error", "Refused.")
        if result.get("needs_acknowledgement"):
            detail = {"error": detail, "needs_acknowledgement": result["needs_acknowledgement"],
                      "cash_warning": result.get("cash_warning"), "duplicate_warnings": result.get("duplicate_warnings")}
        raise HTTPException(409, detail)
    event = result["event"]
    ticket_id = ticket_id if ticket_id is not None else event.get("ticket_id")
    audit.record(f"manager_{event['kind']}", run_id="human", agent=None, ticket_id=ticket_id,
                 by=event["recorded_by"], simulated=event["simulated"], summary=summary, event_record=event,
                 via="dashboard")
    if ticket_id is not None:
        await _refresh_ticket_status(ticket_id)
    label = "Recorded (simulated). " if event["simulated"] else "Recorded. "
    return ManagerActionResult(event=event, message=label + message, effects={"cash_changed": False, **effects})


@app.get("/api/tickets/{ticket_id}/updates")
async def ticket_updates(ticket_id: int) -> dict:
    """Manager-recorded events plus purchase/payment status for one ticket (what agents can read too)."""
    result = await mcp("get_ticket_updates", ticket_id=ticket_id)
    if not result.get("found"):
        raise HTTPException(404, result.get("error", "Ticket not found."))
    return result


@app.post("/api/tickets/{ticket_id}/customer-response", response_model=ManagerActionResult)
async def customer_response(ticket_id: int, body: CustomerResponseIn) -> ManagerActionResult:
    """Record what the customer decided. Nothing is sent to the customer."""
    _confirm(body.confirm, str(ticket_id))
    _no_active_run()
    return await _manager_action(
        "record_customer_response",
        dict(ticket_id=ticket_id, choice=body.choice, summary=body.summary, channel=body.channel,
             recorded_by=body.recorded_by, simulated=body.simulated, basis=body.basis),
        ticket_id=ticket_id, summary=f"customer response '{body.choice}' for ticket {ticket_id}: {body.summary}",
        message=f"Customer response '{body.choice}' saved for ticket {ticket_id}. Nothing was sent to the customer; "
                "the agents will see it the next time the team runs.",
        effects={"message_sent": False, "inventory_changed": False})


@app.post("/api/tickets/{ticket_id}/pricing-decision", response_model=ManagerActionResult)
async def pricing_decision(ticket_id: int, body: PricingDecisionIn) -> ManagerActionResult:
    """Record a person's decision on a discounted price. Recalculated from pricing; never below cost."""
    _confirm(body.confirm, str(ticket_id))
    _no_active_run()
    result = await _manager_action(
        "record_pricing_decision",
        dict(ticket_id=ticket_id, sku=body.sku, size=body.size, quantity=body.quantity, discount_pct=body.discount_pct,
             decision=body.decision, recorded_by=body.recorded_by, note=body.note, simulated=body.simulated,
             basis=body.basis),
        ticket_id=ticket_id, summary=f"pricing decision {body.decision}: {body.discount_pct}% off {body.quantity} x {body.sku} {body.size}",
        message="", effects={"revenue_recorded": False, "inventory_changed": False})
    d = result.event["details"]
    result.message += (f"Pricing {d['decision']}: {d['discount_pct']}% off → ${d['unit_price']:.2f} each "
                       f"(${d['margin_per_unit']:.2f} margin above ${d['unit_cost']:.2f} cost). Not promised to the "
                       "customer yet; no revenue recorded.")
    return result


@app.post("/api/tickets/{ticket_id}/fulfilment", response_model=ManagerActionResult)
async def fulfilment(ticket_id: int, body: FulfilmentIn) -> ManagerActionResult:
    """Record handing the order over; removes it from inventory. Needs a recorded customer response first."""
    _confirm(body.confirm, str(ticket_id))
    _no_active_run()
    result = await _manager_action(
        "record_fulfilment",
        dict(ticket_id=ticket_id, sku=body.sku, size=body.size, quantity=body.quantity, recorded_by=body.recorded_by,
             simulated=body.simulated, basis=body.basis),
        ticket_id=ticket_id, summary=f"fulfilled {body.quantity} x {body.sku} {body.size} for ticket {ticket_id}",
        message="", effects={"revenue_recorded": False})
    d = result.event["details"]
    result.effects.update(inventory_change=-d["quantity"], qty_after=d["qty_after"])
    result.message += (f"{d['quantity']} x {d['sku']} {d['size']} fulfilled ({d['fulfilled_total']} of {d['ordered_qty']} "
                       f"for this ticket); stock now {d['qty_after']}. No revenue recorded.")
    return result


@app.post("/api/approvals/{approval_id}/place-order", response_model=ManagerActionResult)
async def place_order(approval_id: str, body: PlaceOrderIn) -> ManagerActionResult:
    """Record that an approved purchase was ordered from the vendor. Cash and duplicate warnings must be acknowledged."""
    _confirm(body.confirm, approval_id)
    _no_active_run()
    result = await _manager_action(
        "place_purchase_order",
        dict(approval_id=approval_id, recorded_by=body.recorded_by, vendor_reference=body.vendor_reference,
             acknowledge_cash_warning=body.acknowledge_cash_warning,
             acknowledge_duplicate_warning=body.acknowledge_duplicate_warning, simulated=body.simulated, basis=body.basis),
        ticket_id=None, summary=f"purchase order placed for {approval_id}", message="",
        effects={"purchase_status": "ordered", "inventory_changed": False})
    d = result.event["details"]
    result.effects.update(vendor_invoice_created=d.get("vendor_invoice_id"))
    result.message += (f"{approval_id} is now ordered: {d['quantity']} x {d['sku']} {d['size']} from {d['vendor']}, "
                       f"expected around {d['expected_arrival']}. Open vendor invoice {d.get('vendor_invoice_id')} "
                       f"(${d['estimated_cost']:,.2f}, due {d.get('vendor_invoice_due')}) was created; no money moved. "
                       "Pay it through Accounting and your approval.")
    return result


@app.post("/api/approvals/{approval_id}/cancel", response_model=ManagerActionResult)
async def cancel_purchase(approval_id: str, body: CancelPurchaseIn) -> ManagerActionResult:
    """Cancel an approved purchase that hasn't been ordered (e.g. it would duplicate another order)."""
    _confirm(body.confirm, approval_id)
    _no_active_run()
    return await _manager_action(
        "cancel_purchase", dict(approval_id=approval_id, reason=body.reason, recorded_by=body.recorded_by),
        ticket_id=None, summary=f"{approval_id} cancelled: {body.reason}",
        message=f"{approval_id} cancelled. No order exists for it and no money moved.",
        effects={"purchase_status": "cancelled", "inventory_changed": False})


@app.post("/api/inventory/receipts", response_model=ManagerActionResult)
async def stock_receipt(body: StockReceiptIn) -> ManagerActionResult:
    """Record stock arriving (against an ordered purchase or an invoice); adds it to inventory."""
    _confirm(body.confirm, body.source_id)
    _no_active_run()
    result = await _manager_action(
        "record_stock_receipt",
        dict(sku=body.sku, size=body.size, quantity=body.quantity, source_kind=body.source_kind, source_id=body.source_id,
             recorded_by=body.recorded_by, simulated=body.simulated, basis=body.basis, ticket_id=body.ticket_id),
        ticket_id=body.ticket_id, summary=f"received {body.quantity} x {body.sku} {body.size} ({body.source_kind} {body.source_id})",
        message="", effects={"vendor_invoice_created": False})
    d = result.event["details"]
    result.effects.update(inventory_change=d["quantity"], qty_after=d["qty_after"])
    result.message += (f"+{d['quantity']} x {d['sku']} {d['size']} received against {body.source_kind.replace('_', ' ')} "
                       f"{body.source_id}; stock now {d['qty_after']}. No money moved and no vendor invoice was created.")
    return result


@app.get("/api/cash", response_model=CashView)
async def cash() -> CashView:
    """Current checking balance (cash_accounts table, via MCP)."""
    pos = await mcp("get_cash_position")
    checking = next((a for a in pos["accounts"] if a["name"] == "checking"), None)
    if checking is None:
        raise HTTPException(404, "No checking account in cash_accounts.")
    return CashView(account="checking", balance=checking["balance"], as_of=checking["date"], shop_date=pos["shop_date"])


@app.post("/api/reset", response_model=ResetResult)
async def reset(body: ResetRequest) -> ResetResult:
    """Restore data/campus_customs_new.db from the original and archive approvals and manager events, for a fresh run.

    The audit trail is kept (a database_reset record is added).
    """
    if state.active_run is not None:
        raise HTTPException(409, f"An agent run is in progress ({state.active_run}). Reset when it finishes.")
    if not ORIGINAL_DB_PATH.exists():
        raise HTTPException(500, f"Original database not found: {ORIGINAL_DB_PATH}")
    tmp = WORKING_DB_PATH.with_suffix(".resetting")
    shutil.copyfile(ORIGINAL_DB_PATH, tmp)
    os.replace(tmp, WORKING_DB_PATH)
    if hashlib.sha256(WORKING_DB_PATH.read_bytes()).digest() != hashlib.sha256(ORIGINAL_DB_PATH.read_bytes()).digest():
        raise HTTPException(500, "Reset copy did not match the original.")

    archived = None
    if APPROVALS_PATH.exists() and json.loads(APPROVALS_PATH.read_text() or "[]"):
        APPROVALS_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archived = APPROVALS_ARCHIVE_DIR / f"payment_approvals_{stamp}.json"
        shutil.move(APPROVALS_PATH, archived)
    elif APPROVALS_PATH.exists():
        APPROVALS_PATH.unlink()

    # Manager events describe stock and orders in the old database, so archive them too.
    events_archived = None
    if EVENTS_PATH.exists() and json.loads(EVENTS_PATH.read_text() or "[]"):
        APPROVALS_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        events_archived = APPROVALS_ARCHIVE_DIR / f"manager_events_{stamp}.json"
        shutil.move(EVENTS_PATH, events_archived)

    state.runs = {}
    audit.record("database_reset", run_id="api", agent=None, database=str(WORKING_DB_PATH),
                 restored_from=str(ORIGINAL_DB_PATH), approvals_archived_to=str(archived) if archived else None,
                 manager_events_archived_to=str(events_archived) if events_archived else None)
    return ResetResult(
        message="Working database restored to the original. Approvals archived; audit trail kept.",
        database=str(WORKING_DB_PATH.relative_to(ROOT) if WORKING_DB_PATH.is_relative_to(ROOT) else WORKING_DB_PATH),
        restored_from=str(ORIGINAL_DB_PATH.relative_to(ROOT) if ORIGINAL_DB_PATH.is_relative_to(ROOT) else ORIGINAL_DB_PATH),
        approvals_archived_to=str(archived.relative_to(ROOT)) if archived and archived.is_relative_to(ROOT)
        else (str(archived) if archived else None),
    )
