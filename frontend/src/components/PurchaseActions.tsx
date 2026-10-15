import { useState } from 'react'
import {
  ApiError, cancelPurchase, placePurchaseOrder, recordStockReceipt,
  type Approval, type CashWarning, type DuplicateWarning, type ManagerActionResult,
} from '../api'
import { money } from '../agents'
import { Icon, Spinner } from './Icon'
import { ManagerFields } from './ManagerFields'

export interface PurchaseWarnings {
  cash_warning: CashWarning | null
  duplicate_warnings: DuplicateWarning[]
}

/** Cash and possible-duplicate warnings for a purchase. Information only: approving or ordering moves no money. */
export function PurchaseWarningsView({ w }: { w: PurchaseWarnings | null }) {
  if (!w || (!w.cash_warning && !w.duplicate_warnings.length)) return null
  return (
    <div className="pwarn small">
      {w.cash_warning && (
        <div className="pwarn-cash">
          <Icon name="alert" size={12} /> <b>Cash warning (projection):</b> estimated cost {money(w.cash_warning.estimated_cost)} vs{' '}
          {money(w.cash_warning.available_after_commitments)} available (checking {money(w.cash_warning.checking_balance)} minus{' '}
          {money(w.cash_warning.committed)} committed), short by {money(w.cash_warning.shortfall)}.
        </div>
      )}
      {w.duplicate_warnings.map((d, i) => (
        <div key={i} className="pwarn-dup"><Icon name="alert" size={12} /> <b>Possible duplicate:</b> {d.message}</div>
      ))}
    </div>
  )
}

interface Props {
  approval: Approval
  approverName: string
  warnings: PurchaseWarnings | null
  disabledReason: string | null
  onDone: () => Promise<void>
}

