import type { Approval, Cash, DecisionResult, Run } from '../api'
import { money } from '../agents'
import { ApprovalCard } from './ApprovalCard'
import { CashCard } from './CashCard'
import type { PurchaseWarnings } from './PurchaseActions'

interface Props {
  approvals: Approval[]
  runs: Run[]
  cash: Cash | null
  cashError: string | null
  approverName: string
  onApproverName: (name: string) => void
  highlightTicketId: number | null
  onDecide: (approvalId: string, action: 'approve' | 'reject' | 'execute', confirm: string, reason?: string) => Promise<DecisionResult>
  warningsById: Map<string, PurchaseWarnings>
  disabledReason: string | null
  onManagerDone: () => Promise<void>
}

function statusText(a: Approval) {
  if (a.status === 'received') return `received ${a.received_qty} · ordered by ${a.ordered_by}${a.order_simulated ? ' (simulated)' : ''}`
  if (a.status === 'cancelled') return `cancelled by ${a.cancelled_by}: ${a.cancel_reason}`
  if (a.status === 'executed') return `paid · approved by ${a.approved_by}`
  if (a.status === 'rejected') return `rejected by ${a.rejected_by}${a.rejection_reason ? `: ${a.rejection_reason}` : ' (no reason given)'}`
  if (a.kind === 'purchase' && a.status === 'approved') return `approval recorded by ${a.approved_by} · order not placed by the system`
  return a.status
}

export function ApprovalQueue(props: Props) {
  const { approvals, runs, cash } = props
  const payments = approvals.filter((a) => a.kind !== 'purchase')
  const purchases = approvals.filter((a) => a.kind === 'purchase')
  const activePayments = payments.filter((a) => a.status === 'pending' || a.status === 'approved')
  // Active purchases: waiting for approval, approved but not ordered, or ordered and not yet received.
  const pendingPurchases = purchases.filter((a) => a.status === 'pending' || a.status === 'approved' || a.status === 'ordered')
  const history = approvals.filter((a) => !activePayments.includes(a) && !pendingPurchases.includes(a))
  const pendingPaymentTotal = payments.filter((a) => a.status === 'pending').reduce((s, a) => s + a.amount, 0)

  const card = (a: Approval) => {
    const othersPending = payments.filter((p) => p.status === 'pending' && p.approval_id !== a.approval_id)
    return (
      <ApprovalCard
        key={a.approval_id}
        approval={a}
        approverName={props.approverName}
        cash={cash}
        otherPendingPaymentsTotal={a.status === 'pending' ? pendingPaymentTotal - a.amount : 0}
        otherPendingPaymentsCount={a.status === 'pending' ? othersPending.length : 0}
        executingRun={runs.find((r) => r.kind === 'payment_execution' && r.approval_id === a.approval_id && r.status === 'running') ?? null}
        highlight={props.highlightTicketId !== null && a.ticket_id === props.highlightTicketId}
        onDecide={props.onDecide}
        warnings={props.warningsById.get(a.approval_id) ?? null}
        disabledReason={props.disabledReason}
        onManagerDone={props.onManagerDone}
      />
    )
  }

  return (
    <section className="column" aria-label="Approvals and cash" id="approvals">
      <CashCard cash={cash} error={props.cashError} />

      <label className="approver small">
        Approving as
        <input
          value={props.approverName}
          onChange={(e) => props.onApproverName(e.target.value)}
          placeholder="Your name"
          aria-label="Your name, recorded with each approval"
        />
      </label>

      <h2 className="column-title">
        Payments needing you <span className="count">{activePayments.length}</span>
      </h2>
      {activePayments.length === 0 && <p className="muted small">No payment requests. Accounting files them during a ticket run.</p>}
      {activePayments.map(card)}

      <h2 className="column-title">
        Purchase requests and orders <span className="count">{pendingPurchases.length}</span>
        <span className="pill pill-quiet">no immediate cash impact</span>
      </h2>
      {pendingPurchases.length === 0 && <p className="muted small">No purchase requests. Inventory files them for restocks.</p>}
      {pendingPurchases.map(card)}

      {history.length > 0 && (
        <details className="history">
          <summary className="small">History ({history.length})</summary>
          <ul>
            {history.map((a) => (
              <li key={a.approval_id} className="small">
                <b>{a.approval_id}</b> {a.kind} {money(a.amount)} · {a.payee}
                <div className="muted">{statusText(a)}</div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
