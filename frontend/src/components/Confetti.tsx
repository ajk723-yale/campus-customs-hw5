import { useMemo } from 'react'

const COLORS = ['#7f77dd', '#1d9e75', '#378add', '#d85a30', '#d4537e', '#ef9f27']

/** A short, small confetti burst. Hidden entirely when the user prefers reduced motion (see App.css). */
export function Confetti({ pieces = 26 }: { pieces?: number }) {
  const bits = useMemo(
    () =>
      Array.from({ length: pieces }, (_, i) => ({
        left: 4 + ((i * 37) % 92),
        delay: (i % 7) * 60,
        drift: ((i * 53) % 60) - 30,
        rotate: (i * 47) % 360,
        color: COLORS[i % COLORS.length],
        round: i % 3 === 0,
      })),
    [pieces],
  )
  return (
    <div className="confetti" aria-hidden="true">
      {bits.map((b, i) => (
        <span
          key={i}
          className={b.round ? 'round' : undefined}
          style={{
            left: `${b.left}%`,
            background: b.color,
            animationDelay: `${b.delay}ms`,
            ['--drift' as string]: `${b.drift}px`,
            ['--rot' as string]: `${b.rotate}deg`,
          }}
        />
      ))}
    </div>
  )
}
