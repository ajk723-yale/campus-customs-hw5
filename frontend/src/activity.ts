/** Turns /api/events records into what the activity panel shows:
 *  - a per-agent summary (status, what it's doing now, tool and delegation counts, final summary)
 *  - a readable timeline where tool calls are grouped (expandable) and messages,
 *    delegations, approvals, payments, and errors stay visible. */

import { AGENTS, isAgent } from './agents'
import type { AgentEvent, AgentName, AgentReport, Run } from './api'

export type AgentState = 'idle' | 'working' | 'waiting' | 'done' | 'failed'

export interface AgentSummary {
  name: AgentName
  state: AgentState
  now: string // one line: what it is doing / last did
  toolCalls: number
  toolsUsed: string[]
  delegationsOut: number
  report: AgentReport | null // its final structured output (last one in the run)
  runs: number // how many times it was started in this run
  waitingOn: number // delegations it is still waiting on
}

export interface ToolCall {
  tool: string
  args: unknown
  result?: unknown
  error?: string
  timestamp: string
}

export type TimelineItem =
  | { kind: 'event'; key: string; event: AgentEvent }
  | { kind: 'tools'; key: string; agent: string; calls: ToolCall[]; timestamp: string }

/** Events that are noise in the main timeline (they feed the agent summaries instead). */
const HIDDEN = new Set(['agent_started', 'tool_call', 'tool_result', 'tool_error', 'decision'])

export const eventKey = (e: AgentEvent) => `${e.timestamp}|${e.run_id}|${e.event}|${e.agent ?? ''}|${e.tool ?? ''}`

export function summarizeAgents(events: AgentEvent[]): AgentSummary[] {
  const by = new Map<AgentName, AgentSummary>(
    AGENTS.map((a) => [a.name, { name: a.name, state: 'idle', now: 'Not involved yet', toolCalls: 0, toolsUsed: [],
      delegationsOut: 0, report: null, runs: 0, waitingOn: 0 }]),
  )
  for (const e of events) {
    if (!isAgent(e.agent)) continue
    const s = by.get(e.agent)!
    const d = e.details
    switch (e.event) {
      case 'agent_started':
        s.state = 'working'
        s.runs += 1
        s.now = 'Started working'
        break
      case 'tool_call':
        s.toolCalls += 1
        if (e.tool && !s.toolsUsed.includes(e.tool)) s.toolsUsed.push(e.tool)
        s.now = `Calling ${e.tool}…`
        break
      case 'tool_result':
        s.now = `Got ${e.tool} result`
        break
      case 'delegation_started':
        s.delegationsOut += 1
        s.waitingOn += 1
        s.now = `Waiting on ${String(d.to ?? '').replace(/_/g, ' ')}…`
        break
      case 'delegation_result':
      case 'delegation_failed':
        s.waitingOn = Math.max(0, s.waitingOn - 1)
        s.now = e.event === 'delegation_result'
          ? `Received ${String(d.to ?? '').replace(/_/g, ' ')}'s report`
          : `${String(d.to ?? '').replace(/_/g, ' ')} stopped at its limit`
        break
      case 'approval_requested':
        s.now = 'Prepared a request for human approval'
        break
      case 'agent_finished': {
        s.state = 'done'
        s.report = (d.output as AgentReport) ?? null
        s.now = s.report?.summary ?? 'Finished'
        break
      }
      case 'agent_failed':
        s.state = 'failed'
        s.now = `Stopped: ${String(d.error ?? 'error')}`
        break
    }
  }
  for (const s of by.values()) if (s.state === 'working' && s.waitingOn > 0) s.state = 'waiting'
  return [...by.values()]
}

// ---------------------------------------------------------------------------
// Collaboration flow: who delegated to whom, built only from real events
// ---------------------------------------------------------------------------

export interface FlowNode {
  id: string
  agent: AgentName | 'human'
  depth: number
  label?: string // e.g. approval ID on the "You" node
  refused?: boolean
}

export interface FlowEdge {
  id: string
  from: string
  to: string
  n: number // order in the run
  task: string
  status: 'active' | 'done' | 'refused' | 'failed' | 'approval'
  note?: string
  eventKey: string // timeline anchor
}

export interface Flow {
  nodes: FlowNode[]
  edges: FlowEdge[]
}

