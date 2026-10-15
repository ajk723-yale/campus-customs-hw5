import type { Flow, FlowEdge, FlowNode } from '../activity'
import { agentLabel } from '../agents'
import type { AgentName } from '../api'
import type { Mood } from '../characters'
import { CharacterArt } from './AgentCharacter'

const COL_W = 272
const ROW_H = 74
const BOX_W = 166
const BOX_H = 54
const PAD = 8

interface Props {
  flow: Flow
  live: boolean
  celebrating: boolean
  onSelectAgent: (agent: AgentName) => void
  onSelectEdge: (eventKey: string) => void
}

/** Rows: leaves get their own row in delegation order; a parent sits at its first child's row. */
function layout(flow: Flow) {
  const children = new Map<string, string[]>()
  const hasParent = new Set<string>()
  for (const e of flow.edges) {
    children.set(e.from, [...(children.get(e.from) ?? []), e.to])
    hasParent.add(e.to)
  }
  const row = new Map<string, number>()
  let next = 0
  const visit = (id: string) => {
    const kids = children.get(id) ?? []
    if (!kids.length) { row.set(id, next++); return }
    kids.forEach(visit)
    row.set(id, row.get(kids[0])!)
  }
  flow.nodes.filter((n) => !hasParent.has(n.id)).forEach((n) => visit(n.id))
  const pos = new Map(flow.nodes.map((n) => [n.id, { x: PAD + n.depth * COL_W, y: PAD + (row.get(n.id) ?? 0) * ROW_H }]))
  const maxDepth = Math.max(0, ...flow.nodes.map((n) => n.depth))
  return { pos, width: PAD * 2 + maxDepth * COL_W + BOX_W, height: PAD * 2 + Math.max(1, next) * ROW_H - (ROW_H - BOX_H) }
}

function nodeMood(n: FlowNode, flow: Flow, live: boolean, celebrating: boolean): Mood {
  if (n.agent === 'human') return 'talking'
  if (n.refused) return 'worried'
  if (celebrating) return 'celebrate'
  if (!live) return 'happy'
  if (flow.edges.some((e) => e.from === n.id && e.status === 'active')) return 'waiting'
  if (flow.edges.some((e) => e.to === n.id && e.status === 'active')) return 'working'
  return 'happy'
}

const short = (s: string, n = 34) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

function edgeLabel(e: FlowEdge) {
  if (e.status === 'active') return 'working…'
  if (e.status === 'refused') return 'refused'
  if (e.status === 'failed') return 'stopped'
  if (e.status === 'approval') return 'needs you'
  return '✓ reported'
}

/** Who delegated to whom in this run, drawn from real delegation and approval events. */
export function CollaborationFlow({ flow, live, celebrating, onSelectAgent, onSelectEdge }: Props) {
  if (flow.nodes.length <= 1) {
    return <p className="muted small flow-empty">No delegations yet{live ? '. The Boss is reading the ticket…' : ' in this run.'}</p>
  }
  const { pos, width, height } = layout(flow)
  return (
    <div className="flow-wrap">
      <svg className="flow" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img"
        aria-label={`Delegation flow: ${flow.edges.map((e) => `${e.n}. ${agentLabel(flow.nodes.find((n) => n.id === e.from)?.agent)} to ${agentLabel(flow.nodes.find((n) => n.id === e.to)?.agent)} (${edgeLabel(e)})`).join('; ')}`}>
        <defs>
          <marker id="flow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0 0L10 5L0 10z" className="flow-arrowhead" />
          </marker>
        </defs>

        {flow.edges.map((e) => {
          const a = pos.get(e.from)!
          const b = pos.get(e.to)!
          const x1 = a.x + BOX_W
          const y1 = a.y + BOX_H / 2
          const x2 = b.x - 2
          const y2 = b.y + BOX_H / 2
          const mx = (x1 + x2) / 2
          return (
            <g key={e.id} className={`flow-edge edge-${e.status}`} onClick={() => onSelectEdge(e.eventKey)} tabIndex={0}
              onKeyDown={(k) => { if (k.key === 'Enter') onSelectEdge(e.eventKey) }}>
              <title>{`${e.n ? `${e.n}. ` : ''}${e.task}${e.note ? `\n→ ${e.note}` : ''}`}</title>
              <path d={`M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`} className="flow-line" markerEnd="url(#flow-arrow)" />
              <path d={`M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`} className="flow-hit" />
              {/* Arrow ends are unique per edge, so the number and status sit there without colliding. */}
              {e.n > 0 && (
                <g transform={`translate(${x2 - 22} ${y2 - 13})`}>
                  <circle r="8" className="flow-num" />
                  <text textAnchor="middle" dy="3.5" className="flow-num-text">{e.n}</text>
                </g>
              )}
              <text x={x2 - (e.n > 0 ? 34 : 10)} y={y2 - 9} textAnchor="end" className="flow-edge-label">{edgeLabel(e)}</text>
            </g>
          )
        })}

        {flow.nodes.map((n) => {
          const p = pos.get(n.id)!
          const label = n.agent === 'human' ? 'You' : agentLabel(n.agent)
          const sub = n.agent === 'human' ? (n.label ?? 'approval') : n.refused ? 'refused' : `depth ${n.depth}`
          const mood = nodeMood(n, flow, live, celebrating)
          return (
            <g key={n.id} transform={`translate(${p.x} ${p.y})`}
              className={`flow-node agent-${n.agent}${n.refused ? ' refused' : ''}`}
              onClick={() => n.agent !== 'human' && onSelectAgent(n.agent)}>
              <title>{n.agent === 'human' ? `You: decide ${n.label ?? ''} in the approvals column` : `Show only ${label}'s activity`}</title>
              <rect width={BOX_W} height={BOX_H} rx="12" className="flow-box" />
              <svg x="5" y="4" width="46" height="46" viewBox="0 0 64 64" className={`character mood-${mood}`}>
                <CharacterArt who={n.agent} mood={mood} />
              </svg>
              <text x="56" y="24" className="flow-label">{short(label, 17)}</text>
              <text x="56" y="40" className="flow-sub">{short(sub, 16)}</text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
