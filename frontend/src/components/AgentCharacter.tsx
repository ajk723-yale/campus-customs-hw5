/** Friendly cartoon characters for the five agents (and "You", the manager).
 *  Pure SVG, drawn on a 64x64 grid. The face changes with the agent's real state;
 *  the gentle motion lives in App.css (.character.mood-*) and is switched off
 *  for people who prefer reduced motion. */

import type { Mood, Who } from '../characters'

const INK = '#2c2c2a'

interface Look {
  skin: string
  shirt: string
  hair: string
}

const LOOKS: Record<Who, Look> = {
  boss: { skin: '#e8b996', shirt: '#3c3489', hair: '#3b2a24' },
  inventory: { skin: '#c68863', shirt: '#0f6e56', hair: '#2a1d16' },
  accounting: { skin: '#f3d3b8', shirt: '#185fa5', hair: '#7a4a2a' },
  facilities: { skin: '#8d5a3b', shirt: '#993c1d', hair: '#1e1611' },
  customer_service: { skin: '#ebc0a0', shirt: '#993556', hair: '#4a2a1a' },
  human: { skin: '#d9a77f', shirt: '#5f5e5a', hair: '#55493f' },
}

function Body({ who }: { who: Who }) {
  const { shirt } = LOOKS[who]
  const torso = <path d="M10 64c1-11 9-17 22-17s21 6 22 17z" fill={shirt} />
  switch (who) {
    case 'boss':
      return (
        <g>
          {torso}
          <path d="M27 47l5 9 5-9z" fill="#fff" />
          <path d="M32 50l-2 4 2 8 2-8z" fill="#afa9ec" />
        </g>
      )
    case 'inventory':
      return (
        <g>
          {torso}
          <rect x="20" y="51" width="24" height="13" rx="1.5" fill="#c9a06a" stroke="#8a6a3d" strokeWidth="1" />
          <path d="M32 51v13M20 55h24" stroke="#8a6a3d" strokeWidth="1" />
          <circle cx="19" cy="57" r="3" fill={LOOKS.inventory.skin} />
          <circle cx="45" cy="57" r="3" fill={LOOKS.inventory.skin} />
        </g>
      )
    case 'accounting':
      return (
        <g>
          {torso}
          <path d="M26 47l6 6 6-6" fill="none" stroke="#e6f1fb" strokeWidth="2" strokeLinejoin="round" />
        </g>
      )
    case 'facilities':
      return (
        <g>
          <path d="M10 64c1-11 9-17 22-17s21 6 22 17z" fill="#d85a30" />
          <path d="M18 64V53h28v11" fill={shirt} />
          <path d="M22 50v6M42 50v6" stroke={shirt} strokeWidth="3" strokeLinecap="round" />
          <circle cx="25" cy="58" r="1.3" fill="#faece7" />
          <circle cx="39" cy="58" r="1.3" fill="#faece7" />
        </g>
      )
    case 'customer_service':
      return (
        <g>
          {torso}
          <path d="M27 47c2 3 8 3 10 0" fill="none" stroke="#fbeaf0" strokeWidth="2" />
        </g>
      )
    default:
      return (
        <g>
          {torso}
          <rect x="37" y="53" width="7" height="5" rx="1" fill="#f1efe8" />
        </g>
      )
  }
}

/** Hair, hats, and props that sit on or around the head. Drawn after the face where they overlap it. */
function HeadGear({ who, front }: { who: Who; front: boolean }) {
  const { hair } = LOOKS[who]
  if (!front) {
    switch (who) {
      case 'customer_service':
        return <path d="M45 26c5 4 6 12 2 17-1-6-2-10-4-13z" fill={hair} /> // ponytail
      case 'accounting':
        return <circle cx="32" cy="12" r="5" fill={hair} /> // bun
      default:
        return null
    }
  }
  switch (who) {
    case 'boss':
      return <path d="M18 26c0-9 6-14 14-14s14 5 14 13c-4-4-10-6-16-5-5 1-9 3-12 6z" fill={hair} />
    case 'inventory':
      return (
        <g>
          <path d="M17 25c0-9 7-14 15-14s15 5 15 14z" fill="#1d9e75" />
          <rect x="16" y="22" width="32" height="5" rx="2.5" fill="#5dcaa5" />
          <circle cx="32" cy="10" r="2.6" fill="#5dcaa5" />
        </g>
      )
    case 'accounting':
      return (
        <g>
          <path d="M18 25c1-8 7-12 14-12s13 4 14 12c-5-3-9-5-14-5s-9 2-14 5z" fill={hair} />
          <rect x="44" y="14" width="3" height="13" rx="1" transform="rotate(25 45 20)" fill="#ef9f27" />
        </g>
      )
    case 'facilities':
      return (
        <g>
          <path d="M17 24c0-9 7-14 15-14s15 5 15 14z" fill="#ef9f27" />
          <rect x="13" y="22" width="38" height="4" rx="2" fill="#ba7517" />
          <path d="M32 11v11" stroke="#ba7517" strokeWidth="2" />
        </g>
      )
    case 'customer_service':
      return (
        <g>
          <path d="M18 26c0-9 6-14 14-14s14 5 14 14c-3-5-8-8-14-8s-11 3-14 8z" fill={LOOKS.customer_service.hair} />
          <path d="M17 29a15 15 0 0130 0" fill="none" stroke="#444441" strokeWidth="2.2" />
          <rect x="14" y="26" width="5" height="8" rx="2" fill="#444441" />
          <path d="M17 33c0 5 5 6 10 5" fill="none" stroke="#444441" strokeWidth="1.6" />
          <circle cx="27.5" cy="38" r="1.6" fill="#444441" />
        </g>
      )
    default:
      return <path d="M18 25c0-8 6-13 14-13s14 5 14 13c-4-3-9-4-14-4s-10 1-14 4z" fill={hair} />
  }
}

