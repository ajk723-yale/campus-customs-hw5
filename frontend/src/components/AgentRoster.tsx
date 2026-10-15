import { useState } from 'react'
import type { AgentSummary } from '../activity'
import { AGENTS } from '../agents'
import type { AgentName } from '../api'
import { moodFor } from '../characters'
import { AgentCharacter } from './AgentCharacter'
import { Icon, Spinner } from './Icon'

const STATE_LABEL = { idle: 'not involved', working: 'working', waiting: 'waiting on a teammate', done: 'done', failed: 'stopped' } as const

interface Props {
  agents: AgentSummary[]
  filter: AgentName | null
  onFilter: (name: AgentName | null) => void
  live: boolean
}

/** One card per agent: what it's doing now (or its final summary), with details on demand. */
export function AgentRoster({ agents, filter, onFilter, live }: Props) {
  const [open, setOpen] = useState<AgentName | null>(null)
  return (
    <div className="roster">
      {agents.map((a) => {
        const id = AGENTS.find((x) => x.name === a.name)!
        const expanded = open === a.name
        return (
          <div key={a.name} className={`roster-card agent-${a.name} state-${a.state}${filter === a.name ? ' filtered' : ''}`}>
            <button
              type="button"
              className="roster-main"
              onClick={() => setOpen(expanded ? null : a.name)}
              aria-expanded={expanded}
            >
              <AgentCharacter who={a.name} mood={moodFor(a.state)} size={36} />
              <span className="roster-text">
                <span className="roster-name">
                  {id.label}
                  <span className="roster-state">
                    {(a.state === 'working' || a.state === 'waiting') && live ? <Spinner /> : null} {STATE_LABEL[a.state]}
                  </span>
                </span>
                <span className="roster-now">{a.state === 'idle' ? id.role : a.now}</span>
                {a.state !== 'idle' && (
                  <span className="roster-counts">
                    {a.toolCalls} tool call{a.toolCalls === 1 ? '' : 's'}
                    {a.delegationsOut > 0 && ` · ${a.delegationsOut} delegation${a.delegationsOut === 1 ? '' : 's'}`}
                  </span>
                )}
              </span>
              <Icon name={expanded ? 'chevronDown' : 'chevronRight'} size={14} />
            </button>
            {expanded && (
              <div className="roster-details small">
                {a.state === 'idle' ? (
                  <p className="muted">Not used in this run.</p>
                ) : (
                  <>
                    {a.toolsUsed.length > 0 && (
                      <div className="tool-chips">
                        {a.toolsUsed.map((t) => (
                          <span key={t} className="tool-chip"><Icon name="tool" size={11} /> {t}</span>
                        ))}
                      </div>
                    )}
                    {a.report?.findings && a.report.findings.length > 0 && (
                      <>
                        <div className="detail-label">Findings</div>
                        <ul>{a.report.findings.map((f, i) => <li key={i}>{f.fact} <span className="muted">({f.source_tool})</span></li>)}</ul>
                      </>
                    )}
                    {a.report?.recommendations && a.report.recommendations.length > 0 && (
                      <>
                        <div className="detail-label">Recommendations</div>
                        <ul>{a.report.recommendations.map((r, i) => <li key={i}><b>{r.action}</b> · {r.rationale}</li>)}</ul>
                      </>
                    )}
                    {a.report?.escalations && a.report.escalations.length > 0 && (
                      <>
                        <div className="detail-label">Escalations</div>
                        <ul>{a.report.escalations.map((e, i) => <li key={i}>to {e.to}: {e.reason}</li>)}</ul>
                      </>
                    )}
                  </>
                )}
                <button type="button" className="btn btn-small" onClick={() => onFilter(filter === a.name ? null : a.name)}>
                  {filter === a.name ? 'Show all agents' : `Show only ${id.label}`}
                </button>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
