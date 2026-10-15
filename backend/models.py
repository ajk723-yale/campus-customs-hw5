"""Data types for the Campus Customs agent team.

- TeamDeps / TeamBudget: what every agent run carries (who it is, how deep in the
  delegation chain, the shared budget, and the payments a human has approved).
- One structured output per agent. Validators reject outputs that break shop
  rules (negative cash, prices below cost, "sent" customer messages, ...), and
  PydanticAI sends the error back to the model to fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_ai.usage import RunUsage

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
Priority = Literal["high", "medium", "low"]

MONEY_TOLERANCE = 0.01


# --------------------------------------------------------------------------
# Run state shared by the team
# --------------------------------------------------------------------------

@dataclass
class ToolObservation:
    """One MCP tool result seen during the run, kept so outputs can be checked against real data."""

    agent: AgentName
    tool: str
    args: dict[str, Any]
    result: Any


@dataclass
class TeamBudget:
    """Shared by every agent in one team run."""

    usage: RunUsage = field(default_factory=RunUsage)
    delegations: int = 0
    observations: list[ToolObservation] = field(default_factory=list)
    # Structured reports specialists returned in this run (e.g. Customer Service's drafted replies).
    reports: list[Any] = field(default_factory=list)

    def results(self, tool: str) -> list[Any]:
        return [o.result for o in self.observations if o.tool == tool and isinstance(o.result, dict | list)]


@dataclass
class TeamDeps:
    """Passed to every agent run as `ctx.deps`."""

    run_id: str
    agent: AgentName
    depth: int = 0
    path: tuple[AgentName, ...] = ()
    budget: TeamBudget = field(default_factory=TeamBudget)
    # Approval IDs a human explicitly authorized for execution in this run.
    # Empty unless the person starting the run passes them in.
    human_approved_payment_ids: frozenset[str] = frozenset()
    # The ticket this run is about, if any. Approval requests filed during the
    # run are linked to it automatically.
    ticket_id: int | None = None

    def child(self, agent: AgentName) -> TeamDeps:
        return TeamDeps(
            run_id=self.run_id,
            agent=agent,
            depth=self.depth + 1,
            path=(*self.path, self.agent),
            budget=self.budget,
            human_approved_payment_ids=self.human_approved_payment_ids,
            ticket_id=self.ticket_id,
        )


# --------------------------------------------------------------------------
# Pieces shared by the reports
# --------------------------------------------------------------------------

class Finding(BaseModel):
    ticket_id: int | None = Field(None, description="Ticket this fact relates to, if any")
    fact: str = Field(description="A fact taken from an MCP tool result")
    source_tool: str = Field(description="Name of the MCP tool (or agent) the fact came from")


class Recommendation(BaseModel):
    ticket_id: int | None = None
    action: str
    rationale: str
    priority: Priority


class Escalation(BaseModel):
    to: Literal["boss", "human"]
    reason: str


class SpecialistReport(BaseModel):
    """Fields every specialist returns to the agent that delegated to it."""

    agent: AgentName
    summary: str = Field(description="Two or three sentences for the Boss")
    findings: list[Finding] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    escalations: list[Escalation] = Field(default_factory=list)
    consulted_agents: list[AgentName] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Inventory Agent
# --------------------------------------------------------------------------

class ReplenishmentPlan(BaseModel):
    ticket_id: int | None = None
    sku: str
    size: str
    on_hand: int
    needed: int
    shortfall: int = Field(ge=0)
    proposed_order_qty: int = Field(ge=0)
    vendor_id: int | None = None
    vendor_name: str | None = None
    lead_days: int | None = None
    vendor_restricted: bool
    restriction_reason: str | None = None
    can_order_now: bool
    order_placed: Literal[False] = Field(False, description="Always false: Inventory only proposes orders")

    @model_validator(mode="after")
    def check_rules(self) -> ReplenishmentPlan:
        if self.shortfall != max(self.needed - self.on_hand, 0):
            raise ValueError(f"shortfall must be max(needed - on_hand, 0) = {max(self.needed - self.on_hand, 0)}")
        if self.vendor_restricted and self.can_order_now:
            raise ValueError("A restricted vendor (any unpaid invoice) cannot take an order: set can_order_now=false")
        return self


class InventoryReport(SpecialistReport):
    agent: Literal["inventory"] = "inventory"
    replenishment_plans: list[ReplenishmentPlan] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Accounting Agent
# --------------------------------------------------------------------------

class PaymentPlanItem(BaseModel):
    kind: Literal["invoice", "rent"]
    ref_id: int = Field(description="Invoice id or lease id")
    payee: str
    amount: float = Field(gt=0)
    due_date: str
    priority: int = Field(ge=1, description="1 = pay first")
    recommendation: Literal["pay_now", "pay_by_due_date", "defer", "do_not_pay"]
    approval_id: str | None = None
    approval_status: Literal["not_requested", "pending", "approved", "rejected", "executed"] = "not_requested"


class AccountingReport(SpecialistReport):
    agent: Literal["accounting"] = "accounting"
    cash_available: float = Field(description="Checking balance from get_cash_position or get_rent_info")
    payment_plan: list[PaymentPlanItem] = Field(default_factory=list)
    cash_after_plan: float = Field(
        description="cash_available minus every pay_now / pay_by_due_date item. No expected revenue is added."
    )
    payments_executed: list[str] = Field(default_factory=list, description="Approval IDs executed this run")

    @model_validator(mode="after")
    def check_cash(self) -> AccountingReport:
        planned = sum(p.amount for p in self.payment_plan if p.recommendation in ("pay_now", "pay_by_due_date"))
        expected = round(self.cash_available - planned, 2)
        if abs(self.cash_after_plan - expected) > MONEY_TOLERANCE:
            raise ValueError(
                f"cash_after_plan must equal cash_available - planned payments = {expected}; "
                "do not add expected sales or any other revenue"
            )
        if self.cash_after_plan < 0:
            raise ValueError("The payment plan would make cash negative; defer some payments")
        return self


# --------------------------------------------------------------------------
# Facilities Agent
# --------------------------------------------------------------------------

class RentObligation(BaseModel):
    lease_id: int
    space_name: str
    landlord: str
    amount: float
    due_date: str
    days_until_due: int = Field(
        description="next_due minus desk.date_today, exactly as get_rent_info returns it (negative = past due)"
    )
    already_paid: bool
    urgency: str = Field(
        description="Your own assessment of how urgent this rent is, judged from days_until_due, "
                    "whether it is already paid, and the cash available"
    )
    urgency_reasoning: str = Field(description="Why you judged it that way, citing the numbers")
    notice_matches_lease: bool | None = Field(
        None, description="Whether the rent notice ticket agrees with the lease record"
    )


class FacilitiesReport(SpecialistReport):
    agent: Literal["facilities"] = "facilities"
    rent_obligations: list[RentObligation] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Customer Service Agent
# --------------------------------------------------------------------------

class PricingRecommendation(BaseModel):
    ticket_id: int
    sku: str
    size: str | None = None
    quantity_requested: int
    quantity_available_now: int
    list_price: float
    unit_cost: float
    proposed_unit_price: float
    discount_pct: float = Field(ge=0, lt=100)
    margin_per_unit: float
    needs_boss_approval: Literal[True] = True

    @model_validator(mode="after")
    def check_price(self) -> PricingRecommendation:
        if self.proposed_unit_price < self.unit_cost:
            raise ValueError("proposed_unit_price is below unit_cost; the shop never sells below cost")
        if abs(self.margin_per_unit - (self.proposed_unit_price - self.unit_cost)) > MONEY_TOLERANCE:
            raise ValueError("margin_per_unit must equal proposed_unit_price - unit_cost")
        return self


class CustomerResponseDraft(BaseModel):
    ticket_id: int
    recipient: str
    message: str
    sent: Literal[False] = Field(False, description="Always false: drafts are never sent to real customers")


class CustomerServiceReport(SpecialistReport):
    agent: Literal["customer_service"] = "customer_service"
    pricing_recommendations: list[PricingRecommendation] = Field(default_factory=list)
    draft_responses: list[CustomerResponseDraft] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Boss Agent
# --------------------------------------------------------------------------

class TicketDecision(BaseModel):
    ticket_id: int
    priority: int = Field(ge=1, description="1 = handle first")
    decision: str
    owner: AgentName
    status: Literal["proposed", "awaiting_human_approval", "blocked", "needs_more_info", "no_action"]
    next_steps: list[str] = Field(default_factory=list)
    resolution: Literal["resolved", "awaiting_human", "open"] = Field(
        description="resolved = the ticket's request is fully handled and nothing else is needed; "
                    "awaiting_human = only human decisions remain; open = other work remains"
    )
    remaining_actions: list[str] = Field(
        default_factory=list,
        description="Everything still needed besides approving the payments in resolves_when_payments_executed "
                    "(e.g. restock arrival, customer reply, discount sign-off). Empty only if nothing else is needed.",
    )
    resolves_when_payments_executed: list[str] = Field(
        default_factory=list,
        description="Payment approval IDs (filed by Accounting) whose execution, with nothing else remaining, "
                    "fully resolves this ticket. Never purchase IDs.",
    )

    @model_validator(mode="after")
    def check_resolution(self) -> TicketDecision:
        if self.resolution == "resolved":
            if self.remaining_actions or self.resolves_when_payments_executed:
                raise ValueError("A resolved ticket can't have remaining_actions or payments still to execute")
            if self.status in ("awaiting_human_approval", "blocked", "needs_more_info"):
                raise ValueError(f"status {self.status!r} contradicts resolution 'resolved'")
        if self.resolves_when_payments_executed:
            if self.remaining_actions:
                raise ValueError("Paying can only resolve the ticket if nothing else remains: either list no "
                                 "remaining_actions or leave resolves_when_payments_executed empty")
            if self.resolution != "awaiting_human":
                raise ValueError("Use resolution 'awaiting_human' when the ticket waits only on payment approvals")
        return self


class PaymentForHumanApproval(BaseModel):
    kind: Literal["invoice", "rent"]
    ref_id: int
    payee: str
    amount: float = Field(gt=0)
    reason: str
    approval_id: str | None = Field(
        None,
        description="The approval ID Accounting filed for this payment in this run. Leave empty only if "
                    "Accounting tried to file it and the request was refused (say why in reason).",
    )


class BossDecision(BaseModel):
    summary: str
    ticket_decisions: list[TicketDecision] = Field(default_factory=list)
    payments_needing_human_approval: list[PaymentForHumanApproval] = Field(default_factory=list)
    consulted_agents: list[AgentName] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


REPORT_TYPES: dict[AgentName, type[BaseModel]] = {
    "boss": BossDecision,
    "inventory": InventoryReport,
    "accounting": AccountingReport,
    "facilities": FacilitiesReport,
    "customer_service": CustomerServiceReport,
}


# --------------------------------------------------------------------------
# FastAPI request / response bodies (backend/main.py)
# --------------------------------------------------------------------------

RunStatus = Literal["running", "finished", "failed"]


class TicketView(BaseModel):
    id: int
    type: str
    requester: str
    subject: str
    sku: str | None = None
    size: str | None = None
    qty: int | None = None
    lease_id: int | None = None
    invoice_id: int | None = None
    status: str = Field(description="From the tickets table: 'open' or 'resolved'")
    notes: str | None = None
    created_at: str
    running: bool = Field(description="An agent run on this ticket is in progress")
    last_run_id: str | None = None
    last_run_status: RunStatus | None = None
    pending_approvals: int = Field(0, description="Requests for this ticket waiting for a human decision")
    resolution: Literal["resolved", "awaiting_human", "open"] | None = Field(
        None, description="The Boss's resolution in the latest finished run")
    remaining_actions: list[str] = Field(default_factory=list, description="What the Boss said is still needed")
    next_step: str = Field(description="Plain-language next step for the dashboard")


class RunView(BaseModel):
    run_id: str
    kind: Literal["ticket", "payment_execution", "other"] = Field(
        description="ticket = Boss run on a ticket; payment_execution = Accounting executing a human-approved "
                    "payment; other = runs without a ticket (e.g. connection tests)")
    ticket_id: int | None = None
    approval_id: str | None = None
    status: RunStatus
    started_at: str
    finished_at: str | None = None
    error: str | None = None
    output: dict[str, Any] | None = Field(None, description="BossDecision (ticket runs) or AccountingReport")


class RunStarted(BaseModel):
    run_id: str
    status: RunStatus = "running"
    message: str


class EventView(BaseModel):
    """One audit-trail record, with a plain-language line for the dashboard."""

    timestamp: str
    run_id: str
    ticket_id: int | None = None
    agent: str | None = None
    depth: int | None = None
    event: str
    category: Literal["run", "message", "delegation", "tool", "approval", "payment", "error", "manager"]
    text: str
    tool: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class HumanDecision(BaseModel):
    approver: str = Field(min_length=1, description="Name of the person deciding")
    confirm_approval_id: str = Field(description="Must equal the approval ID, as a deliberate confirmation")
    reason: str = Field("", max_length=500, description="Optional: why. Agents read rejection reasons.")


class DecisionEffects(BaseModel):
    """What a human decision actually did."""

    decision_recorded: bool = True
    payment_execution_started: bool = False
    order_placed: Literal[False] = False
    cash_changed_now: Literal[False] = Field(
        False, description="Approving never moves money itself; an approved payment is paid by the Accounting run")
    inventory_changed: Literal[False] = False


class DecisionResult(BaseModel):
    approval: dict[str, Any]
    message: str
    effects: DecisionEffects
    execution_run_id: str | None = Field(None, description="Accounting run that executes an approved payment")


class CashView(BaseModel):
    account: str
    balance: float
    as_of: str
    shop_date: str


class ResetRequest(BaseModel):
    confirm: Literal["RESET"] = Field(description='Must be the word "RESET"')


class ResetResult(BaseModel):
    message: str
    database: str
    restored_from: str
    approvals_archived_to: str | None = None


# --------------------------------------------------------------------------
# Manager actions (human-only dashboard routes)
# --------------------------------------------------------------------------

class ManagerActionBase(BaseModel):
    """Every manager action needs a name, a typed confirmation, and an honest label."""

    recorded_by: str = Field(min_length=1, description="Name of the person recording this")
    confirm: str = Field(description="Must equal the ticket ID, approval ID, or source ID, as a deliberate confirmation")
    simulated: bool = Field(True, description="True when this stands in for a real-world customer/vendor event "
                                              "(always the case for customer and vendor events in this assignment)")
    basis: str = Field(min_length=1, description="What this record is based on, e.g. 'Simulated for Problem 9: "
                                                 "no real customer was contacted'")


class CustomerResponseIn(ManagerActionBase):
    choice: Literal["accept", "decline", "wait", "alternative", "partial", "other"]
    summary: str = Field(min_length=1, description="What the customer decided, in the manager's words")
    channel: str = Field("unspecified", description="How it was received (email, phone, in person, simulated…)")


class PricingDecisionIn(ManagerActionBase):
    simulated: bool = Field(False, description="A pricing decision is normally the manager's own real decision")
    sku: str
    size: str
    quantity: int = Field(gt=0)
    discount_pct: float = Field(ge=0, lt=100)
    decision: Literal["approved", "declined"]
    note: str = ""


class FulfilmentIn(ManagerActionBase):
    sku: str
    size: str
    quantity: int = Field(gt=0)


class PlaceOrderIn(ManagerActionBase):
    vendor_reference: str = ""
    acknowledge_cash_warning: bool = False
    acknowledge_duplicate_warning: bool = False


class CancelPurchaseIn(BaseModel):
    recorded_by: str = Field(min_length=1)
    confirm: str = Field(description="Must equal the approval ID")
    reason: str = Field(min_length=1)


class StockReceiptIn(ManagerActionBase):
    sku: str
    size: str
    quantity: int = Field(gt=0)
    source_kind: Literal["purchase_order", "invoice"]
    source_id: str = Field(description="BUY-… for a purchase order, or the invoice id")
    ticket_id: int | None = None


class ManagerActionResult(BaseModel):
    event: dict[str, Any]
    message: str
    effects: dict[str, Any] = Field(description="What actually changed (inventory, purchase status); cash never changes")
