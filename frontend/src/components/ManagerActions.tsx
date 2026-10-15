import { useState, type ReactNode } from 'react'
import {
  recordCustomerResponse, recordFulfilment, recordPricingDecision, recordStockReceipt,
  type ManagerActionResult, type ManagerEvent, type ManagerFields as Fields, type Ticket, type TicketUpdates,
} from '../api'
import { money, timeOf } from '../agents'
import { AgentCharacter } from './AgentCharacter'
import { Icon, Spinner } from './Icon'
import { ManagerFields } from './ManagerFields'

type Base = Omit<Fields, 'recorded_by'>
const blank = (simulated = true): Base => ({ confirm: '', simulated, basis: '' })

const KIND_LABEL: Record<ManagerEvent['kind'], string> = {
  customer_response: 'Customer response',
  pricing_decision: 'Pricing decision',
  purchase_order: 'Purchase order placed',
  purchase_cancelled: 'Purchase cancelled',
  stock_receipt: 'Stock received',
  fulfilment: 'Order fulfilled',
}

function describe(e: ManagerEvent): string {
  const d = e.details as Record<string, string | number | boolean | null>
  switch (e.kind) {
    case 'customer_response':
      return `Choice: ${d.choice}. ${d.summary} (channel: ${d.channel})`
    case 'pricing_decision':
      return `${d.decision}: ${d.discount_pct}% off ${d.quantity} × ${d.sku} ${d.size} → ${money(Number(d.unit_price))} each `
        + `(${money(Number(d.margin_per_unit))} margin). No revenue recorded.`
    case 'purchase_order':
      return `${d.quantity} × ${d.sku} ${d.size} from ${d.vendor} (${e.refs.approval_id}), expected around ${d.expected_arrival}. No money moved.`
    case 'purchase_cancelled':
      return `${e.refs.approval_id} cancelled: ${d.reason}`
    case 'stock_receipt':
      return `+${d.quantity} × ${d.sku} ${d.size} against ${e.refs.invoice_id ? `invoice ${e.refs.invoice_id}` : e.refs.approval_id}; stock now ${d.qty_after}.`
    case 'fulfilment':
      return `${d.quantity} × ${d.sku} ${d.size} handed over (${d.fulfilled_total} of ${d.ordered_qty}); stock now ${d.qty_after}. No revenue recorded.`
  }
}

/** One manager-recorded event, clearly separated from agent actions. */
export function ManagerEventRow({ e }: { e: ManagerEvent }) {
  return (
    <li className="mevent">
      <AgentCharacter who="human" mood="talking" size={28} />
      <div>
        <div className="mevent-head">
          <b>{KIND_LABEL[e.kind]}</b>
          {e.simulated ? <span className="pill pill-sim">Simulated</span> : <span className="pill pill-quiet">Manager decision</span>}
          <span className="muted small">by {e.recorded_by} · {timeOf(e.recorded_at)}</span>
        </div>
        <div className="small">{describe(e)}</div>
        <div className="muted small">Basis: {e.basis}</div>
      </div>
    </li>
  )
}

function Form({ title, help, children, onSubmit, busy, result, error }: {
  title: string; help: ReactNode; children: ReactNode; onSubmit: () => void; busy: boolean
  result: ManagerActionResult | null; error: string | null
}) {
  return (
    <details className="mform">
      <summary>{title}</summary>
      <p className="muted small">{help}</p>
      <div className="mform-fields">{children}</div>
      <button type="button" className="btn btn-primary" disabled={busy} onClick={onSubmit}>
        {busy ? <Spinner /> : <Icon name="check" size={14} />} Record
      </button>
      {error && <div className="text-danger small" role="alert">{error}</div>}
      {result && <div className="result small" role="status">{result.message}</div>}
    </details>
  )
}

function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ManagerActionResult | null>(null)
  const run = async (fn: () => Promise<ManagerActionResult>, onDone: () => void) => {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setResult(await fn())
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, result, run, setError }
}

interface Props {
  ticket: Ticket
  updates: TicketUpdates | null
  approverName: string
  disabledReason: string | null // e.g. an agent run is in progress
  onRecorded: () => Promise<void>
}

