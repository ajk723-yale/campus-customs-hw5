import { useEffect, useRef, useState } from 'react'
import type { Cash } from '../api'
import { money } from '../agents'
import { Icon } from './Icon'

/** The actual checking balance, as returned by GET /api/cash. */
export function CashCard({ cash, error }: { cash: Cash | null; error: string | null }) {
  const prev = useRef<number | null>(null)
  const [changed, setChanged] = useState<{ from: number; to: number } | null>(null)

  useEffect(() => {
    if (cash && prev.current !== null && prev.current !== cash.balance) {
      setChanged({ from: prev.current, to: cash.balance })
      const id = window.setTimeout(() => setChanged(null), 8000)
      prev.current = cash.balance
      return () => window.clearTimeout(id)
    }
    if (cash) prev.current = cash.balance
  }, [cash])

  return (
    <div className={`card cash${changed ? ' cash-changed' : ''}`} aria-live="polite">
      <div className="card-title"><Icon name="bank" size={14} /> Checking balance <span className="pill pill-quiet">actual</span></div>
      {cash ? (
        <>
          <div className="cash-amount">{money(cash.balance)}</div>
          <div className="muted small">From the cash_accounts table · as of {cash.as_of}</div>
          {changed && (
            <div className="cash-delta small">
              Updated after a payment: {money(changed.from)} → {money(changed.to)}
            </div>
          )}
        </>
      ) : (
        <div className="muted small">{error ?? 'Loading…'}</div>
      )}
    </div>
  )
}
