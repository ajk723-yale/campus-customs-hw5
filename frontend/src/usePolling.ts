import { useEffect, useRef } from 'react'

/** Call `fn` now and then every `delayMs` (skipping a tick if the previous call is still running). */
export function usePolling(fn: () => Promise<void>, delayMs: number) {
  const saved = useRef(fn)
  const busy = useRef(false)

  useEffect(() => {
    saved.current = fn
  }, [fn])

  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      if (busy.current || cancelled) return
      busy.current = true
      try {
        await saved.current()
      } finally {
        busy.current = false
      }
    }
    void tick()
    const id = window.setInterval(tick, delayMs)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [delayMs])
}
