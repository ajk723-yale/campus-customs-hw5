/** Typed client for the Campus Customs FastAPI backend (backend/main.py).
 *  Calls go to /api/* and Vite proxies them to the backend (see vite.config.ts),
 *  so they are same-origin in dev and no secrets ever reach the browser.
 *
 *  The types below mirror the backend's response models in backend/models.py
 *  (TicketView, RunView, RunStarted, EventView, DecisionResult, CashView,
 *  ResetResult) and the approval records in mcp_server/approvals.py / server.py. */

export type AgentName = 'boss' | 'inventory' | 'accounting' | 'facilities' | 'customer_service'
export type RunStatus = 'running' | 'finished' | 'failed'
export type Resolution = 'resolved' | 'awaiting_human' | 'open'

export interface Health {
  status: string
  model: string
  mcp_tools: number
  active_run: string | null
}

/** GET /api/tickets, GET /api/tickets/{id} */
export interface Ticket {
  id: number
  type: string
  requester: string
  subject: string
  sku: string | null
  size: string | null
  qty: number | null
  lease_id: number | null
  invoice_id: number | null
  status: string // 'open' | 'resolved' (tickets table)
  notes: string | null
  created_at: string
  running: boolean
  last_run_id: string | null
  last_run_status: RunStatus | null
  pending_approvals: number
  resolution: Resolution | null
  remaining_actions: string[]
  next_step: string
}

/** One ticket decision inside the Boss's BossDecision output. */
export interface TicketDecision {
  ticket_id: number
  priority: number
  decision: string
  owner: AgentName
  status: 'proposed' | 'awaiting_human_approval' | 'blocked' | 'needs_more_info' | 'no_action'
  next_steps: string[]
  resolution: Resolution
  remaining_actions: string[]
  resolves_when_payments_executed: string[]
}

export interface BossDecision {
  summary: string
  ticket_decisions: TicketDecision[]
  payments_needing_human_approval: {
    kind: 'invoice' | 'rent'
    ref_id: number
    payee: string
    amount: number
    reason: string
    approval_id: string | null
  }[]
  consulted_agents: AgentName[]
  risks: string[]
}

/** Specialist reports share these fields (SpecialistReport); extra fields vary by agent. */
export interface AgentReport {
  agent?: AgentName
  summary: string
  findings?: { ticket_id: number | null; fact: string; source_tool: string }[]
  recommendations?: { ticket_id: number | null; action: string; rationale: string; priority: string }[]
  escalations?: { to: string; reason: string }[]
  [extra: string]: unknown
}

/** GET /api/runs, GET /api/runs/{id} */
export interface Run {
  run_id: string
  kind: 'ticket' | 'payment_execution' | 'other'
  ticket_id: number | null
  approval_id: string | null
  status: RunStatus
  started_at: string
  finished_at: string | null
  error: string | null
  output: (BossDecision & AgentReport) | AgentReport | null
}

/** POST /api/tickets/{id}/run (202) */
export interface RunStarted {
  run_id: string
  status: RunStatus
  message: string
}

export type EventCategory = 'run' | 'message' | 'delegation' | 'tool' | 'approval' | 'payment' | 'error' | 'manager'

/** GET /api/events: one audit-trail record with a plain-language line. */
export interface AgentEvent {
  timestamp: string
  run_id: string
  ticket_id: number | null
  agent: string | null
  depth: number | null
  event: string
  category: EventCategory
  text: string
  tool: string | null
  details: Record<string, unknown>
}

/** GET /api/approvals: payment (invoice / rent) or purchase requests. */
export interface Approval {
  approval_id: string
  // payments: pending -> approved -> executed (or rejected)
  // purchases: pending -> approved -> ordered -> received (approved -> cancelled; pending -> rejected)
  status: 'pending' | 'approved' | 'rejected' | 'executed' | 'ordered' | 'received' | 'cancelled'
  kind: 'invoice' | 'rent' | 'purchase'
  ref_id: number
  amount: number
  payee: string
  due_date: string | null
  description: string
  requested_by: string
  reason: string
  ticket_id: number | null
  requested_at: string
  shop_date_when_requested: string
  approved_by: string | null
  approved_at: string | null
  rejected_by?: string
  rejected_at?: string
  rejection_reason?: string | null
  approval_reason?: string | null
  // payments
  account?: string
  balance_when_requested?: number
  payment_id?: number | null
  executed_at?: string
  // purchases
  sku?: string
  size?: string
  product_name?: string
  quantity?: number
  unit_cost?: number
  vendor_id?: number
  lead_days?: number
  ordered_by?: string
  ordered_at?: string
  expected_arrival?: string
  order_simulated?: boolean
  vendor_invoice_id?: number
  received_qty?: number
  cancelled_by?: string
  cancel_reason?: string
  // only on purchases returned by /api/tickets/{id}/updates
  cash_warning?: CashWarning | null
  duplicate_warnings?: DuplicateWarning[]
}

