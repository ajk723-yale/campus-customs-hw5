"""The five Campus Customs agents and how they delegate to each other.

Every agent is a PydanticAI Agent on gpt-6-luna (Portkey) with:
  - its system prompt from backend/prompts/<name>.md
  - only its own MCP tools (backend/mcp_client.AGENT_TOOLS)
  - a structured output type (backend/models.py)
  - a delegation tool for the agents it may hand work to (DELEGATES)
  - an output validator that checks its numbers against MCP results seen in this run

Delegation runs the target agent as a nested run. Limits: depth (Boss = 0),
number of delegations per team run, no delegating back to an agent already in
the chain, per-agent request/tool/token limits, and a shared team budget.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimitExceeded, UsageLimits
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.usage import RunUsage

from backend import audit
from backend.config import (
    AGENT_REQUEST_LIMIT, AGENT_TOOL_CALLS_LIMIT, AGENT_TOTAL_TOKENS_LIMIT, MAX_DELEGATION_DEPTH,
    MAX_DELEGATIONS_PER_RUN, MODEL_NAME, MODEL_SETTINGS, PROMPTS_DIR, TEAM_REQUEST_LIMIT,
    TEAM_TOTAL_TOKENS_LIMIT, get_model,
)
from backend.mcp_client import build_toolset, tools_for
from backend.models import (
    REPORT_TYPES, AccountingReport, AgentName, BossDecision, CustomerServiceReport, FacilitiesReport,
    InventoryReport, TeamBudget, TeamDeps,
)

# Who may hand work to whom. Accounting is the end of every chain.
DELEGATES: dict[AgentName, tuple[AgentName, ...]] = {
    "boss": ("inventory", "accounting", "facilities", "customer_service"),
    "inventory": ("accounting",),
    "facilities": ("accounting",),
    "customer_service": ("inventory", "accounting"),
    "accounting": (),
}

AGENT_TITLES: dict[AgentName, str] = {
    "boss": "Boss Agent",
    "inventory": "Inventory Agent",
    "accounting": "Accounting Agent",
    "facilities": "Facilities Agent",
    "customer_service": "Customer Service Agent",
}


class TeamBudgetExceeded(RuntimeError):
    """The shared team request or token budget is used up."""


# --------------------------------------------------------------------------
# Facts seen through MCP in this run (used by the output validators)
# --------------------------------------------------------------------------

def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)


def _seen_dicts(deps: TeamDeps):
    for obs in deps.budget.observations:
        yield from _walk(obs.result)


def _seen_balances(deps: TeamDeps) -> set[float]:
    found = set()
    for d in _seen_dicts(deps):
        if "checking_balance" in d and d["checking_balance"] is not None:
            found.add(round(d["checking_balance"], 2))
        if d.get("name") == "checking" and "balance" in d:
            found.add(round(d["balance"], 2))
    return found


def _seen_amounts(deps: TeamDeps) -> set[float]:
    return {round(d[k], 2) for d in _seen_dicts(deps) for k in ("amount", "monthly_rent")
            if isinstance(d.get(k), int | float)}


def _seen_pricing(deps: TeamDeps) -> dict[str, tuple[float, float]]:
    return {d["sku"]: (d["unit_cost"], d["list_price"]) for d in _seen_dicts(deps)
            if "sku" in d and d.get("unit_cost") is not None and d.get("list_price") is not None}


def _seen_stock(deps: TeamDeps) -> dict[tuple[str, str], int]:
    stock = {}
    for d in _seen_dicts(deps):
        if "sku" in d and "size" in d and isinstance(d.get("qty"), int):
            stock[(d["sku"], d["size"])] = d["qty"]
        if "sku" in d and isinstance(d.get("sizes"), list):
            for s in d["sizes"]:
                stock[(d["sku"], s["size"])] = s["qty"]
    return stock


def _seen_days_until_due(deps: TeamDeps) -> dict[int, int]:
    """Days until rent is due per lease, as calculated by MCP from desk.date_today."""
    days = {}
    for obs in deps.budget.observations:
        if obs.tool == "get_rent_info" and isinstance(obs.result, dict) and "days_until_due" in obs.result:
            days[obs.result["lease_id"]] = obs.result["days_until_due"]
        elif obs.tool == "get_cash_position" and isinstance(obs.result, dict):
            for lease in obs.result.get("upcoming_rent", []):
                days[lease["id"]] = lease["days_until_due"]
    return days


def _seen_payment_requests(deps: TeamDeps) -> tuple[dict[str, tuple[str, int]], set[tuple[str, int]]]:
    """Payment requests Accounting filed (or found already filed) in this run, and refused attempts.

    Returns ({approval_id: (kind, ref_id)} for open requests, {(kind, ref_id)} refused with no request on file).
    """
    known: dict[str, tuple[str, int]] = {}
    refused: set[tuple[str, int]] = set()
    for obs in deps.budget.observations:
        r = obs.result
        if obs.tool == "request_payment_approval" and isinstance(r, dict):
            if r.get("created"):
                known[r["approval_id"]] = (r["kind"], r["ref_id"])
            elif isinstance(r.get("existing"), dict):
                e = r["existing"]
                known[e["approval_id"]] = (e["kind"], e["ref_id"])
            else:
                refused.add((obs.args.get("kind"), obs.args.get("ref_id")))
        elif obs.tool == "list_payment_approvals" and isinstance(r, list):
            for e in r:
                if e.get("kind") in ("invoice", "rent") and e.get("status") in ("pending", "approved"):
                    known[e["approval_id"]] = (e["kind"], e["ref_id"])
    return known, refused


def _check_boss_resolution(deps: TeamDeps, output: BossDecision) -> None:
    """The Boss may resolve a ticket only after verifying, in this run, that everything the shop can do now is done.

    Resolved = all actions currently possible are completed, required human
    decisions are made, and (for customer tickets) a reply is drafted. Future
    deliveries and customer responses are follow-ups, not blockers. Checked
    from get_ticket_updates:
      - no approval for the ticket is still pending, approved-but-unexecuted
        (payments) or approved-but-not-ordered/cancelled (purchases);
      - no unpaid vendor invoice tied to the ticket (its own linked invoice or
        a bill created by ordering its purchase): it must be paid through
        Accounting and human approval first, so a cash shortfall blocks;
      - customer order: any shortfall is covered by stock on hand, the ticket's
        paid linked invoice for that item, or an ordered/received purchase;
      - price request: a pricing decision is recorded;
      - customer tickets: Customer Service drafted a reply in this run (unless
        the order is already fulfilled and the customer's response recorded).
    """
    updates = {o.result["ticket_id"]: o.result for o in deps.budget.observations
               if o.tool == "get_ticket_updates" and isinstance(o.result, dict) and o.result.get("found")}
    for d in output.ticket_decisions:
        if d.resolution != "resolved":
            continue
        u = updates.get(d.ticket_id)
        if u is None:
            raise ModelRetry(f"Call get_ticket_updates({d.ticket_id}) and check every step before resolving it.")
        missing = []
        purchases = u.get("purchases", [])
        payments = u.get("payments", [])
        pending = [a["approval_id"] for a in purchases + payments if a["status"] == "pending"]
        if pending:
            missing.append(f"waiting for a human decision on {', '.join(pending)}")
        unpaid_payments = [a["approval_id"] for a in payments if a["status"] == "approved"]
        if unpaid_payments:
            missing.append(f"{', '.join(unpaid_payments)} approved but not yet paid")
        undecided = [a["approval_id"] for a in purchases if a["status"] == "approved"]
        if undecided:
            missing.append(f"{', '.join(undecided)} approved but neither ordered nor cancelled")
        cash = u.get("cash") or {}
        for inv in u.get("unpaid_vendor_invoices") or []:
            short = inv["amount"] > (cash.get("checking_balance") or 0)
            missing.append(f"vendor invoice {inv['invoice_id']} (${inv['amount']:,.2f}) is unpaid"
                           + (f" and checking holds only ${cash.get('checking_balance', 0):,.2f}" if short else
                              "; Accounting must request payment and a human approve it"))
        req = u.get("requested") or {}
        kind = u.get("ticket_type")
        still = u.get("quantity_still_to_fulfil") or 0
        if kind == "customer_order" and req.get("sku") and still > 0 and (u.get("on_hand") or 0) < still:
            link = u.get("linked_invoice") or {}
            covered = (link.get("covers_requested_item") and link.get("status") == "paid") or any(
                a["status"] in ("ordered", "received") and a.get("sku") == req["sku"] and a.get("size") == req["size"]
                for a in purchases)
            if not covered:
                missing.append("the shortfall has no restock secured (no paid linked invoice for the item and no ordered purchase)")
        if kind == "price_override" and not u.get("latest_pricing_decision"):
            missing.append("no pricing decision is recorded")
        if kind in ("customer_order", "price_override"):
            fulfilled_and_answered = still == 0 and u.get("latest_customer_response")
            drafted = any(getattr(r, "agent", None) == "customer_service"
                          and any(dr.ticket_id == d.ticket_id for dr in getattr(r, "draft_responses", []))
                          for r in deps.budget.reports)
            if not (drafted or fulfilled_and_answered):
                missing.append("no customer reply was drafted in this run (delegate to customer_service)")
        if missing:
            raise ModelRetry(f"Ticket {d.ticket_id} can't be resolved yet: {'; '.join(missing)}. "
                             "List these in remaining_actions (or as follow-ups only if they are future events).")


def _check_boss_payment_requests(deps: TeamDeps, output: BossDecision) -> None:
    """Accounting files payment requests; the Boss only reports the IDs Accounting produced."""
    known, refused = _seen_payment_requests(deps)
    for p in output.payments_needing_human_approval:
        if p.approval_id:
            if known.get(p.approval_id) != (p.kind, p.ref_id):
                raise ModelRetry(f"{p.approval_id} is not a payment request Accounting filed for {p.kind} {p.ref_id} "
                                 "in this run. Use only approval IDs from Accounting's report.")
        elif (p.kind, p.ref_id) not in refused:
            raise ModelRetry(f"Payment {p.kind} {p.ref_id} has no approval_id. Delegate to accounting to file it with "
                             "request_payment_approval and include the approval_id it returns. (Leave approval_id "
                             "empty only if Accounting's request was refused.)")
    for d in output.ticket_decisions:
        for approval_id in d.resolves_when_payments_executed:
            if approval_id not in known:
                raise ModelRetry(f"resolves_when_payments_executed lists {approval_id}, which is not a payment request "
                                 "Accounting filed in this run. Purchases never resolve a ticket.")


def _executed_ids(deps: TeamDeps) -> set[str]:
    return {o.result["approval_id"] for o in deps.budget.observations
            if o.tool == "execute_payment" and isinstance(o.result, dict) and o.result.get("executed")}


def _check_amounts(deps: TeamDeps, amounts: list[float], what: str) -> None:
    seen = _seen_amounts(deps)
    unknown = [a for a in amounts if round(a, 2) not in seen]
    if unknown:
        raise ModelRetry(f"{what} {unknown} did not come from any MCP result in this run. "
                         "Use only amounts returned by the MCP tools (or reported by the specialist who looked them up).")


def _validate(ctx: RunContext[TeamDeps], output: BaseModel) -> BaseModel:
    """Reject outputs whose key numbers weren't seen through MCP in this run."""
    deps = ctx.deps
    if isinstance(output, AccountingReport):
        balances = _seen_balances(deps)
        if not balances:
            raise ModelRetry("Call get_cash_position (or get_rent_info) before reporting cash_available.")
        allowed = balances | {round(b - sum(o.result["amount"] for o in deps.budget.observations
                                            if o.tool == "execute_payment" and isinstance(o.result, dict)
                                            and o.result.get("executed")), 2) for b in balances}
        if round(output.cash_available, 2) not in allowed:
            raise ModelRetry(f"cash_available {output.cash_available} doesn't match the checking balance "
                             f"returned by MCP ({sorted(balances)}).")
        _check_amounts(deps, [p.amount for p in output.payment_plan], "Payment amounts")
        if unknown := set(output.payments_executed) - _executed_ids(deps):
            raise ModelRetry(f"payments_executed lists {sorted(unknown)}, but execute_payment did not succeed for them.")
    elif isinstance(output, FacilitiesReport):
        _check_amounts(deps, [r.amount for r in output.rent_obligations], "Rent amounts")
        days = _seen_days_until_due(deps)
        for r in output.rent_obligations:
            if r.lease_id not in days:
                raise ModelRetry(f"Call get_rent_info({r.lease_id}) to get days_until_due before assessing urgency.")
            if r.days_until_due != days[r.lease_id]:
                raise ModelRetry(f"days_until_due for lease {r.lease_id} must be {days[r.lease_id]} "
                                 "(next_due minus desk.date_today, as returned by get_rent_info).")
    elif isinstance(output, InventoryReport):
        stock = _seen_stock(deps)
        for plan in output.replenishment_plans:
            if stock.get((plan.sku, plan.size)) != plan.on_hand:
                raise ModelRetry(f"on_hand for {plan.sku} {plan.size} must match get_product_info "
                                 f"(seen: {stock.get((plan.sku, plan.size))}).")
    elif isinstance(output, CustomerServiceReport):
        pricing = _seen_pricing(deps)
        for rec in output.pricing_recommendations:
            if rec.sku not in pricing:
                raise ModelRetry(f"Look up {rec.sku} with get_product_info or quote_price before pricing it.")
            cost, price = pricing[rec.sku]
            if (round(rec.unit_cost, 2), round(rec.list_price, 2)) != (round(cost, 2), round(price, 2)):
                raise ModelRetry(f"{rec.sku}: unit_cost/list_price must be {cost}/{price} as returned by MCP.")
    elif isinstance(output, BossDecision):
        _check_amounts(deps, [p.amount for p in output.payments_needing_human_approval],
                       "Payment amounts for human approval")
        _check_boss_payment_requests(deps, output)
        _check_boss_resolution(deps, output)
    return output


# --------------------------------------------------------------------------
# The team
# --------------------------------------------------------------------------

class CampusTeam:
    """Builds the five agents around one shared MCP connection.

    Use as `async with CampusTeam() as team:` so the MCP server starts once
    and stops when you're done.
    """

    def __init__(self, toolset: MCPToolset | None = None):
        self.toolset = toolset or build_toolset()
        self.agents: dict[AgentName, Agent[TeamDeps, BaseModel]] = {name: self._build(name) for name in REPORT_TYPES}

    async def __aenter__(self) -> CampusTeam:
        await self.toolset.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.toolset.__aexit__(*exc)

    # ---- building -------------------------------------------------------

    def _build(self, name: AgentName) -> Agent[TeamDeps, BaseModel]:
        agent: Agent[TeamDeps, BaseModel] = Agent(
            get_model(),
            name=name,
            deps_type=TeamDeps,
            output_type=REPORT_TYPES[name],
            instructions=(PROMPTS_DIR / f"{name}.md").read_text(),
            toolsets=[tools_for(self.toolset, name)],
            model_settings=MODEL_SETTINGS,
            retries=2,
        )
        agent.output_validator(_validate)
        if DELEGATES[name]:
            self._add_delegation_tool(agent, name)
        return agent

    def _add_delegation_tool(self, agent: Agent[TeamDeps, BaseModel], name: AgentName) -> None:
        targets = DELEGATES[name]
        Target = Literal[targets]  # type: ignore[valid-type]
        team = self

        async def delegate(ctx: RunContext[TeamDeps], to: Target, task: str, ticket_ids: list[int]) -> dict:
            """Hand a task to another agent and get its structured report back.

            Args:
                to: The agent to delegate to.
                task: What you need, with any facts or numbers they should use.
                ticket_ids: Ticket IDs this task is about (empty list if none).
            """
            return await team.delegate(ctx, to, task, ticket_ids)

        # Real types (not strings) so PydanticAI can build the tool schema from this closure.
        delegate.__annotations__ = {"ctx": RunContext[TeamDeps], "to": Target, "task": str,
                                    "ticket_ids": list[int], "return": dict}
        tool_name = "delegate_to_specialist" if name == "boss" else "consult_agent"
        agent.tool(delegate, name=tool_name,
                   description=f"Delegate a task to one of: {', '.join(targets)}. Returns that agent's report.")

    # ---- running --------------------------------------------------------

    async def run_agent(self, name: AgentName, prompt: str, deps: TeamDeps) -> BaseModel:
        """Run one agent with its own limits, inside the shared team budget."""
        budget = deps.budget
        requests_left = TEAM_REQUEST_LIMIT - budget.usage.requests
        tokens_left = TEAM_TOTAL_TOKENS_LIMIT - budget.usage.total_tokens
        if requests_left <= 0 or tokens_left <= 0:
            raise TeamBudgetExceeded(
                f"team budget used up ({budget.usage.requests} requests, {budget.usage.total_tokens} tokens)")
        limits = UsageLimits(
            request_limit=min(AGENT_REQUEST_LIMIT, requests_left),
            tool_calls_limit=AGENT_TOOL_CALLS_LIMIT,
            total_tokens_limit=min(AGENT_TOTAL_TOKENS_LIMIT, tokens_left),
        )
        where = dict(run_id=deps.run_id, agent=name, depth=deps.depth, path=deps.path)
        audit.record("agent_started", **where, model=MODEL_NAME, prompt=prompt,
                     limits=dict(requests=limits.request_limit, tool_calls=limits.tool_calls_limit,
                                 total_tokens=limits.total_tokens_limit))
        usage = RunUsage()
        try:
            result = await self.agents[name].run(prompt, deps=deps, usage_limits=limits, usage=usage)
        except Exception as exc:
            audit.record("agent_failed", **where, error_type=type(exc).__name__, error=str(exc),
                         usage=_usage_dict(usage))
            raise
        finally:
            budget.usage.incr(usage)
        audit.record("agent_finished", **where, output=result.output, usage=_usage_dict(usage))
        if name == "boss":
            audit.record("decision", **where, decision=result.output)
        return result.output

    async def delegate(self, ctx: RunContext[TeamDeps], to: AgentName, task: str, ticket_ids: list[int]) -> dict:
        deps, budget = ctx.deps, ctx.deps.budget
        where = dict(run_id=deps.run_id, agent=deps.agent, depth=deps.depth, path=deps.path)
        refusal = None
        if to not in DELEGATES[deps.agent]:
            refusal = f"{deps.agent} may not delegate to {to}"
        elif to == deps.agent or to in deps.path:
            refusal = f"{to} is already working on this chain ({' -> '.join((*deps.path, deps.agent))}); no loops"
        elif deps.depth + 1 > MAX_DELEGATION_DEPTH:
            refusal = f"maximum delegation depth {MAX_DELEGATION_DEPTH} reached"
        elif budget.delegations >= MAX_DELEGATIONS_PER_RUN:
            refusal = f"maximum of {MAX_DELEGATIONS_PER_RUN} delegations per run reached"
        if refusal:
            audit.record("delegation_refused", **where, to=to, task=task, ticket_ids=ticket_ids, reason=refusal)
            return {"delegated": False, "error": refusal + ". Work with what you have."}

        budget.delegations += 1
        audit.record("delegation_started", **where, to=to, task=task, ticket_ids=ticket_ids,
                     delegation_number=budget.delegations)
        prompt = (f"Task from the {AGENT_TITLES[deps.agent]}"
                  f"{' about ticket(s) ' + ', '.join(map(str, ticket_ids)) if ticket_ids else ''}:\n{task}")
        try:
            report = await self.run_agent(to, prompt, deps.child(to))
        except (UsageLimitExceeded, TeamBudgetExceeded) as exc:
            audit.record("delegation_failed", **where, to=to, error=str(exc))
            return {"delegated": True, "completed": False,
                    "error": f"{to} stopped at its limit: {exc}. Decide with the information you have."}
        audit.record("delegation_result", **where, to=to, report=report)
        budget.reports.append(report)
        return {"delegated": True, "completed": True, "report": report.model_dump(mode="json")}


def new_run_id() -> str:
    return "run-" + uuid.uuid4().hex[:12]


def _usage_dict(usage: RunUsage) -> dict:
    return {"requests": usage.requests, "tool_calls": usage.tool_calls, "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens, "total_tokens": usage.total_tokens}


async def run_team(task: str, *, entry_agent: AgentName = "boss",
                   human_approved_payment_ids: list[str] | tuple[str, ...] = (),
                   team: CampusTeam | None = None, run_id: str | None = None,
                   ticket_id: int | None = None) -> tuple[str, BaseModel]:
    """Run one team task starting at `entry_agent` (normally the Boss).

    `human_approved_payment_ids` is how a person authorizes execution of
    payments they already approved (dashboard or scripts/approve_payment.py).
    Leave it empty and no payment can be executed in this run. `ticket_id`
    links the run, and any approval requests it files, to a ticket.
    Returns (run_id, output).
    """
    run_id = run_id or new_run_id()
    deps = TeamDeps(run_id=run_id, agent=entry_agent, budget=TeamBudget(),
                    human_approved_payment_ids=frozenset(human_approved_payment_ids), ticket_id=ticket_id)
    audit.record("run_started", run_id=run_id, agent=entry_agent, depth=0, task=task, model=MODEL_NAME,
                 ticket_id=ticket_id,
                 human_approved_payment_ids=sorted(deps.human_approved_payment_ids),
                 limits=dict(team_requests=TEAM_REQUEST_LIMIT, team_total_tokens=TEAM_TOTAL_TOKENS_LIMIT,
                             agent_requests=AGENT_REQUEST_LIMIT, agent_tool_calls=AGENT_TOOL_CALLS_LIMIT,
                             agent_total_tokens=AGENT_TOTAL_TOKENS_LIMIT, max_depth=MAX_DELEGATION_DEPTH,
                             max_delegations=MAX_DELEGATIONS_PER_RUN))

    async def go(t: CampusTeam) -> BaseModel:
        return await t.run_agent(entry_agent, task, deps)

    try:
        if team is None:
            async with CampusTeam() as t:
                output = await go(t)
        else:
            output = await go(team)
    except Exception as exc:
        audit.record("run_failed", run_id=run_id, agent=entry_agent, depth=0, error_type=type(exc).__name__,
                     error=str(exc), usage=_usage_dict(deps.budget.usage), delegations=deps.budget.delegations)
        raise
    audit.record("run_finished", run_id=run_id, agent=entry_agent, depth=0,
                 usage=_usage_dict(deps.budget.usage), delegations=deps.budget.delegations)
    return run_id, output
