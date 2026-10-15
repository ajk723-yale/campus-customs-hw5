"""Connects the agents to the Campus Customs FastMCP server (mcp_server/server.py).

- One MCP connection (stdio) is shared by the whole team.
- Each agent sees only the MCP tools listed for it in AGENT_TOOLS.
- Every MCP call goes through `audited_call`, which writes the call and its
  result to the audit trail and keeps the result so agent outputs can be
  checked against real data.
- execute_payment gets a second, backend-side gate: only the Accounting Agent
  may call it, and only for an approval ID the human passed into this run.
  The MCP server separately refuses anything a human hasn't approved.
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp.client.transports import StdioTransport
from pydantic_ai import RunContext
from pydantic_ai.mcp import CallToolFunc, MCPToolset

from backend import audit
from backend.config import MCP_PYTHON, MCP_SERVER_SCRIPT, ROOT
from backend.models import AgentName, TeamDeps, ToolObservation

READ_TICKETS = {"get_shop_date", "get_ticket"}
# Manager-recorded events (customer responses, pricing decisions, orders, receipts,
# fulfilment) are readable by these agents; none of them can create or change events.
READ_UPDATES = {"get_ticket_updates"}

# Human-only MCP tools: called by the backend's dashboard routes on a person's
# behalf, never by an agent. They are deliberately absent from AGENT_TOOLS, so
# audited_call blocks any agent attempt ("tool_blocked").
MANAGER_TOOLS = frozenset({
    "record_customer_response", "record_pricing_decision", "place_purchase_order", "cancel_purchase",
    "record_stock_receipt", "record_fulfilment", "set_ticket_status",
})

AGENT_TOOLS: dict[AgentName, frozenset[str]] = {
    "boss": frozenset(READ_TICKETS | READ_UPDATES | {"list_tickets", "list_payment_approvals"}),
    "inventory": frozenset(READ_TICKETS | READ_UPDATES | {
        "get_product_info", "get_product_sizes", "list_vendors", "get_vendor_status", "get_invoice_info",
        "request_purchase_approval",
    }),
    "accounting": frozenset(READ_TICKETS | READ_UPDATES | {
        "get_invoice_info", "list_open_invoices", "get_cash_position", "get_rent_info",
        "request_payment_approval", "list_payment_approvals", "execute_payment",
    }),
    "facilities": frozenset(READ_TICKETS | {"get_rent_info", "get_cash_position"}),
    "customer_service": frozenset(READ_TICKETS | READ_UPDATES | {"get_product_info", "get_product_sizes", "quote_price"}),
}

# Tools that create an approval request; the run's ticket_id is attached to them.
REQUEST_TOOLS = {"request_payment_approval", "request_purchase_approval"}

# Passed through to the server so tests can point it at scratch copies.
_PASSTHROUGH_ENV = ("CAMPUS_DB_PATH", "CAMPUS_APPROVALS_PATH", "CAMPUS_MANAGER_EVENTS_PATH")


def _unwrap(result: Any) -> Any:
    """FastMCP wraps list results as {"result": [...]}; return the plain value."""
    if isinstance(result, dict) and set(result) == {"result"}:
        return result["result"]
    return result


async def audited_call(ctx: RunContext[TeamDeps], call_tool: CallToolFunc, name: str, args: dict[str, Any]) -> Any:
    deps = ctx.deps
    where = dict(run_id=deps.run_id, agent=deps.agent, depth=deps.depth, path=deps.path)

    if name not in AGENT_TOOLS[deps.agent]:
        audit.record("tool_blocked", **where, tool=name, args=args, reason="tool not allowed for this agent")
        return {"error": f"{name} is not available to the {deps.agent} agent."}

    if name == "execute_payment":
        approval_id = args.get("approval_id")
        if deps.agent != "accounting" or approval_id not in deps.human_approved_payment_ids:
            reason = ("only the Accounting Agent may execute payments" if deps.agent != "accounting"
                      else f"approval {approval_id!r} was not authorized by a human for this run")
            audit.record("payment_blocked", **where, tool=name, args=args, reason=reason)
            return {"executed": False, "error": f"Blocked by the backend: {reason}."}

    if name in REQUEST_TOOLS and deps.ticket_id is not None and args.get("ticket_id") is None:
        args = {**args, "ticket_id": deps.ticket_id}

    audit.record("tool_call", **where, tool=name, args=args)
    try:
        result = _unwrap(await call_tool(name, args))
    except Exception as exc:
        audit.record("tool_error", **where, tool=name, args=args, error=str(exc))
        raise
    audit.record("tool_result", **where, tool=name, result=result)
    deps.budget.observations.append(ToolObservation(deps.agent, name, args, result))

    if name in REQUEST_TOOLS:
        event = "approval_requested" if isinstance(result, dict) and result.get("created") else "approval_request_refused"
        audit.record(event, **where, request=args, result=result)
    elif name == "execute_payment":
        event = "payment_executed" if isinstance(result, dict) and result.get("executed") else "payment_refused"
        audit.record(event, **where, approval_id=args.get("approval_id"), result=result)
    return result


def build_toolset() -> MCPToolset:
    """A toolset that launches mcp_server/server.py over stdio with the project's .venv Python."""
    env = {k: os.environ[k] for k in _PASSTHROUGH_ENV if k in os.environ}
    transport = StdioTransport(
        command=str(MCP_PYTHON),
        args=[str(MCP_SERVER_SCRIPT)],
        cwd=str(ROOT),
        env=env or None,
    )
    return MCPToolset(transport, id="campus-customs", process_tool_call=audited_call, tool_error_behavior="retry")


def tools_for(toolset: MCPToolset, agent: AgentName):
    """The shared toolset, narrowed to the tools this agent may use."""
    allowed = AGENT_TOOLS[agent]
    return toolset.filtered(lambda ctx, tool_def: tool_def.name in allowed)


assert not any(MANAGER_TOOLS & tools for tools in AGENT_TOOLS.values()), "agents must never get manager tools"
