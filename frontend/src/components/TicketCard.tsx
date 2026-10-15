import type { Ticket } from '../api'
import { Icon, Spinner } from './Icon'

const TYPE_LABEL: Record<string, string> = {
  customer_order: 'customer order',
  rent_notice: 'rent notice',
  price_override: 'price request',
}

export function StatusPill({ ticket }: { ticket: Ticket }) {
  if (ticket.running)
    return (
      <span className="pill pill-running">
        <Spinner label="Agents working" /> running
      </span>
    )
  return <span className={`pill pill-${ticket.status === 'resolved' ? 'resolved' : 'open'}`}>{ticket.status}</span>
}

interface Props {
  ticket: Ticket
  selected: boolean
  onSelect: () => void
  celebrating?: boolean
}

export function TicketCard({ ticket, selected, onSelect, celebrating = false }: Props) {
  return (
    <button type="button" className={`ticket-card${selected ? ' selected' : ''}${celebrating ? ' celebrating' : ''}`} onClick={onSelect} aria-pressed={selected}>
      <div className="ticket-card-top">
        <span className="ticket-id">#{ticket.id}</span>
        <StatusPill ticket={ticket} />
      </div>
      <div className="ticket-subject">{ticket.subject}</div>
      <div className="muted small">
        {ticket.requester} · {TYPE_LABEL[ticket.type] ?? ticket.type}
      </div>
      <div className="ticket-next small">
        {ticket.pending_approvals > 0 && (
          <span className="pill pill-wait">
            <Icon name="hourglass" size={12} /> {ticket.pending_approvals} to approve
          </span>
        )}
        <span className="muted">{ticket.next_step}</span>
      </div>
    </button>
  )
}
