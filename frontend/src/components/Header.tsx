import { useState } from 'react'
import type { Cash, Health } from '../api'
import { Icon, Spinner } from './Icon'

interface Props {
  health: Health | null
  healthError: string | null
  cash: Cash | null
  onReset: () => Promise<void>
}

export function Header({ health, healthError, cash, onReset }: Props) {
  const [resetOpen, setResetOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const doReset = async () => {
    if (typed !== 'RESET') return setError('Type RESET to confirm.')
    setBusy(true)
    setError(null)
    try {
      await onReset()
      setResetOpen(false)
      setTyped('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <header className="header">
      <div className="brand">
        <span className="brand-mark"><Icon name="store" size={18} /></span>
        <div>
          <h1>Campus Customs ops desk</h1>
          <div className="muted small">
            {cash ? `Shop date ${cash.shop_date}` : 'Tickets, agent team, approvals, and cash'}
          </div>
        </div>
      </div>
      <div className="header-right">
        {healthError ? (
          <span className="pill pill-error" title={healthError}>
            <Icon name="alert" size={12} /> Backend unreachable
          </span>
        ) : health ? (
          <span className="pill pill-ok" title={`${health.mcp_tools} MCP tools`}>
            {health.active_run ? <Spinner /> : <Icon name="check" size={12} />}{' '}
            {health.active_run ? 'Agent run in progress' : `Connected · ${health.model}`}
          </span>
        ) : (
          <span className="pill pill-quiet"><Spinner /> Connecting…</span>
        )}
        <button type="button" className="btn" onClick={() => setResetOpen(!resetOpen)} aria-expanded={resetOpen}>
          <Icon name="refresh" size={14} /> Reset data
        </button>
      </div>

      {resetOpen && (
        <div className="reset-panel card" role="dialog" aria-label="Reset the working database">
          <p className="small">
            Restores the working database to the original for a fresh run. Payment approvals are archived and the audit
            trail is kept. This can't be undone.
          </p>
          <div className="btn-row">
            <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Type RESET" aria-label="Type RESET to confirm" />
            <button type="button" className="btn btn-reject" onClick={doReset} disabled={busy}>
              {busy ? <Spinner /> : null} Reset
            </button>
            <button type="button" className="btn" onClick={() => setResetOpen(false)}>Cancel</button>
          </div>
          {error && <div className="text-danger small">{error}</div>}
        </div>
      )}
    </header>
  )
}
