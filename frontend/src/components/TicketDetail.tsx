import type { AgentEvent, BossDecision, Run, Ticket, TicketUpdates } from '../api'
import { agentLabel, money } from '../agents'
import { AgentActivity } from './AgentActivity'
import { ManagerActions } from './ManagerActions'
import { NextAction } from './NextAction'

interface Props {
  ticket: Ticket
  runs: Run[] // this ticket's runs since the last reset, oldest first
  events: AgentEvent[]
  activeRun: Run | null
  canRun: boolean
  runBlockedReason: string | null
  starting: boolean
  onRun: () => void
  onReviewApprovals: () => void
  celebrating: boolean
  updates: TicketUpdates | null
  approverName: string
  managerDisabledReason: string | null
  onManagerRecorded: () => Promise<void>
}

function BossDecisionCard({ run, ticketId }: { run: Run; ticketId: number }) {
  const out = run.output as BossDecision | null
  if (!out || !('ticket_decisions' in out)) return null
  const d = out.ticket_decisions.find((x) => x.ticket_id === ticketId)
  return (
    <div className="card decision agent-boss">
      <div className="card-title">Boss decision</div>
      <p className="decision-summary">{out.summary}</p>
      {d && (
        <dl className="kv small">
          <dt>Decision</dt><dd>{d.decision}</dd>
          <dt>Owner</dt><dd>{agentLabel(d.owner)}</dd>
          <dt>Status</dt><dd>{d.status.replace(/_/g, ' ')}</dd>
          {d.next_steps.length > 0 && (<><dt>Next steps</dt><dd>{d.next_steps.join(' · ')}</dd></>)}
        </dl>
      )}
      {out.payments_needing_human_approval.length > 0 && (
        <div className="small muted">
          Payments for your approval:{' '}
          {out.payments_needing_human_approval.map((p) => `${p.approval_id ?? 'not filed'} (${p.payee}, ${money(p.amount)})`).join(', ')}
        </div>
      )}
      {out.risks.length > 0 && <div className="small muted">Risks: {out.risks.join(' · ')}</div>}
    </div>
  )
}

export function TicketDetail(props: Props) {
  const { ticket, runs, events } = props
  const lastTicketRun = [...runs].reverse().find((r) => r.kind === 'ticket' && r.status === 'finished')
  return (
    <section className="column column-center" aria-label={`Ticket ${ticket.id}`}>
      <div className="detail-head">
        <h2>
          #{ticket.id} {ticket.subject}
        </h2>
        <span className="muted small">
          {ticket.requester}
          {ticket.sku && ` · ${ticket.sku} ${ticket.size ?? ''} × ${ticket.qty}`}
          {ticket.lease_id !== null && ` · lease ${ticket.lease_id}`}
          {ticket.invoice_id !== null && ` · invoice ${ticket.invoice_id}`}
        </span>
        {ticket.notes && <q className="ticket-notes">{ticket.notes}</q>}
      </div>

      <NextAction
        ticket={ticket}
        activeRun={props.activeRun}
        canRun={props.canRun}
        runBlockedReason={props.runBlockedReason}
        starting={props.starting}
        onRun={props.onRun}
        onReviewApprovals={props.onReviewApprovals}
        celebrating={props.celebrating}
      />

      {lastTicketRun && <BossDecisionCard run={lastTicketRun} ticketId={ticket.id} />}

      {lastTicketRun && ticket.status !== 'resolved' && (
        <ManagerActions key={ticket.id} ticket={ticket} updates={props.updates} approverName={props.approverName}
          disabledReason={props.managerDisabledReason} onRecorded={props.onManagerRecorded} />
      )}

      <AgentActivity runs={runs} events={events} running={ticket.running} celebrating={props.celebrating} />
    </section>
  )
}
