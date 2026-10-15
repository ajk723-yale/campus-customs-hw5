import { useEffect, useMemo, useRef, useState } from 'react'
import { buildFlow, buildTimeline, summarizeAgents } from '../activity'
import type { AgentEvent, AgentName, Run } from '../api'
import { AgentRoster } from './AgentRoster'
import { ActivityItem, ToolGroup } from './ActivityItem'
import { CollaborationFlow } from './CollaborationFlow'
import { Spinner } from './Icon'
import { TeamRow } from './TeamRow'

interface Props {
  runs: Run[] // this ticket's runs, oldest first
  events: AgentEvent[] // this ticket's events
  running: boolean
  celebrating: boolean
}

function runTitle(run: Run, index: number, runs: Run[]): string {
  if (run.kind === 'payment_execution') return `Payment ${run.approval_id ?? ''}`
  const n = runs.slice(0, index + 1).filter((r) => r.kind === 'ticket').length
  return `Team run ${n}`
}

/** Events that belong to a run: its own, plus human/backend events until the next run starts. */
function eventsOfRun(events: AgentEvent[], runs: Run[], i: number): AgentEvent[] {
  const run = runs[i]
  const next = runs[i + 1]?.started_at
  return events.filter((e) =>
    e.run_id === run.run_id
    || ((e.run_id === 'human' || e.run_id === 'api') && e.timestamp >= run.started_at && (!next || e.timestamp < next)),
  )
}

export function AgentActivity({ runs, events, running, celebrating }: Props) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [agentFilter, setAgentFilter] = useState<AgentName | null>(null)
  const [expandTools, setExpandTools] = useState(false)
  const [focusKey, setFocusKey] = useState<string | null>(null)
  const listRef = useRef<HTMLDivElement>(null)

  // Follow the newest run unless the manager picked an older one.
  const latest = runs[runs.length - 1]
  const runIndex = Math.max(0, runs.findIndex((r) => r.run_id === (selectedRunId ?? latest?.run_id)))
  const run = runs[runIndex]
  const runEvents = useMemo(() => (run ? eventsOfRun(events, runs, runIndex) : []), [events, runs, runIndex, run])
  const agents = useMemo(() => summarizeAgents(runEvents), [runEvents])
  const flow = useMemo(() => buildFlow(runEvents.filter((e) => e.run_id === run?.run_id)), [runEvents, run])
  const timeline = useMemo(() => {
    const items = buildTimeline(runEvents)
    if (!agentFilter) return items
    return items.filter((it) => (it.kind === 'tools' ? it.agent : it.event.agent) === agentFilter
      || (it.kind === 'event' && it.event.details.to === agentFilter))
  }, [runEvents, agentFilter])
  const isLive = run?.status === 'running'

  // Keep the newest activity in view while the team is working.
  useEffect(() => {
    const el = listRef.current
    if (el && isLive && !focusKey) el.scrollTop = el.scrollHeight
  }, [timeline.length, isLive, focusKey])

  // Clicking an arrow in the flow scrolls the timeline to that delegation and highlights it briefly.
  useEffect(() => {
    if (!focusKey || !listRef.current) return
    const target = [...listRef.current.querySelectorAll<HTMLElement>('[data-event-key]')]
      .find((el) => el.dataset.eventKey === focusKey)
    target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    const id = window.setTimeout(() => setFocusKey(null), 2500)
    return () => window.clearTimeout(id)
  }, [focusKey])

  const selectAgent = (a: AgentName) => setAgentFilter((cur) => (cur === a ? null : a))

  return (
    <div className="card activity">
      <div className="activity-head">
        <div className="card-title">
          Agent activity
          {isLive && (
            <span className="live">
              <Spinner /> team is working… updates every few seconds
            </span>
          )}
        </div>
        {runs.length > 1 && (
          <div className="run-tabs" role="tablist" aria-label="Runs">
            {runs.map((r, i) => (
              <button
                key={r.run_id}
                type="button"
                role="tab"
                aria-selected={i === runIndex}
                className={`run-tab${i === runIndex ? ' active' : ''}`}
                onClick={() => setSelectedRunId(i === runs.length - 1 ? null : r.run_id)}
              >
                {r.status === 'running' && <Spinner />} {runTitle(r, i, runs)}
              </button>
            ))}
          </div>
        )}
      </div>

      <TeamRow agents={runs.length ? agents : null} live={isLive} celebrating={celebrating} />

      {!runs.length ? (
        <p className="muted small">No agent runs for this ticket yet. Run the agent team to see how the team
          collaborates, with each agent's messages, delegations, and tool use.</p>
      ) : (
        <>
          <div className="section-label">How the team collaborated <span className="muted">· click an agent to filter, an arrow to jump to it</span></div>
          <CollaborationFlow flow={flow} live={isLive} celebrating={celebrating} onSelectAgent={selectAgent} onSelectEdge={setFocusKey} />

          <details className="roster-wrap">
            <summary className="section-label">Agent details: tools, findings, recommendations</summary>
            <AgentRoster agents={agents} filter={agentFilter} onFilter={setAgentFilter} live={isLive} />
          </details>

          <div className="timeline-tools">
            <span className="muted small">
              {agentFilter ? (
                <>Showing {agentFilter.replace('_', ' ')} only · <button type="button" className="link" onClick={() => setAgentFilter(null)}>show all</button></>
              ) : 'All agents'} · {timeline.length} steps
              {run?.status === 'failed' && run.error && <span className="text-danger"> · run failed: {run.error}</span>}
            </span>
            <label className="small">
              <input type="checkbox" checked={expandTools} onChange={(e) => setExpandTools(e.target.checked)} /> Expand all tool details
            </label>
          </div>

          <div className="timeline" ref={listRef} aria-live={isLive ? 'polite' : undefined}>
            {timeline.map((it) =>
              it.kind === 'tools' ? (
                <ToolGroup key={it.key} item={it} forceOpen={expandTools} live={isLive} />
              ) : (
                <ActivityItem key={it.key} event={it.event} focused={focusKey !== null && it.key === focusKey} />
              ),
            )}
            {isLive && (
              <div className="timeline-pending muted small">
                <Spinner /> waiting for the next step…
              </div>
            )}
          </div>
        </>
      )}
      {running && !isLive && runs.length > 0 && <p className="muted small">Starting…</p>}
    </div>
  )
}
