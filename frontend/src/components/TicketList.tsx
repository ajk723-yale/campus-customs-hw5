import type { Ticket } from '../api'
import { TicketCard } from './TicketCard'

interface Props {
  tickets: Ticket[]
  selectedId: number | null
  onSelect: (id: number) => void
  celebrating: Set<number>
}

export function TicketList({ tickets, selectedId, onSelect, celebrating }: Props) {
  return (
    <section className="column" aria-label="Tickets">
      <h2 className="column-title">Tickets</h2>
      {tickets.length === 0 && <p className="muted small">Loading tickets…</p>}
      {tickets.map((t) => (
        <TicketCard key={t.id} ticket={t} selected={t.id === selectedId} onSelect={() => onSelect(t.id)} celebrating={celebrating.has(t.id)} />
      ))}
    </section>
  )
}