export interface CashWarning {
  estimated_cost: number
  checking_balance: number
  committed: number
  available_after_commitments: number
  shortfall: number
  message: string
}

export interface DuplicateWarning {
  invoice_id?: number
  approval_id?: string
  status: string
  description?: string
  message: string
}

export type ManagerEventKind =
  | 'customer_response' | 'pricing_decision' | 'purchase_order' | 'purchase_cancelled' | 'stock_receipt' | 'fulfilment'

/** One manager-recorded event (output/manager_events.json). */
export interface ManagerEvent {
  event_id: string
  kind: ManagerEventKind
  ticket_id: number | null
  recorded_by: string
  recorded_at: string
  shop_date: string
  simulated: boolean
  basis: string
  details: Record<string, unknown>
  refs: { approval_id?: string; invoice_id?: number }
  source: 'manager'
}

/** GET /api/tickets/{id}/updates (the same data agents read with get_ticket_updates). */
export interface TicketUpdates {
  found: boolean
  ticket_id: number
  ticket_status: string
  requested: { sku: string | null; size: string | null; qty: number | null }
  events: ManagerEvent[]
  latest_customer_response: ManagerEvent | null
  latest_pricing_decision: ManagerEvent | null
  purchases: Approval[]
  payments: Approval[]
  quantity_fulfilled: number
  quantity_still_to_fulfil: number
  on_hand: number | null
  linked_invoice: {
    invoice_id: number; vendor_id: number; amount: number; due_date: string; status: string
    description: string; covers_requested_item: boolean; note: string
  } | null
  vendor_invoices: { approval_id: string; invoice_id: number; amount: number; due_date: string; status: string; description: string }[]
  unpaid_vendor_invoices: { invoice_id: number; amount: number; status: string; description: string }[]
  cash: { checking_balance: number; open_invoices_total: number; committed: number; available_after_commitments: number }
  open_steps: string[]
  note: string
}

/** POST manager-action routes. Cash never changes. */
export interface ManagerActionResult {
  event: ManagerEvent
  message: string
  effects: Record<string, unknown>
}

/** Thrown for API errors; `detail` keeps structured info such as warnings needing acknowledgement. */
export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

export interface DecisionEffects {
  decision_recorded: boolean
  payment_execution_started: boolean
  order_placed: false
  cash_changed_now: false
  inventory_changed: false
}

/** POST /api/approvals/{id}/approve | reject | execute */
export interface DecisionResult {
  approval: Approval
  message: string
  effects: DecisionEffects
  execution_run_id: string | null
}

/** GET /api/cash */
export interface Cash {
  account: string
  balance: number
  as_of: string
  shop_date: string
}

/** POST /api/reset */
export interface ResetResult {
  message: string
  database: string
  restored_from: string
  approvals_archived_to: string | null
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    let detail: unknown = null
    try {
      const body = (await res.json()) as { detail?: unknown }
      detail = body?.detail ?? null
      if (typeof detail === 'string') message = detail
      else if (detail && typeof detail === 'object' && 'error' in detail) message = String((detail as { error: unknown }).error)
      else if (Array.isArray(detail)) message = detail.map((d) => (d as { msg?: string }).msg ?? JSON.stringify(d)).join('; ')
      else if (detail) message = JSON.stringify(detail)
    } catch {
      // Response had no JSON body; the status line is all we get.
    }
    throw new ApiError(message, res.status, detail)
  }
  return (await res.json()) as T
}