function Face({ who, mood }: { who: Who; mood: Mood }) {
  const happyEyes = mood === 'happy' || mood === 'celebrate'
  const eyes = happyEyes ? (
    <g fill="none" stroke={INK} strokeWidth="1.8" strokeLinecap="round">
      <path d="M23.5 29q2.5-3 5 0" />
      <path d="M35.5 29q2.5-3 5 0" />
    </g>
  ) : (
    <g className="eyes" fill={INK}>
      {mood === 'working' ? (
        <>
          <circle cx="27" cy="29" r="1.9" />
          <circle cx="39" cy="29" r="1.9" />
        </>
      ) : mood === 'waiting' ? (
        <>
          <circle cx="25" cy="27" r="1.9" />
          <circle cx="37" cy="27" r="1.9" />
        </>
      ) : (
        <>
          <circle cx="26" cy="28" r="2" />
          <circle cx="38" cy="28" r="2" />
        </>
      )}
    </g>
  )
  const mouth = {
    idle: <path d="M28 35q4 2.5 8 0" fill="none" stroke={INK} strokeWidth="1.6" strokeLinecap="round" />,
    working: <ellipse cx="32" cy="36" rx="1.8" ry="2" fill={INK} />,
    waiting: <path d="M28.5 36h7" stroke={INK} strokeWidth="1.6" strokeLinecap="round" />,
    happy: <path d="M27 34q5 5 10 0" fill="none" stroke={INK} strokeWidth="1.8" strokeLinecap="round" />,
    celebrate: <path d="M26 33.5q6 8 12 0z" fill={INK} />,
    talking: <path d="M28 34q4 4 8 0z" fill={INK} />,
    worried: <path d="M27.5 37q4.5-3.5 9 0" fill="none" stroke={INK} strokeWidth="1.6" strokeLinecap="round" />,
  }[mood]
  const brows = mood === 'worried' ? (
    <g stroke={INK} strokeWidth="1.5" strokeLinecap="round">
      <path d="M23 24.5l5 1.5" />
      <path d="M41 24.5l-5 1.5" />
    </g>
  ) : mood === 'working' ? (
    <g stroke={INK} strokeWidth="1.3" strokeLinecap="round">
      <path d="M24 24.5h5" />
      <path d="M35 24.5h5" />
    </g>
  ) : null
  const glasses = who === 'accounting' ? (
    <g fill="none" stroke="#0c447c" strokeWidth="1.5">
      <circle cx="26" cy="28.5" r="4.4" />
      <circle cx="38" cy="28.5" r="4.4" />
      <path d="M30.4 28.5h3.2" />
    </g>
  ) : null
  const cheeks = mood === 'happy' || mood === 'celebrate' || mood === 'idle' || mood === 'talking'
  return (
    <g>
      {cheeks && (
        <g fill="#e0607e" opacity="0.28">
          <circle cx="21.5" cy="33" r="2.6" />
          <circle cx="42.5" cy="33" r="2.6" />
        </g>
      )}
      {brows}
      {eyes}
      {glasses}
      {mouth}
    </g>
  )
}

/** The character as an SVG group (64x64 grid), for embedding inside other SVGs such as the flow diagram. */
export function CharacterArt({ who, mood }: { who: Who; mood: Mood }) {
  const { skin } = LOOKS[who]
  return (
    <g className={`character-art mood-${mood}`}>
      <g className="char-body">
        <Body who={who} />
      </g>
      <g className="char-head">
        <HeadGear who={who} front={false} />
        <rect x="28" y="40" width="8" height="8" rx="3" fill={skin} />
        <circle cx="32" cy="29" r="14" fill={skin} />
        <circle cx="18" cy="30" r="2.6" fill={skin} />
        <circle cx="46" cy="30" r="2.6" fill={skin} />
        <Face who={who} mood={mood} />
        <HeadGear who={who} front />
      </g>
      {mood === 'working' && (
        <g className="bubble">
          <rect x="46" y="1" width="17" height="10" rx="5" fill="#fff" stroke="#c9ced6" strokeWidth="0.8" />
          <circle className="dot d1" cx="50.5" cy="6" r="1.2" fill={INK} />
          <circle className="dot d2" cx="54.5" cy="6" r="1.2" fill={INK} />
          <circle className="dot d3" cx="58.5" cy="6" r="1.2" fill={INK} />
        </g>
      )}
      {mood === 'celebrate' && (
        <g className="sparkles" fill="#ef9f27">
          <path d="M8 10l1.5 3 3 1.5-3 1.5-1.5 3-1.5-3-3-1.5 3-1.5z" />
          <path d="M55 6l1 2 2 1-2 1-1 2-1-2-2-1 2-1z" />
          <path d="M57 26l1 2 2 1-2 1-1 2-1-2-2-1 2-1z" />
        </g>
      )}
    </g>
  )
}

const TITLES: Record<Who, string> = {
  boss: 'Boss', inventory: 'Inventory', accounting: 'Accounting', facilities: 'Facilities',
  customer_service: 'Customer service', human: 'You',
}

/** A character in its own round badge. */
export function AgentCharacter({ who, mood, size = 40, title }: { who: Who; mood: Mood; size?: number; title?: string }) {
  return (
    <span
      className={`character agent-${who === 'human' ? 'human' : who} mood-${mood}`}
      style={{ width: size, height: size }}
      role="img"
      aria-label={title ?? `${TITLES[who]} (${mood})`}
    >
      <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true">
        <CharacterArt who={who} mood={mood} />
      </svg>
    </span>
  )
}