/** Things a person records for this ticket: what agents can't do (talk to customers, sign off prices, hand over goods). */
export function ManagerActions({ ticket, updates, approverName, disabledReason, onRecorded }: Props) {
  const id = String(ticket.id)
  const [resp, setResp] = useState({ choice: '', summary: '', channel: '' })
  const [respBase, setRespBase] = useState(blank())
  const [price, setPrice] = useState({ size: ticket.size ?? '', quantity: '', discount: '', decision: 'approved' as 'approved' | 'declined', note: '' })
  const [priceBase, setPriceBase] = useState(blank(false))
  const [rcpt, setRcpt] = useState({ size: ticket.size ?? '', quantity: '' })
  const [rcptBase, setRcptBase] = useState(blank())
  const [ful, setFul] = useState({ size: ticket.size ?? '', quantity: '' })
  const [fulBase, setFulBase] = useState(blank())
  const a1 = useAction(), a2 = useAction(), a3 = useAction(), a4 = useAction()

  const name = approverName.trim()
  const needName = (set: (m: string) => void) => {
    if (!name) { set('Enter your name in "Approving as" (right column) first.'); return true }
    if (disabledReason) { set(disabledReason); return true }
    return false
  }
  const events = updates?.events ?? []
  const response = updates?.latest_customer_response
  const pricing = updates?.latest_pricing_decision

  return (
    <div className="card manager-actions" id="manager-actions">
      <div className="card-title">
        <AgentCharacter who="human" mood="idle" size={26} /> Manager actions
        <span className="pill pill-quiet">recorded by you · agents can only read these</span>
      </div>
      <p className="muted small">
        Optional: record what the agents can't do themselves, such as a customer's answer, a delivery, or a handover. These are
        <b>not required</b> to resolve a ticket: future deliveries and customer responses are follow-ups. Mark customer and
        vendor events as <b>simulated</b> (no real customer or vendor is contacted). Nothing here moves cash or resolves the
        ticket; run the team again and the Boss decides.
      </p>

      {events.length > 0 ? (
        <ul className="mevents">{events.map((e) => <ManagerEventRow key={e.event_id} e={e} />)}</ul>
      ) : (
        <p className="muted small">No manager events recorded for this ticket.</p>
      )}
      {updates && ticket.sku && (
        <div className="muted small">
          Fulfilled {updates.quantity_fulfilled} of {ticket.qty} · customer response: {response ? String(response.details.choice) : 'not recorded'}
          {ticket.type === 'price_override' && ` · pricing decision: ${pricing ? String(pricing.details.decision) : 'not recorded'}`}
          {updates.open_steps.length > 0 && ` · open: ${updates.open_steps.join('; ')}`}
        </div>
      )}
      {updates?.linked_invoice && (
        <div className="muted small">
          Linked invoice {updates.linked_invoice.invoice_id}: “{updates.linked_invoice.description}”, {updates.linked_invoice.status}
          {updates.linked_invoice.covers_requested_item ? ': this is the restock for the requested item (quantity and delivery date not recorded).' : '.'}
        </div>
      )}
      {updates && updates.unpaid_vendor_invoices.length > 0 && (
        <div className="pwarn-cash small">
          Unpaid vendor invoice(s) for this ticket: {updates.unpaid_vendor_invoices.map((i) => `#${i.invoice_id} (${money(i.amount)})`).join(', ')}
          {' '}· checking {money(updates.cash.checking_balance)}. The ticket can't be resolved until they're paid.
        </div>
      )}

      <Form title="Record customer response" busy={a1.busy} error={a1.error} result={a1.result}
        help="After you've sent the drafted reply yourself, record what the customer decided. Agents never contact customers."
        onSubmit={() => {
          if (needName(a1.setError)) return
          if (!resp.choice) return a1.setError('Choose what the customer decided.')
          a1.run(() => recordCustomerResponse(ticket.id, { ...respBase, recorded_by: name, ...resp, channel: resp.channel || 'unspecified' }),
            () => { setResp({ choice: '', summary: '', channel: '' }); setRespBase(blank()); void onRecorded() })
        }}>
        <select aria-label="Customer's choice" value={resp.choice} onChange={(e) => setResp({ ...resp, choice: e.target.value })}>
          <option value="">Customer's choice…</option>
          <option value="accept">accept: accepts the offer as proposed</option>
          <option value="wait">wait: will wait for the requested item</option>
          <option value="alternative">alternative: accepts a different size</option>
          <option value="partial">partial: takes part of the order</option>
          <option value="decline">decline: doesn't want it</option>
          <option value="other">other</option>
        </select>
        <input placeholder="What the customer decided, in your words" value={resp.summary} onChange={(e) => setResp({ ...resp, summary: e.target.value })} />
        <input placeholder="Channel (email, phone, in person, simulated…)" value={resp.channel} onChange={(e) => setResp({ ...resp, channel: e.target.value })} />
        <ManagerFields expected={id} value={respBase} onChange={setRespBase} />
      </Form>

      {ticket.type === 'price_override' && ticket.sku && (
        <Form title="Record pricing decision" busy={a2.busy} error={a2.error} result={a2.result}
          help="Your sign-off on a discount. The price and margin are recalculated from the pricing table; anything below cost is refused."
          onSubmit={() => {
            if (needName(a2.setError)) return
            const q = Number(price.quantity), d = Number(price.discount)
            if (!price.discount || !(q > 0)) return a2.setError('Enter the quantity and discount %.')
            a2.run(() => recordPricingDecision(ticket.id, { ...priceBase, recorded_by: name, sku: ticket.sku!, size: price.size,
              quantity: q, discount_pct: d, decision: price.decision, note: price.note }),
            () => { setPriceBase(blank(false)); void onRecorded() })
          }}>
          <div className="row2">
            <input aria-label="Size" placeholder="Size" value={price.size} onChange={(e) => setPrice({ ...price, size: e.target.value })} />
            <input aria-label="Quantity" placeholder="Quantity" inputMode="numeric" value={price.quantity} onChange={(e) => setPrice({ ...price, quantity: e.target.value })} />
            <input aria-label="Discount %" placeholder="Discount %" inputMode="decimal" value={price.discount} onChange={(e) => setPrice({ ...price, discount: e.target.value })} />
          </div>
          <select aria-label="Decision" value={price.decision} onChange={(e) => setPrice({ ...price, decision: e.target.value as 'approved' | 'declined' })}>
            <option value="approved">approve this price</option>
            <option value="declined">decline this discount</option>
          </select>
          <input placeholder="Note (optional)" value={price.note} onChange={(e) => setPrice({ ...price, note: e.target.value })} />
          <ManagerFields expected={id} value={priceBase} onChange={setPriceBase} simulatedHelp="(leave unticked: this is your own decision)" />
        </Form>
      )}

      {ticket.invoice_id !== null && ticket.sku && (
        <Form title={`Record stock received against invoice ${ticket.invoice_id}`} busy={a3.busy} error={a3.error} result={a3.result}
          help={<>Only if you've confirmed that invoice {ticket.invoice_id} covers this stock. Refused while a purchase for the same item
            is still pending, approved, or ordered (cancel it first to avoid a duplicate). Adds to inventory; no money moves.</>}
          onSubmit={() => {
            if (needName(a3.setError)) return
            const q = Number(rcpt.quantity)
            if (!(q > 0)) return a3.setError('Enter the quantity received.')
            a3.run(() => recordStockReceipt({ ...rcptBase, recorded_by: name, sku: ticket.sku!, size: rcpt.size, quantity: q,
              source_kind: 'invoice', source_id: String(ticket.invoice_id), ticket_id: ticket.id }),
            () => { setRcpt({ ...rcpt, quantity: '' }); setRcptBase(blank()); void onRecorded() })
          }}>
          <div className="row2">
            <input aria-label="Size" placeholder="Size" value={rcpt.size} onChange={(e) => setRcpt({ ...rcpt, size: e.target.value })} />
            <input aria-label="Quantity received" placeholder="Quantity received" inputMode="numeric" value={rcpt.quantity} onChange={(e) => setRcpt({ ...rcpt, quantity: e.target.value })} />
          </div>
          <ManagerFields expected={String(ticket.invoice_id)} value={rcptBase} onChange={setRcptBase} />
        </Form>
      )}

      {ticket.sku && (
        <Form title="Record order fulfilled" busy={a4.busy} error={a4.error} result={a4.result}
          help={<>Handing the goods to the customer. Needs a recorded customer response{ticket.type === 'price_override' ? ' and a pricing decision' : ''};
            a different size needs the customer's recorded "alternative" choice. Removes stock; no revenue is recorded.</>}
          onSubmit={() => {
            if (needName(a4.setError)) return
            const q = Number(ful.quantity)
            if (!(q > 0)) return a4.setError('Enter the quantity handed over.')
            a4.run(() => recordFulfilment(ticket.id, { ...fulBase, recorded_by: name, sku: ticket.sku!, size: ful.size, quantity: q }),
              () => { setFul({ ...ful, quantity: '' }); setFulBase(blank()); void onRecorded() })
          }}>
          <div className="row2">
            <input aria-label="Size" placeholder="Size" value={ful.size} onChange={(e) => setFul({ ...ful, size: e.target.value })} />
            <input aria-label="Quantity handed over" placeholder={`Quantity (${updates?.quantity_still_to_fulfil ?? ticket.qty} left)`} inputMode="numeric"
              value={ful.quantity} onChange={(e) => setFul({ ...ful, quantity: e.target.value })} />
          </div>
          <ManagerFields expected={id} value={fulBase} onChange={setFulBase} />
        </Form>
      )}
    </div>
  )
}
