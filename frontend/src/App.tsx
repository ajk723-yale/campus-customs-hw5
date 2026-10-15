import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import { eventKey, eventsForTicket, ticketRuns } from './activity'
import {
  decideApproval, fetchApprovals, fetchCash, fetchEvents, fetchHealth, fetchRuns, fetchTicketUpdates, fetchTickets,
  resetDatabase, runTicket,
  type AgentEvent, type Approval, type Cash, type Health, type Run, type Ticket, type TicketUpdates,
} from './api'
import type { PurchaseWarnings } from './components/PurchaseActions'
import { ApprovalQueue } from './components/ApprovalQueue'
import { Header } from './components/Header'
import { TicketDetail } from './components/TicketDetail'
import { TicketList } from './components/TicketList'
import { usePolling } from './usePolling'

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [cash, setCash] = useState<Cash | null>(null)
  const [updates, setUpdates] = useState<Record<number, TicketUpdates>>({})
  const [cashError, setCashError] = useState<string | null>(null)
  const [events, setEvents] = useState<AgentEvent[]>([])
  // ?ticket=102 opens a ticket directly (bookmarkable); otherwise the first ticket.
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    const n = Number(new URLSearchParams(window.location.search).get('ticket'))
    return Number.isInteger(n) && n > 0 ? n : null
  })
  const [startingId, setStartingId] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [highlightTicket, setHighlightTicket] = useState<number | null>(null)
  const [approverName, setApproverName] = useState(() => localStorage.getItem('approverName') ?? '')
  const [celebrating, setCelebrating] = useState<Set<number>>(new Set())
  const lastStatus = useRef<Map<number, string>>(new Map())

  // Celebrate only a real change: a ticket the backend had as open is now resolved.
  // (Tickets already resolved when the page loads are not celebrated.)
  const noticeResolutions = useCallback((list: Ticket[]) => {
    const newlyResolved = list.filter((t) => lastStatus.current.get(t.id) === 'open' && t.status === 'resolved').map((t) => t.id)
    lastStatus.current = new Map(list.map((t) => [t.id, t.status]))
    if (!newlyResolved.length) return
    setCelebrating((cur) => new Set([...cur, ...newlyResolved]))
    window.setTimeout(() => setCelebrating((cur) => new Set([...cur].filter((id) => !newlyResolved.includes(id)))), 4500)
  }, [])

  // Events are fetched per selected ticket, then only new ones (since the last timestamp).
  const eventsFor = useRef<number | null>(null)
  const lastTs = useRef<string | undefined>(undefined)

  const loadEvents = useCallback(async (ticketId: number) => {
    if (eventsFor.current !== ticketId) {
      eventsFor.current = ticketId
      lastTs.current = undefined
      setEvents([])
    }
    const fresh = await fetchEvents({ ticketId, since: lastTs.current })
    if (eventsFor.current !== ticketId || fresh.length === 0) return
    lastTs.current = fresh[fresh.length - 1].timestamp
    setEvents((old) => {
      const seen = new Set(old.map(eventKey))
      return [...old, ...fresh.filter((e) => !seen.has(eventKey(e)))]
    })
  }, [])

  const refresh = useCallback(async () => {
    let t: Ticket[] = []
    try {
      const [h, tk, r, a] = await Promise.all([fetchHealth(), fetchTickets(), fetchRuns(), fetchApprovals()])
      t = tk
      setHealth(h)
      setTickets(t)
      noticeResolutions(t)
      setRuns(r)
      setApprovals(a)
      setHealthError(null)
      setSelectedId((id) => id ?? t[0]?.id ?? null)
    } catch (e) {
      setHealthError(errorText(e))
      return
    }
    // Manager events and purchase warnings for every ticket (read-only; the same data the agents read).
    Promise.all(t.map((x) => fetchTicketUpdates(x.id).catch(() => null)))
      .then((list) => setUpdates(Object.fromEntries(list.filter(Boolean).map((u) => [u!.ticket_id, u!]))))
    // The actual balance is re-read every refresh, so it updates right after a payment executes.
    fetchCash().then((c) => { setCash(c); setCashError(null) }).catch((e) => setCashError(errorText(e)))
    if (selectedId !== null) await loadEvents(selectedId).catch(() => undefined)
  }, [selectedId, loadEvents, noticeResolutions])

  const anyRunning = health?.active_run != null || runs.some((r) => r.status === 'running')
  usePolling(refresh, anyRunning ? 1500 : 8000)
  useEffect(() => { void refresh() }, [selectedId, refresh])

  const ticket = tickets.find((t) => t.id === selectedId) ?? null
  const tRuns = useMemo(() => (ticket ? ticketRuns(runs, ticket.id) : []), [runs, ticket])
  const tEvents = useMemo(() => eventsForTicket(events, tRuns), [events, tRuns])
  const activeRun = tRuns.find((r) => r.status === 'running') ?? null
  const otherRunActive = health?.active_run != null && !tRuns.some((r) => r.run_id === health.active_run)

  const onRun = async () => {
    if (!ticket) return
    setStartingId(ticket.id)
    setNotice(null)
    try {
      await runTicket(ticket.id)
      await refresh()
    } catch (e) {
      setNotice(`Couldn't start the run: ${errorText(e)}`)
    } finally {
      setStartingId(null)
    }
  }

  const onDecide = async (approvalId: string, action: 'approve' | 'reject' | 'execute', confirm: string, reason = '') => {
    const result = await decideApproval(approvalId, action, approverName.trim(), confirm, reason)
    await refresh()
    return result
  }

  const onReset = async () => {
    await resetDatabase()
    eventsFor.current = null
    setEvents([])
    await refresh()
  }

  const warningsById = useMemo(() => {
    const m = new Map<string, PurchaseWarnings>()
    for (const u of Object.values(updates))
      for (const p of u.purchases)
        if (p.cash_warning !== undefined || p.duplicate_warnings)
          m.set(p.approval_id, { cash_warning: p.cash_warning ?? null, duplicate_warnings: p.duplicate_warnings ?? [] })
    return m
  }, [updates])
  const managerDisabledReason = health?.active_run ? 'An agent run is in progress. Record manager actions when it finishes.' : null

  const onReviewApprovals = () => {
    setHighlightTicket(ticket?.id ?? null)
    document.getElementById('approvals')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    window.setTimeout(() => setHighlightTicket(null), 4000)
  }

  const onApproverName = (name: string) => {
    setApproverName(name)
    localStorage.setItem('approverName', name)
  }

  return (
    <div className="app">
      <Header health={health} healthError={healthError} cash={cash} onReset={onReset} />
      {healthError && (
        <div className="banner banner-error" role="alert">
          Can't reach the backend ({healthError}). Start it from backend/ with uvicorn on the port this dev server proxies
          to (8000 by default, or BACKEND_PORT).
        </div>
      )}
      {notice && (
        <div className="banner banner-warning" role="alert">
          {notice} <button type="button" className="link" onClick={() => setNotice(null)}>Dismiss</button>
        </div>
      )}
      <main className="grid">
        <TicketList tickets={tickets} selectedId={selectedId} onSelect={setSelectedId} celebrating={celebrating} />
        {ticket ? (
          <TicketDetail
            ticket={ticket}
            runs={tRuns}
            events={tEvents}
            activeRun={activeRun}
            canRun={!otherRunActive && !healthError}
            runBlockedReason={otherRunActive ? 'Another agent run is in progress. One run at a time.' : null}
            starting={startingId === ticket.id}
            onRun={onRun}
            onReviewApprovals={onReviewApprovals}
            celebrating={celebrating.has(ticket.id)}
            updates={updates[ticket.id] ?? null}
            approverName={approverName}
            managerDisabledReason={managerDisabledReason}
            onManagerRecorded={refresh}
          />
        ) : (
          <section className="column column-center"><p className="muted">Select a ticket.</p></section>
        )}
        <ApprovalQueue
          approvals={approvals}
          runs={runs}
          cash={cash}
          cashError={cashError}
          approverName={approverName}
          onApproverName={onApproverName}
          highlightTicketId={highlightTicket}
          onDecide={onDecide}
          warningsById={warningsById}
          disabledReason={managerDisabledReason}
          onManagerDone={refresh}
        />
      </main>
    </div>
  )
}
