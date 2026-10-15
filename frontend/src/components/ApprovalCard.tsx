import { useState } from 'react'
import type { Approval, Cash, DecisionResult, Run } from '../api'
import { agentLabel, isAgent, money } from '../agents'
import { AgentCharacter } from './AgentCharacter'
import { Icon, Spinner } from './Icon'
import { PurchaseActions, PurchaseWarningsView, type PurchaseWarnings } from './PurchaseActions'

type Action = 'approve' | 'reject' | 'execute'

interface Props {
  approval: Approval
  approverName: string
  cash: Cash | null
  otherPendingPaymentsTotal: number // other pending payments (for the "all pending" projection)
  otherPendingPaymentsCount: number
  executingRun: Run | null // Accounting run executing this payment, if any
  highlight: boolean
  onDecide: (approvalId: string, action: Action, confirm: string, reason?: string) => Promise<DecisionResult>
  warnings: PurchaseWarnings | null // purchases: cash and possible-duplicate warnings
  disabledReason: string | null
  onManagerDone: () => Promise<void>
}

function requester(r: string) {
  return r.endsWith('_agent') ? agentLabel(r.replace('_agent', '')) : r
}

/** Payment or purchase request. Approving needs the person's name and the ID typed back (backend rule). */
export function ApprovalCard(props: Props) {
  const { approval: a, approverName, cash, executingRun, highlight, onDecide } = props
  const [confirm, setConfirm] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState<Action | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<DecisionResult | null>(null)
  const isPurchase = a.kind === 'purchase'

  const act = async (action: Action) => {
    setError(null)
    if (!approverName.trim()) return setError('Enter your name at the top of this column first.')
    if (confirm.trim() !== a.approval_id) return setError(`Type ${a.approval_id} exactly to confirm.`)
    setBusy(action)
    try {
      setResult(await onDecide(a.approval_id, action, confirm.trim(), reason.trim()))
      setConfirm('')
      setReason('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  const projectionAfter = cash ? cash.balance - a.amount : null
  const projectionAll = cash ? cash.balance - a.amount - props.otherPendingPaymentsTotal : null
  const needsDecision = a.status === 'pending'
  const awaitingExecution = !isPurchase && a.status === 'approved'

  return (
    <div className={`card approval ${isPurchase ? 'approval-purchase' : 'approval-payment'}${highlight ? ' highlight' : ''}`}>
      <div className="approval-top">
        <span className={`pill ${isPurchase ? 'pill-purchase' : 'pill-payment'}`}>
          <Icon name={isPurchase ? 'cart' : 'cash'} size={12} /> {isPurchase ? 'purchase' : `${a.kind} payment`}
        </span>
        <span className="approval-amount">{money(a.amount)}</span>
      </div>
      <div className="approval-what">{a.description}</div>
      {(() => {
        const who = a.requested_by.replace(/_agent$/, '')
        return isAgent(who) ? (
          <div className="prepared-by small">
            <AgentCharacter who={who} mood={a.status === 'executed' ? 'happy' : 'talking'} size={30} />
            <span>Prepared by <b>{agentLabel(who)}</b>{needsDecision ? ', waiting for your decision' : ''}</span>
          </div>
        ) : null
      })()}
      <div className="muted small">
        {a.approval_id} · {a.payee}
        {a.ticket_id !== null && ` · ticket #${a.ticket_id}`}
        {a.due_date && ` · due ${a.due_date}`} · by {requester(a.requested_by)}
      </div>
      {a.reason && <div className="small reason">{a.reason}</div>}

      {!isPurchase && needsDecision && (
        <dl className="balance-box small" aria-label="Balance impact">
          <dt>Checking now <span className="pill pill-quiet">actual</span></dt>
          <dd>{cash ? money(cash.balance) : '…'}</dd>
          <dt>After this payment <span className="pill pill-projection">projection</span></dt>
          <dd className={projectionAfter !== null && projectionAfter < 0 ? 'text-danger' : ''}>
            {projectionAfter !== null ? money(projectionAfter) : '…'}
          </dd>
          {props.otherPendingPaymentsCount > 0 && (
            <>
              <dt>If all {props.otherPendingPaymentsCount + 1} pending payments are paid <span className="pill pill-projection">projection</span></dt>
              <dd className={projectionAll !== null && projectionAll < 0 ? 'text-danger' : ''}>
                {projectionAll !== null ? money(projectionAll) : '…'}
              </dd>
            </>
          )}
          <dd className="projection-note">
            Projections are estimates, not the actual balance. The real balance changes only when Accounting executes an
            approved payment{projectionAfter !== null && projectionAfter < 0 ? ', and the backend refuses any payment that would overdraw checking' : ''}.
          </dd>
        </dl>
      )}

      {isPurchase && needsDecision && (
        <div className="purchase-note small">
          <Icon name="info" size={12} /> Approving only records your decision. No order is placed, and cash and
          inventory don't change. Estimated cost {money(a.amount)} ({a.quantity} × {money(a.unit_cost ?? 0)}),
          vendor lead time {a.lead_days} days.
        </div>
      )}
      {isPurchase && needsDecision && <PurchaseWarningsView w={props.warnings} />}
      {isPurchase && (a.status === 'approved' || a.status === 'ordered') && (
        <PurchaseActions approval={a} approverName={approverName} warnings={props.warnings}
          disabledReason={props.disabledReason} onDone={props.onManagerDone} />
      )}

      {needsDecision && (
        <div className="approval-actions">
          <input
            aria-label={`Type ${a.approval_id} to confirm`}
            placeholder={`Type ${a.approval_id} to confirm`}
            value={confirm}
            onChange={(e) => { setConfirm(e.target.value); setError(null) }}
          />
          <input
            aria-label="Reason (optional)"
            placeholder="Reason (optional, e.g. not enough cash). Agents read this"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="btn-row">
            <button type="button" className="btn btn-approve" disabled={busy !== null} onClick={() => act('approve')}>
              {busy === 'approve' ? <Spinner /> : <Icon name="check" size={14} />} {isPurchase ? 'Record approval' : 'Approve payment'}
            </button>
            <button type="button" className="btn btn-reject" disabled={busy !== null} onClick={() => act('reject')}>
              {busy === 'reject' ? <Spinner /> : <Icon name="x" size={14} />} Reject
            </button>
          </div>
        </div>
      )}

      {awaitingExecution && (
        executingRun ? (
          <div className="status-line small"><Spinner /> Approved by {a.approved_by}. Accounting is executing the payment…</div>
        ) : (
          <div className="approval-actions">
            <div className="status-line small text-warning">Approved by {a.approved_by} but not paid yet.</div>
            <input placeholder={`Type ${a.approval_id} to retry`} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            <button type="button" className="btn" disabled={busy !== null} onClick={() => act('execute')}>
              {busy === 'execute' ? <Spinner /> : <Icon name="refresh" size={14} />} Retry payment
            </button>
          </div>
        )
      )}

      {error && <div className="text-danger small" role="alert">{error}</div>}
      {result && (
        <div className="result small" role="status">
          {result.message}
          <div className="effects">
            {result.effects.payment_execution_started ? 'Payment execution started' : 'No payment started'} · order placed: no ·
            cash changed now: no · inventory changed: no
          </div>
        </div>
      )}
    </div>
  )
}
