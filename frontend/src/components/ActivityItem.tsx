import { useState, type ReactNode } from 'react'
import type { TimelineItem } from '../activity'
import { eventKey } from '../activity'
import { agentLabel, isAgent, timeOf } from '../agents'
import type { AgentEvent, AgentReport } from '../api'
import type { Mood } from '../characters'
import { AgentCharacter } from './AgentCharacter'
import { Icon, type IconName } from './Icon'

/** The agent's character, with an expression that fits what this step was. */
function Avatar({ agent, mood }: { agent: string | null; mood: Mood }) {
  return <AgentCharacter who={isAgent(agent) ? agent : 'human'} mood={mood} size={32} />
}

function eventMood(e: AgentEvent): Mood {
  if (e.category === 'error' || e.event.endsWith('refused') || e.event.endsWith('blocked')) return 'worried'
  switch (e.event) {
    case 'agent_finished':
    case 'payment_executed':
    case 'approval_granted':
      return 'happy'
    case 'delegation_started':
    case 'approval_requested':
      return 'talking'
    default:
      return 'idle'
  }
}

function Json({ value }: { value: unknown }) {
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  return <pre className="json">{text && text.length > 4000 ? `${text.slice(0, 4000)}…` : text}</pre>
}

function ReportDetails({ report }: { report: AgentReport }) {
  return (
    <div className="small">
      {report.findings?.length ? (
        <ul>{report.findings.map((f, i) => <li key={i}>{f.fact} <span className="muted">({f.source_tool})</span></li>)}</ul>
      ) : null}
      {report.recommendations?.length ? (
        <ul>{report.recommendations.map((r, i) => <li key={i}><b>{r.action}</b> · {r.rationale}</li>)}</ul>
      ) : null}
      <details>
        <summary className="muted">Full structured output</summary>
        <Json value={report} />
      </details>
    </div>
  )
}

const KIND: Record<string, { label: string; icon: IconName }> = {
  delegation_started: { label: 'delegation', icon: 'arrow' },
  delegation_result: { label: 'report back', icon: 'arrow' },
  agent_finished: { label: 'message', icon: 'info' },
  approval_requested: { label: 'prepared for approval', icon: 'hourglass' },
  approval_request_refused: { label: 'request refused', icon: 'alert' },
  approval_granted: { label: 'human approved', icon: 'check' },
  approval_rejected: { label: 'human rejected', icon: 'x' },
  payment_executed: { label: 'payment executed', icon: 'cash' },
  payment_refused: { label: 'payment refused', icon: 'alert' },
  payment_blocked: { label: 'payment blocked', icon: 'alert' },
  ticket_status_changed: { label: 'ticket status', icon: 'flag' },
  manager_customer_response: { label: 'you recorded', icon: 'info' },
  manager_pricing_decision: { label: 'you recorded', icon: 'check' },
  manager_purchase_order: { label: 'you recorded', icon: 'cart' },
  manager_purchase_cancelled: { label: 'you recorded', icon: 'x' },
  manager_stock_receipt: { label: 'you recorded', icon: 'inventory' },
  manager_fulfilment: { label: 'you recorded', icon: 'check' },
}

/** One visible step: a message, delegation, approval, payment, error, or run marker. */
export function ActivityItem({ event: e, focused = false }: { event: AgentEvent; focused?: boolean }) {
  const [open, setOpen] = useState(false)
  const d = e.details
  if (e.event === 'run_started' || e.event === 'run_finished' || e.event === 'database_reset') {
    return <div className="run-marker small muted"><span>{e.text}</span><span>{timeOf(e.timestamp)}</span></div>
  }
  const kind = KIND[e.event] ?? { label: e.category, icon: e.category === 'error' ? 'alert' : 'info' }
  const agent = e.agent
  let body: ReactNode = <span>{e.text}</span>
  let details: ReactNode = null

  if (e.event === 'delegation_started') {
    body = (
      <span>
        <b>{agentLabel(agent)}</b> <Icon name="arrow" size={12} /> <b>{agentLabel(String(d.to))}</b>
        <span className="quote">{String(d.task ?? '')}</span>
      </span>
    )
  } else if (e.event === 'delegation_result') {
    body = (
      <span className="muted">
        {agentLabel(String(d.to))} reported back to {agentLabel(agent)}
      </span>
    )
  } else if (e.event === 'agent_finished') {
    const report = d.output as AgentReport | undefined
    body = <span className="message">{report?.summary ?? e.text}</span>
    if (report) details = <ReportDetails report={report} />
  } else if (e.event === 'approval_requested') {
    const r = (d.result ?? {}) as Record<string, unknown>
    body = <span><b>{String(r.approval_id)}</b>: {String(r.description)} — waiting for a human</span>
  }

  const tone = e.category === 'error' || e.event.endsWith('refused') || e.event.endsWith('blocked') ? ' item-error' : ''
  return (
    <div className={`item cat-${e.category}${tone}${focused ? ' focused' : ''}`} data-event-key={eventKey(e)}>
      <Avatar agent={agent} mood={eventMood(e)} />
      <div className="item-body">
        <div className="item-meta">
          <span className="item-agent">{agentLabel(agent)}</span>
          <span className="item-kind"><Icon name={kind.icon} size={11} /> {kind.label}</span>
          {e.depth ? <span className="muted">depth {e.depth}</span> : null}
          {e.category === 'manager' && (d.simulated
            ? <span className="pill pill-sim">Simulated</span>
            : <span className="pill pill-quiet">Manager decision</span>)}
          <span className="muted">{timeOf(e.timestamp)}</span>
        </div>
        <div className="item-text">{body}</div>
        {details && (
          <>
            <button type="button" className="link small" onClick={() => setOpen(!open)} aria-expanded={open}>
              {open ? 'Hide details' : 'Show findings and recommendations'}
            </button>
            {open && details}
          </>
        )}
      </div>
    </div>
  )
}

/** Consecutive MCP tool calls by one agent, collapsed to one line; expand for arguments and results. */
export function ToolGroup({ item, forceOpen, live = false }: { item: Extract<TimelineItem, { kind: 'tools' }>; forceOpen: boolean; live?: boolean }) {
  const [open, setOpen] = useState(false)
  const shown = open || forceOpen
  const pending = item.calls.some((c) => c.result === undefined && c.error === undefined)
  return (
    <div className="item cat-tool">
      <Avatar agent={item.agent} mood={pending && live ? 'working' : 'idle'} />
      <div className="item-body">
        <div className="item-meta">
          <span className="item-agent">{agentLabel(item.agent)}</span>
          <span className="item-kind"><Icon name="tool" size={11} /> MCP tools</span>
          <span className="muted">{timeOf(item.timestamp)}</span>
        </div>
        <button type="button" className="tool-line" onClick={() => setOpen(!open)} aria-expanded={shown}>
          <Icon name={shown ? 'chevronDown' : 'chevronRight'} size={12} />
          {item.calls.map((c, i) => (
            <span key={i} className={`tool-chip${c.error ? ' tool-error' : ''}`}>
              {c.tool}
            </span>
          ))}
          {pending && <span className="muted small">running…</span>}
        </button>
        {shown && (
          <div className="tool-details">
            {item.calls.map((c, i) => (
              <div key={i} className="tool-call">
                <div className="small"><b>{c.tool}</b>(<code>{JSON.stringify(c.args)}</code>)</div>
                {c.error ? <div className="text-danger small">{c.error}</div>
                  : c.result === undefined ? <div className="muted small">waiting for result…</div>
                  : <Json value={c.result} />}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
