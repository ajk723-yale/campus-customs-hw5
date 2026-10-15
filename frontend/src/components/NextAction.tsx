import type { Run, Ticket } from '../api'
import { Confetti } from './Confetti'
import { Icon, Spinner, type IconName } from './Icon'

type Tone = 'resolved' | 'running' | 'human' | 'todo' | 'failed' | 'idle'

/** Classify the ticket from the backend's own fields (status, running, pending_approvals,
 *  last_run_status, resolution, next_step). Nothing here decides resolution itself. */
function tone(ticket: Ticket): Tone {
  if (ticket.running) return 'running'
  if (ticket.status === 'resolved') return 'resolved'
  if (ticket.last_run_status === 'failed') return 'failed'
  if (!ticket.last_run_id) return 'idle'
  // next_step phrases from backend/main.py _ticket_progress for "waiting on a person".
  if (ticket.pending_approvals > 0 || ticket.next_step.startsWith('Waiting for a human decision')
      || ticket.next_step.startsWith('Approved but not yet paid')) return 'human'
  return 'todo'
}

const HEADLINE: Record<Tone, { title: string; icon: IconName }> = {
  resolved: { title: 'Resolved', icon: 'check' },
  running: { title: 'Agents are working', icon: 'clock' },
  human: { title: 'Needs your decision', icon: 'hourglass' },
  todo: { title: 'Still to do', icon: 'flag' },
  failed: { title: 'Last run failed', icon: 'alert' },
  idle: { title: 'Not started', icon: 'play' },
}

interface Props {
  ticket: Ticket
  activeRun: Run | null
  canRun: boolean
  runBlockedReason: string | null
  starting: boolean
  onRun: () => void
  onReviewApprovals: () => void
  celebrating: boolean
}

/** The first thing on the selected ticket's panel: what still needs to be done. */
export function NextAction({ ticket, activeRun, canRun, runBlockedReason, starting, onRun, onReviewApprovals, celebrating }: Props) {
  const t = tone(ticket)
  const head = HEADLINE[t]
  const runLabel = ticket.last_run_id ? 'Run team again' : 'Run agent team'
  return (
    <div className={`next-action tone-${t}${celebrating ? ' celebrating' : ''}`} aria-live="polite">
      {celebrating && <Confetti />}
      <div className="next-action-head">
        <span className="next-action-icon">{t === 'running' ? <Spinner /> : <Icon name={head.icon} size={18} />}</span>
        <div className="next-action-text">
          <div className="next-action-title">
            Next action · {celebrating ? 'Resolved. Nice work, team' : head.title}
            {ticket.resolution && t !== 'resolved' && (
              <span className="pill pill-quiet">Boss: {ticket.resolution.replace('_', ' ')}</span>
            )}
          </div>
          <div className="next-action-step">{t === 'running' && activeRun?.kind === 'payment_execution'
            ? `Accounting is executing ${activeRun.approval_id}…`
            : ticket.next_step}</div>
        </div>
      </div>

      {ticket.remaining_actions.length > 0 && t !== 'resolved' && (
        <ul className="remaining" aria-label="Remaining actions">
          {ticket.remaining_actions.map((a) => (
            <li key={a}>
              <span className="box" aria-hidden="true" /> {a}
            </li>
          ))}
        </ul>
      )}

      <div className="next-action-buttons">
        {ticket.pending_approvals > 0 && (
          <button type="button" className="btn btn-primary" onClick={onReviewApprovals}>
            <Icon name="hourglass" size={14} /> Review {ticket.pending_approvals} approval{ticket.pending_approvals > 1 ? 's' : ''}
          </button>
        )}
        {ticket.status !== 'resolved' && !ticket.running && (
          <button
            type="button"
            className={`btn${ticket.pending_approvals > 0 ? '' : ' btn-primary'}`}
            onClick={onRun}
            disabled={!canRun || starting}
            title={runBlockedReason ?? undefined}
          >
            {starting ? <Spinner /> : <Icon name="play" size={14} />} {runLabel}
          </button>
        )}
        {runBlockedReason && !ticket.running && ticket.status !== 'resolved' && (
          <span className="muted small">{runBlockedReason}</span>
        )}
      </div>
    </div>
  )
}
