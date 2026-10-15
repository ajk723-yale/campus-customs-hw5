# Campus Customs dashboard (React + Vite + TypeScript)

The operations desk for the Campus Customs agent team. It talks only to the existing FastAPI backend (`../backend/main.py`) through `/api/*`; Vite proxies those calls, so no keys or backend settings reach the browser.

## Run it

Full steps are in the project [README](../README.md) (steps 5–6). In short, this project uses backend port **8010** and dashboard port **5180**:

1. Backend, from `backend/`:

   ```bash
   ../.venv/bin/uvicorn main:app --port 8010
   ```

2. Frontend, from `frontend/` (first time: `npm install`):

   ```bash
   BACKEND_PORT=8010 npm run dev -- --port 5180 --strictPort
   ```

3. Open **http://localhost:5180** (page title "Campus Customs ops desk"). `?ticket=102` opens a ticket directly.

Don't rely on Vite's default port: if 5173 is busy, Vite moves to the next free port, and an older app already on 5173 may be what you see. Without `BACKEND_PORT`, `/api` goes to port 8000, which may be a different app's server.

## Layout

| Column | What it shows |
|---|---|
| Left | Ticket cards 101–103: status (`open` / `resolved` from the backend), running spinner, pending approvals, next step |
| Center | Selected ticket: **Next action** banner (backend `next_step` + `remaining_actions` checklist, Run / Review approvals buttons), Boss decision, **Agent activity** (agent roster + timeline) |
| Right | Actual checking balance, then **payments needing you** (with actual vs. projected balance), then **purchase requests** (no cash impact), then history |

## Files

```
src/
  api.ts            typed client for every backend route (types mirror backend/models.py)
  activity.ts       turns /api/events into agent summaries and a grouped timeline
  agents.ts         the five agents' labels and roles; money/time formatting
  usePolling.ts     refresh loop (1.5 s while a run is active, 8 s otherwise)
  App.tsx           state, polling, actions
  components/
    Header.tsx, TicketList.tsx, TicketCard.tsx, TicketDetail.tsx, NextAction.tsx,
    AgentActivity.tsx, TeamRow.tsx, CollaborationFlow.tsx, AgentRoster.tsx,
    ActivityItem.tsx (incl. ToolGroup), AgentCharacter.tsx, Confetti.tsx,
    ApprovalQueue.tsx, ApprovalCard.tsx, CashCard.tsx, Icon.tsx
  characters.ts     character moods; an agent's mood follows its real state
```

## Characters, collaboration flow, and animation

- Each agent is a cartoon character whose expression follows its real state in the run (from `/api/events`).
- The collaboration flow is drawn only from real `delegation_*` and `approval_requested` events.
- A short celebration plays only when a ticket the backend had as open becomes resolved while you watch.
- All motion is off when the OS "reduce motion" setting is on.

## Manager actions (Problem 9)

- **Center column, "Manager actions" panel** (shown once a ticket has had a team run):
  - lists the ticket's recorded events, each labelled **Simulated** or **Manager decision**
  - has forms for: customer response, pricing decision (price requests), stock received against the ticket's invoice, and order fulfilled
- **Right column, purchase cards:**
  - approved: **Place order** and **Cancel**
  - ordered: **Record receipt**
  - cash and possible-duplicate warnings appear first, and each needs a checkbox acknowledgement
- **Every form** needs your name ("Approving as"), a typed ID, a basis, and the Simulated checkbox (ticked by default for customer and vendor events).
- **Nothing here** moves cash or resolves a ticket. Run the team again and the Boss decides.

## Safety (all enforced by the backend; the UI only reflects it)

- The UI never decides resolution: status, `resolution`, `remaining_actions`, and `next_step` come from `/api/tickets`.
- Approve / Reject send the person's name and the approval ID typed back, as `/api/approvals/{id}/approve|reject` requires.
- Approving a payment starts the Accounting Agent's execution; the balance shown is re-read from `/api/cash` on every refresh. Projections on payment cards are labelled as estimates.
- Approving a purchase only records the decision (no order, no cash or inventory change), and the card says so.
- Reset needs the word RESET typed in.
