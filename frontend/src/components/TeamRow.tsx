import type { AgentSummary } from '../activity'
import { AGENTS } from '../agents'
import { moodFor } from '../characters'
import { AgentCharacter } from './AgentCharacter'

const STATUS = { idle: 'Ready', working: 'Working', waiting: 'Waiting on a teammate', done: 'Done', failed: 'Stopped' } as const

interface Props {
  agents: AgentSummary[] | null // null = no run yet
  live: boolean
  celebrating: boolean
}

/** The five agents side by side, each reacting to what it is actually doing in the selected run. */
export function TeamRow({ agents, live, celebrating }: Props) {
  return (
    <div className="team-row" aria-label="The agent team">
      {AGENTS.map((a) => {
        const s = agents?.find((x) => x.name === a.name)
        const state = s?.state ?? 'idle'
        const involved = state !== 'idle'
        const mood = celebrating && (involved || !agents) ? 'celebrate' : moodFor(state)
        const line = !agents ? a.role : !involved ? (live ? 'Standing by' : 'Not needed this run') : s!.now
        return (
          <div key={a.name} className={`team-member state-${state}${involved || !agents ? '' : ' benched'}`}>
            <AgentCharacter who={a.name} mood={mood} size={56} />
            <div className="team-name">{a.label}</div>
            <div className={`team-status agent-${a.name}`}>{agents ? STATUS[state] : 'Ready'}</div>
            <div className="team-line" title={line}>{line}</div>
          </div>
        )
      })}
    </div>
  )
}