function postJson(url: string, body?: unknown): Promise<Response> {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export async function fetchHealth(): Promise<Health> {
  return readJson<Health>(await fetch('/api/health'))
}

export async function fetchTickets(): Promise<Ticket[]> {
  return readJson<Ticket[]>(await fetch('/api/tickets'))
}

export async function runTicket(ticketId: number): Promise<RunStarted> {
  return readJson<RunStarted>(await postJson(`/api/tickets/${ticketId}/run`))
}

export async function fetchRuns(): Promise<Run[]> {
  return readJson<Run[]>(await fetch('/api/runs'))
}

export async function fetchEvents(params: { ticketId?: number; runId?: string; since?: string; limit?: number }): Promise<AgentEvent[]> {
  const q = new URLSearchParams()
  if (params.ticketId !== undefined) q.set('ticket_id', String(params.ticketId))
  if (params.runId) q.set('run_id', params.runId)
  if (params.since) q.set('since', params.since)
  q.set('limit', String(params.limit ?? 2000))
  return readJson<AgentEvent[]>(await fetch(`/api/events?${q}`))
}

export async function fetchApprovals(): Promise<Approval[]> {
  return readJson<Approval[]>(await fetch('/api/approvals'))
}

/** A person approves, rejects, or retries. The backend requires their name and the ID typed back. */
export async function decideApproval(
  approvalId: string,
  action: 'approve' | 'reject' | 'execute',
  approver: string,
  confirmApprovalId: string,
  reason = '',
): Promise<DecisionResult> {
  const res = await postJson(`/api/approvals/${encodeURIComponent(approvalId)}/${action}`, {
    approver,
    confirm_approval_id: confirmApprovalId,
    reason,
  })
  return readJson<DecisionResult>(res)
}

export async function fetchCash(): Promise<Cash> {
  return readJson<Cash>(await fetch('/api/cash'))
}

export async function resetDatabase(): Promise<ResetResult> {
  return readJson<ResetResult>(await postJson('/api/reset', { confirm: 'RESET' }))
}

// ---------------------------------------------------------------------------
// Manager actions: a person records business events the agents can't perform.
// Every call needs the person's name and a typed confirmation; none moves cash.
// ---------------------------------------------------------------------------

export interface ManagerFields {
  recorded_by: string
  confirm: string
  simulated: boolean
  basis: string
}

export async function fetchTicketUpdates(ticketId: number): Promise<TicketUpdates> {
  return readJson<TicketUpdates>(await fetch(`/api/tickets/${ticketId}/updates`))
}

export async function recordCustomerResponse(
  ticketId: number,
  body: ManagerFields & { choice: string; summary: string; channel: string },
): Promise<ManagerActionResult> {
  return readJson<ManagerActionResult>(await postJson(`/api/tickets/${ticketId}/customer-response`, body))
}

export async function recordPricingDecision(
  ticketId: number,
  body: ManagerFields & { sku: string; size: string; quantity: number; discount_pct: number; decision: 'approved' | 'declined'; note: string },
): Promise<ManagerActionResult> {
  return readJson<ManagerActionResult>(await postJson(`/api/tickets/${ticketId}/pricing-decision`, body))
}

export async function recordFulfilment(
  ticketId: number,
  body: ManagerFields & { sku: string; size: string; quantity: number },
): Promise<ManagerActionResult> {
  return readJson<ManagerActionResult>(await postJson(`/api/tickets/${ticketId}/fulfilment`, body))
}

export async function placePurchaseOrder(
  approvalId: string,
  body: ManagerFields & { vendor_reference: string; acknowledge_cash_warning: boolean; acknowledge_duplicate_warning: boolean },
): Promise<ManagerActionResult> {
  return readJson<ManagerActionResult>(await postJson(`/api/approvals/${encodeURIComponent(approvalId)}/place-order`, body))
}

export async function cancelPurchase(
  approvalId: string,
  body: { recorded_by: string; confirm: string; reason: string },
): Promise<ManagerActionResult> {
  return readJson<ManagerActionResult>(await postJson(`/api/approvals/${encodeURIComponent(approvalId)}/cancel`, body))
}

export async function recordStockReceipt(
  body: ManagerFields & { sku: string; size: string; quantity: number; source_kind: 'purchase_order' | 'invoice'; source_id: string; ticket_id: number | null },
): Promise<ManagerActionResult> {
  return readJson<ManagerActionResult>(await postJson('/api/inventory/receipts', body))
}