/** Approved -> Place order / Cancel. Ordered -> Record receipt. Each needs a name and the ID typed back. */
export function PurchaseActions({ approval: a, approverName, warnings, disabledReason, onDone }: Props) {
  const [mode, setMode] = useState<'order' | 'cancel' | 'receive' | null>(null)
  const [base, setBase] = useState({ confirm: '', simulated: true, basis: '' })
  const [vendorRef, setVendorRef] = useState('')
  const [ackCash, setAckCash] = useState(false)
  const [ackDup, setAckDup] = useState(false)
  const [reason, setReason] = useState('')
  const [qty, setQty] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ManagerActionResult | null>(null)
  const [serverWarnings, setServerWarnings] = useState<PurchaseWarnings | null>(null)
  const w = serverWarnings ?? warnings

  const go = async (fn: () => Promise<ManagerActionResult>) => {
    setError(null)
    if (!approverName.trim()) return setError('Enter your name in "Approving as" first.')
    if (disabledReason) return setError(disabledReason)
    setBusy(true)
    try {
      setResult(await fn())
      setMode(null)
      setBase({ confirm: '', simulated: true, basis: '' })
      await onDone()
    } catch (e) {
      if (e instanceof ApiError && e.detail && typeof e.detail === 'object' && 'needs_acknowledgement' in e.detail) {
        const d = e.detail as unknown as PurchaseWarnings
        setServerWarnings({ cash_warning: d.cash_warning, duplicate_warnings: d.duplicate_warnings ?? [] })
      }
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="pactions">
      {a.status === 'approved' && (
        <>
          <div className="status-line small">Approved by {a.approved_by}. <b>No order placed yet.</b></div>
          <div className="btn-row">
            <button type="button" className={`btn btn-small${mode === 'order' ? ' active' : ''}`} onClick={() => setMode(mode === 'order' ? null : 'order')}>
              <Icon name="cart" size={13} /> Place order
            </button>
            <button type="button" className={`btn btn-small btn-reject${mode === 'cancel' ? ' active' : ''}`} onClick={() => setMode(mode === 'cancel' ? null : 'cancel')}>
              <Icon name="x" size={13} /> Cancel
            </button>
          </div>
        </>
      )}
      {a.status === 'ordered' && (
        <>
          <div className="status-line small">
            Ordered by {a.ordered_by}{a.order_simulated ? ' (simulated)' : ''}; expected around {a.expected_arrival}. Not received yet.
            {a.vendor_invoice_id ? ` Vendor invoice ${a.vendor_invoice_id} is open: pay it through Accounting and your approval.` : ''}
          </div>
          <button type="button" className={`btn btn-small${mode === 'receive' ? ' active' : ''}`} onClick={() => setMode(mode === 'receive' ? null : 'receive')}>
            <Icon name="inventory" size={13} /> Record receipt
          </button>
        </>
      )}

      {mode === 'order' && (
        <div className="pform">
          <p className="muted small">Record that you ordered this from {a.payee}. This creates an <b>open vendor invoice</b> for
            {' '}{money(a.amount)} (due on the expected delivery date) and restricts the vendor until it's paid. No money moves now.</p>
          <PurchaseWarningsView w={w} />
          {w?.cash_warning && (
            <label className="small ack"><input type="checkbox" checked={ackCash} onChange={(e) => setAckCash(e.target.checked)} /> I've seen the cash warning and still want to order</label>
          )}
          {w && w.duplicate_warnings.length > 0 && (
            <label className="small ack"><input type="checkbox" checked={ackDup} onChange={(e) => setAckDup(e.target.checked)} /> I've seen the possible-duplicate warning and accept the risk</label>
          )}
          <input placeholder="Vendor reference (optional)" value={vendorRef} onChange={(e) => setVendorRef(e.target.value)} />
          <ManagerFields expected={a.approval_id} value={base} onChange={setBase} />
          <button type="button" className="btn btn-primary btn-small" disabled={busy}
            onClick={() => go(() => placePurchaseOrder(a.approval_id, { ...base, recorded_by: approverName.trim(), vendor_reference: vendorRef,
              acknowledge_cash_warning: ackCash, acknowledge_duplicate_warning: ackDup }))}>
            {busy ? <Spinner /> : <Icon name="check" size={13} />} Record order
          </button>
        </div>
      )}
      {mode === 'cancel' && (
        <div className="pform">
          <p className="muted small">Cancels this approved purchase before any order is placed (e.g. it would duplicate another order).</p>
          <input placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <input placeholder={`Type ${a.approval_id} to confirm`} value={base.confirm} onChange={(e) => setBase({ ...base, confirm: e.target.value })} />
          <button type="button" className="btn btn-reject btn-small" disabled={busy}
            onClick={() => go(() => cancelPurchase(a.approval_id, { recorded_by: approverName.trim(), confirm: base.confirm, reason }))}>
            {busy ? <Spinner /> : <Icon name="x" size={13} />} Cancel purchase
          </button>
        </div>
      )}
      {mode === 'receive' && (
        <div className="pform">
          <p className="muted small">Record what arrived for this order (up to {a.quantity}). Adds to inventory; no money moves and no vendor invoice is created.</p>
          <input placeholder={`Quantity received (ordered ${a.quantity})`} inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} />
          <ManagerFields expected={a.approval_id} value={base} onChange={setBase} />
          <button type="button" className="btn btn-primary btn-small" disabled={busy}
            onClick={() => {
              const q = Number(qty)
              if (!(q > 0)) return setError('Enter the quantity received.')
              void go(() => recordStockReceipt({ ...base, recorded_by: approverName.trim(), sku: a.sku!, size: a.size!, quantity: q,
                source_kind: 'purchase_order', source_id: a.approval_id, ticket_id: a.ticket_id }))
            }}>
            {busy ? <Spinner /> : <Icon name="check" size={13} />} Record receipt
          </button>
        </div>
      )}
      {error && <div className="text-danger small" role="alert">{error}</div>}
      {result && <div className="result small" role="status">{result.message}</div>}
    </div>
  )
}
