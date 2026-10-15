import type { AgentState } from './activity'
import type { AgentName } from './api'

/** Who a character portrays: one of the five agents, or "You" (the manager). */
export type Who = AgentName | 'human'

/** Facial expression / motion of a character. */
export type Mood = 'idle' | 'working' | 'waiting' | 'happy' | 'worried' | 'celebrate' | 'talking'

/** An agent's mood follows its real state in the run (from the audit events). */
export function moodFor(state: AgentState): Mood {
  return ({ idle: 'idle', working: 'working', waiting: 'waiting', done: 'happy', failed: 'worried' } as const)[state]
}