/** Build the delegation tree for one run from delegation_* and approval_requested events. */
export function buildFlow(events: AgentEvent[]): Flow {
  const nodes: FlowNode[] = []
  const edges: FlowEdge[] = []
  const current = new Map<string, string>() // `${agent}@${depth}` -> latest node id
  const add = (n: FlowNode) => { nodes.push(n); current.set(`${n.agent}@${n.depth}`, n.id); return n.id }
  let count = 0

  const start = events.find((e) => e.event === 'run_started')
  if (!start) return { nodes, edges }
  const entry = isAgent(start.agent) ? start.agent : 'boss'
  const approved = (start.details.human_approved_payment_ids as string[] | undefined) ?? []
  if (approved.length) {
    // A payment-execution run: a person's approval started it.
    const you = add({ id: 'you-start', agent: 'human', depth: 0, label: approved[0] })
    const acct = add({ id: `n${nodes.length}`, agent: entry, depth: 1 })
    edges.push({ id: 'e-approval', from: you, to: acct, n: 0, task: `Approved ${approved[0]}`, status: 'done',
      note: 'you approved', eventKey: eventKey(start) })
  } else {
    add({ id: 'n0', agent: entry, depth: 0 })
  }
  const offset = approved.length ? 1 : 0

  for (const e of events) {
    const d = e.details
    const depth = (e.depth ?? 0) + offset
    const fromId = current.get(`${e.agent}@${depth}`)
    if (!fromId || !isAgent(e.agent)) continue
    if (e.event === 'delegation_started' && isAgent(String(d.to))) {
      const to = add({ id: `n${nodes.length}`, agent: d.to as AgentName, depth: depth + 1 })
      edges.push({ id: `e${edges.length}`, from: fromId, to, n: ++count, task: String(d.task ?? ''), status: 'active', eventKey: eventKey(e) })
    } else if (e.event === 'delegation_result' || e.event === 'delegation_failed') {
      const edge = [...edges].reverse().find((x) => x.from === fromId && x.status === 'active'
        && nodes.find((n) => n.id === x.to)?.agent === d.to)
      if (edge) {
        edge.status = e.event === 'delegation_result' ? 'done' : 'failed'
        edge.note = e.event === 'delegation_result'
          ? ((d.report as AgentReport | undefined)?.summary ?? 'reported back')
          : String(d.error ?? 'stopped at its limit')
      }
    } else if (e.event === 'delegation_refused' && isAgent(String(d.to))) {
      const id = `n${nodes.length}`
      nodes.push({ id, agent: d.to as AgentName, depth: depth + 1, refused: true })
      edges.push({ id: `e${edges.length}`, from: fromId, to: id, n: ++count, task: String(d.task ?? ''), status: 'refused',
        note: String(d.reason ?? 'refused'), eventKey: eventKey(e) })
    } else if (e.event === 'approval_requested') {
      const r = (d.result ?? {}) as Record<string, unknown>
      const id = `you-${String(r.approval_id)}`
      nodes.push({ id, agent: 'human', depth: depth + 1, label: String(r.approval_id) })
      edges.push({ id: `e${edges.length}`, from: fromId, to: id, n: ++count, task: `Prepared ${String(r.approval_id)} for your approval`,
        status: 'approval', note: String(r.description ?? ''), eventKey: eventKey(e) })
    }
  }
  return { nodes, edges }
}

export function buildTimeline(events: AgentEvent[]): TimelineItem[] {
  const items: TimelineItem[] = []
  const open = new Map<string, ToolCall[]>() // agent -> calls waiting for results, in order
  for (const e of events) {
    if (e.event === 'tool_call' || e.event === 'tool_result' || e.event === 'tool_error') {
      const agent = e.agent ?? 'unknown'
      const last = items[items.length - 1]
      if (e.event === 'tool_call') {
        const call: ToolCall = { tool: e.tool ?? '?', args: e.details.args, timestamp: e.timestamp }
        if (last && last.kind === 'tools' && last.agent === agent) last.calls.push(call)
        else items.push({ kind: 'tools', key: `tools|${eventKey(e)}`, agent, calls: [call], timestamp: e.timestamp })
        open.set(agent, [...(open.get(agent) ?? []), call])
      } else {
        const pending = open.get(agent) ?? []
        const idx = pending.findIndex((c) => c.tool === e.tool && c.result === undefined && c.error === undefined)
        if (idx >= 0) {
          const call = pending[idx]
          if (e.event === 'tool_result') call.result = e.details.result
          else call.error = String(e.details.error ?? e.details.reason ?? 'error')
          pending.splice(idx, 1)
        }
      }
      continue
    }
    if (HIDDEN.has(e.event)) continue
    items.push({ kind: 'event', key: eventKey(e), event: e })
  }
  return items
}

/** The runs (since the last reset) that belong to a ticket, oldest first. */
export function ticketRuns(runs: Run[], ticketId: number): Run[] {
  return runs.filter((r) => r.ticket_id === ticketId && r.kind !== 'other').sort((a, b) => a.started_at.localeCompare(b.started_at))
}

/** Keep a ticket's events from its current runs, plus human/backend events since its first run. */
export function eventsForTicket(events: AgentEvent[], runs: Run[]): AgentEvent[] {
  if (!runs.length) return []
  const ids = new Set(runs.map((r) => r.run_id))
  const since = runs[0].started_at
  return events.filter((e) => ids.has(e.run_id) || ((e.run_id === 'human' || e.run_id === 'api') && e.timestamp >= since))
}
