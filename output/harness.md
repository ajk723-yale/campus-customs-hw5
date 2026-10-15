# Harness — Homework 5

## Databases

| File | Role |
|---|---|
| `data/campus_customs.db` | Original data. Kept unchanged as the clean reference. |
| `data/campus_customs_new.db` | Byte-for-byte copy of the original (same SHA-1). This is the working copy the agents read and write. |

Today's date in the shop (`desk.date_today`) is **2026-08-31**.

## Tables

### `desk`
| Field | Type | Notes |
|---|---|---|
| `date_today` | TEXT, required | The shop's "today" (2026-08-31) |
| `notes` | TEXT | Free-text desk notes (empty) |

**Why it matters:** gives the agents a fixed "today". They need it to tell whether a bill is overdue or a deadline is coming, instead of using the real clock.

### `inventory`
| Field | Type | Notes |
|---|---|---|
| `sku` | TEXT, required | Product code. Primary key with `size` |
| `name` | TEXT, required | Product name |
| `size` | TEXT, required | S / M / L / XL, or OS (one size) |
| `qty` | INTEGER, required | Units on hand |
| `location` | TEXT, required | Aisle |

**Why it matters:** shows whether an order can be filled from stock. For example, the white tee in size S has 0 on hand, and the navy hoodie in size M has only 8.

### `pricing`
| Field | Type | Notes |
|---|---|---|
| `sku` | TEXT, primary key | Product code |
| `unit_cost` | REAL, required | What the shop pays per unit |
| `list_price` | REAL, required | Normal selling price |

**Why it matters:** lets an agent quote a price and check the margin before agreeing to a discount, so it never sells below cost.

### `vendors`
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER, primary key | Vendor ID |
| `name` | TEXT, required | Vendor name |
| `specialty` | TEXT, required | What they supply |
| `lead_days` | INTEGER, required | Days to deliver |

**Why it matters:** tells an agent who can restock an item and how long it takes, so it can promise realistic dates. It also identifies who an invoice is owed to.

### `leases`
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER, primary key | Lease ID |
| `space_name` | TEXT, required | Rented space |
| `landlord` | TEXT, required | Who is owed rent |
| `monthly_rent` | REAL, required | Rent amount |
| `next_due` | TEXT, required | Next due date |
| `notes` | TEXT | Notes (empty) |

**Why it matters:** this is the authoritative rent amount and due date. An agent should check a rent request against this table rather than trusting the email.

### `cash_accounts`
| Field | Type | Notes |
|---|---|---|
| `name` | TEXT, primary key | Account name (`checking`) |
| `balance` | REAL, required | Current balance |
| `date` | TEXT, required | As-of date |

**Why it matters:** shows how much money is available. An agent must check it before paying anything so the account isn't overdrawn.

### `payments`
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER, primary key | Payment ID |
| `kind` | TEXT, required | What was paid, e.g. rent or invoice |
| `ref_id` | INTEGER | ID of the lease or invoice paid |
| `amount` | REAL, required | Amount paid |
| `account` | TEXT, required | Account the money came from |
| `paid_at` | TEXT, required | When it was paid |
| `approved_by` | TEXT, required | Who approved it |

**Why it matters:** this is where agent payments get recorded, along with who approved each one. It starts empty, so nothing has been paid yet.

### `invoices`
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER, primary key | Invoice ID |
| `vendor_id` | INTEGER, required | Links to `vendors.id` |
| `amount` | REAL, required | Amount owed |
| `due_date` | TEXT, required | Due date |
| `status` | TEXT, required | e.g. `open` |
| `description` | TEXT | What it's for |

**Why it matters:** lists the shop's unpaid bills. The only one, invoice 501, is still open and was due 2026-08-28, so it is already overdue.

### `tickets`
| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER, primary key | Ticket ID |
| `type` | TEXT, required | `customer_order`, `rent_notice`, or `price_override` |
| `requester` | TEXT, required | Who asked |
| `subject` | TEXT, required | Short title |
| `sku`, `size`, `qty` | TEXT / TEXT / INTEGER | Product requested, if any |
| `lease_id` | INTEGER | Links to `leases.id` |
| `invoice_id` | INTEGER | Links to `invoices.id` |
| `status` | TEXT, required | e.g. `open` |
| `notes` | TEXT | Details of the request |
| `created_at` | TEXT, required | Timestamp |

**Why it matters:** these are the agents' work queue. Each ticket is a request to handle, and its link fields point to the other tables an agent needs to check.

## The three tickets

| Ticket | Request | Related data | What it shows |
|---|---|---|---|
| **101** `customer_order` (Tauhid Zaman) | 1 Classic Bulldog Tee, size S | `inventory`: CC-TEE-WHITE S has **0** on hand. `pricing`: $28 list price. `invoices` 501: **$840** rush reprint of exactly that tee and size from Bulldog Print Co (5-day lead time), status `open`, due 2026-08-28 (**overdue**) | The order can't be filled from stock. A restock is on order, but its invoice hasn't been paid. |
| **102** `rent_notice` (Elm City Properties) | Email says shop rent is due in 2 days | `leases` 1: **$2,400** due **2026-09-02** (2 days after 2026-08-31). `cash_accounts`: checking holds **$3,400**. `payments`: empty | The email matches the lease. Paying the rent would be the biggest draw on cash. |
| **103** `price_override` (Yale AI Club) | 20 navy hoodies, size M, at a bulk discount | `inventory`: CC-HOOD-NAVY M has only **8** (L has 14). `pricing`: cost **$22**, list **$58** | The shop has less than half the hoodies requested. A discount needs approval and must stay above the $22 cost. |

**How the tickets connect:** all three draw on the same $3,400 in checking. Rent ($2,400) plus invoice 501 ($840) comes to $3,240, which would leave just **$160**. Paying both is possible but leaves almost nothing in the account. Ticket 101 also depends on invoice 501 being settled before the reprinted tee arrives.

## Agent team (Problem 5)

Five PydanticAI agents in `backend/`, all using **`gpt-6-luna` through Portkey** (`https://api.portkey.ai/v1`, header `x-portkey-provider: openai`; key `PORTKEY_API_KEY` from `AI code/.env`). Each has a system prompt in `backend/prompts/<name>.md`, a structured output type in `backend/models.py`, and only the MCP tools listed for it.

```
Boss             ──delegate_to_specialist──>  Inventory | Accounting | Facilities | Customer Service
Inventory        ──consult_agent──>           Accounting
Facilities       ──consult_agent──>           Accounting
Customer Service ──consult_agent──>           Inventory | Accounting
Accounting       (delegates to no one: end of every chain)

Every agent ──MCP over stdio──> mcp_server/server.py ──> data/campus_customs_new.db
```

| Agent | Responsibility | MCP tools | Can delegate to | Can never |
|---|---|---|---|---|
| **Boss** | Delegates, weighs reports, sets priorities and next steps per ticket, lists payments that need a human | `get_shop_date`, `list_tickets`, `get_ticket`, `list_payment_approvals`, `get_ticket_updates` | inventory, accounting, facilities, customer_service | Pay, approve payments, edit tickets |
| **Inventory** | Stock, shortages, restock quantity, vendor choice, lead time, vendor restrictions | `get_shop_date`, `get_ticket`, `get_product_info`, `get_product_sizes`, `list_vendors`, `get_vendor_status`, `get_invoice_info`, `request_purchase_approval`, `get_ticket_updates` | accounting | Place orders (`order_placed` is always false); it can only file a purchase request for a human |
| **Accounting** | Invoices, due dates, cash, payment priorities; files approval requests; executes **human-approved** payments | `get_shop_date`, `get_ticket`, `get_invoice_info`, `list_open_invoices`, `get_cash_position`, `get_rent_info`, `request_payment_approval`, `list_payment_approvals`, `execute_payment`, `get_ticket_updates` | none | Pay without human approval; plan a negative balance; count expected revenue |
| **Facilities** | Rent and lease terms, checking notices against the lease, urgency (judged from `days_until_due`, no fixed threshold) | `get_shop_date`, `get_ticket`, `get_rent_info`, `get_cash_position` | accounting | Pay or request payments |
| **Customer Service** | Orders and price requests, pricing recommendations, draft replies | `get_shop_date`, `get_ticket`, `get_product_info`, `get_product_sizes`, `quote_price`, `get_ticket_updates` | inventory, accounting | Contact customers (drafts have `sent` always false); price below cost |

**How delegation works:** a delegation tool runs the target agent as a nested PydanticAI run with its own limits. The target gets a short task plus ticket IDs and returns its structured report as the tool result. Accounting is the end of every chain. A delegation is refused, and the refusal logged, if the target isn't allowed, the target is already in the current chain (no loops), the depth would exceed 2, or the run has already used 10 delegations.

**Output checks:** each report is validated before it's accepted. A failure is sent back to the model to fix.
- Accounting's `cash_after_plan` must equal cash minus planned payments, must be ≥ 0, and its cash and amounts must match MCP results from this run.
- Inventory's `on_hand` must match MCP.
- Facilities' `days_until_due` must match what `get_rent_info` calculated from `desk.date_today`. Its `urgency` is free text, with `urgency_reasoning` citing the numbers.
- Customer Service's prices must be ≥ cost and its cost and list price must match MCP.
- A restricted vendor can't have `can_order_now=true`.
- Payment amounts the Boss lists must have come from MCP.
- **Payment requests come from Accounting.** Every payment the Boss lists must carry an `approval_id` that Accounting filed (or found already filed) in this run. The only exception is a payment Accounting tried to file and was refused. Otherwise the Boss is told to delegate to Accounting.
- **Resolution is the Boss's call.** A ticket marked `resolved` can't have `remaining_actions`, payments still to execute, or a status of awaiting approval, blocked, or needs more info. `resolves_when_payments_executed` is allowed only when nothing else remains, may name only payment requests Accounting filed, and never names purchases.

## MCP server tools

`mcp_server/server.py` (FastMCP; see `mcp_server/README.md`) is the agents' only source of shop facts. It has 24 tools: the 17 below, plus 7 for manager actions listed in the Manager actions section. Every tool reads `data/campus_customs_new.db`. Lookups open it read-only. Only two tools write to it: `execute_payment` (human-approved payments) and `set_ticket_status` (backend only, no agent has it).

| Tool | Tables used | Ticket(s) helped | Why it is useful |
|---|---|---|---|
| `get_product_info(sku, size)` | `inventory`, `pricing` | **101**, **103** | It shows that the size S tee has 0 on hand (101) and that only 8 size M hoodies exist against a $22 cost and $58 list price (103), so the agent can say what's in stock and how far a bulk discount can go. |
| `get_invoice_info(invoice_id)` | `invoices`, `vendors` | **101** | It shows that the $840 rush reprint of the size S tee (invoice 501) is still `open` past its 2026-08-28 due date and that Bulldog Print Co needs 5 days to deliver, so the agent can explain when the tee could realistically be available. |
| `get_rent_info(lease_id)` | `leases`, `payments`, `cash_accounts`, `desk` | **102** | It checks the landlord's email against the lease ($2,400 due 2026-09-02), confirms no rent has been paid yet, and shows the $3,400 checking balance, so the agent knows the rent is real and affordable before anyone approves payment. It also returns `days_until_due` (next due minus `desk.date_today`: 2), which the Facilities Agent uses to judge urgency. |
| `get_shop_date()` | `desk` | 101, 102, 103 | Gives every agent the shop's "today" (2026-08-31), so "overdue" and "due in 2 days" are judged against shop time, not the real clock. |
| `list_tickets(status)` | `tickets` | 101, 102, 103 | Lets the Boss see the whole work queue at once. |
| `get_ticket(ticket_id)` | `tickets` | 101, 102, 103 | Gives an agent the exact request: sku, size, qty, lease, or invoice link, and the notes. |
| `get_product_sizes(sku)` | `inventory`, `pricing` | **103** (also 101) | Shows that hoodie stock across all sizes is 32 (M 8, L 14), so Customer Service can suggest a mixed-size order instead of only saying "8 available". |
| `quote_price(sku, quantity, discount_pct)` | `pricing` | **103** | Works out the discounted unit price, margin, and the maximum discount before hitting the $22 cost, and flags quotes below cost. The quote is not revenue. |
| `list_vendors()` | `vendors` | **101** | Lists who can restock what and their lead times, so Inventory picks the right vendor (apparel reprint for tees). |
| `get_vendor_status(vendor_id)` | `vendors`, `invoices`, `desk` | **101** | Flags Bulldog Print Co as **restricted** because invoice 501 is unpaid, so no new tee order goes to them until it's paid. Any unpaid invoice restricts a vendor, overdue or not. |
| `list_open_invoices()` | `invoices`, `vendors`, `desk` | **101** | Shows every unpaid bill and how many days overdue it is (501: 3 days), for Accounting's payment priorities. |
| `get_cash_position()` | `cash_accounts`, `invoices`, `leases`, `payments`, `desk` | **101**, **102** | Puts $3,400 cash against rent ($2,400) and invoice 501 ($840), leaving $160, so Accounting can plan payments without going negative. It counts cash on hand only. |
| `request_payment_approval(kind, ref_id, requested_by, reason)` | reads `invoices`/`vendors` or `leases`, plus `cash_accounts` and `desk`; writes `output/payment_approvals.json` (not the DB) | **101**, **102** | Files a **pending** request for a human. It moves no money. The amount comes from the DB, and the request is refused if the item isn't payable, is a duplicate, or would overdraw checking. |
| `request_purchase_approval(sku, size, quantity, vendor_id, requested_by, reason)` | reads `inventory`, `pricing`, `vendors`, `invoices`, `desk`; writes `output/payment_approvals.json` (not the DB) | **101**, **103** | Inventory files a **pending** restock purchase for a human (cost = `unit_cost` × qty from the DB). Places no order and moves no money. Refused for a vendor with any unpaid invoice, so no reprint order can go to Bulldog Print Co while invoice 501 is open. |
| `list_payment_approvals(status)` | `output/payment_approvals.json` | **101**, **102**, **103** | Shows whether a human has approved, rejected, or not yet looked at each payment and purchase request. |
| `set_ticket_status(ticket_id, status)` | writes `tickets` | 101, 102, 103 | **Backend only** (no agent has it). The FastAPI backend sets `resolved` only when the Boss's decision says so (see the resolution rule below). |
| `execute_payment(approval_id)` | writes `payments`, `cash_accounts`, `invoices`; reads `leases`, `vendors` | **101**, **102** | Pays **only** a request a human approved. It re-checks the amount and payability against the DB and refuses if checking would go negative. In one transaction it adds a `payments` row, lowers the balance, and marks a paid invoice `paid`. |

## FastAPI backend (Problem 7)

`backend/main.py` connects the React dashboard (Problem 8) to the agent team. Start it from the `backend/` folder:

```bash
../.venv/bin/uvicorn main:app --reload --port 8010
```

- **Base URL:** `http://127.0.0.1:8010`. Interactive docs are at `/docs`.
- **CORS:** allows the React dev servers on `localhost:5173` (Vite) and `localhost:3000`. Override with `CORS_ORIGINS`.
- **Reuse:** the backend opens **one** MCP connection, shared with the agents. Every shop fact it returns (tickets, cash, approvals) comes through the MCP tools; there's no SQL in the backend. Runs use `run_team` and the five Problem 5 agents. Approvals use the shared `mcp_server/approvals.py`.

| Method | URL | What it does |
|---|---|---|
| GET | `/api/health` | Server status, model (`gpt-6-luna`), number of MCP tools (24), and the agent run in progress (if any). |
| GET | `/api/tickets` | All three tickets (101, 102, 103) with `status` (`open` / `resolved`, from the `tickets` table via `list_tickets`), plus `running`, `last_run_id`, `last_run_status`, `pending_approvals`, the Boss's `resolution` and `remaining_actions`, and a plain-language `next_step` (e.g. "Waiting for a human decision on PAY-…", "Still needed: …"). |
| GET | `/api/tickets/{ticket_id}` | One ticket in the same shape. 404 if it doesn't exist. |
| POST | `/api/tickets/{ticket_id}/run` | Starts the agent team (Boss first) on that ticket in the background and returns **202** with a `run_id` right away. 409 if another run is in progress or the ticket is already resolved. 503 if the agents can't be built (e.g. no `PORTKEY_API_KEY`). |
| GET | `/api/runs` | Agent runs since the last reset, newest first: `kind` (`ticket`, `payment_execution`, `other`), `status` (`running`, `finished`, `failed`), the final output (Boss decision or Accounting report), and any error. |
| GET | `/api/runs/{run_id}` | One run. Poll this until `status` isn't `running`. |
| GET | `/api/events` | Recent agent activity from `output/audit_trail.json`, oldest first. Each event has `agent`, `category` (`run`, `message`, `delegation`, `tool`, `approval`, `payment`, `error`), a plain-language `text` (what the agent said, who delegated what to whom, which tool was called with what arguments and what it returned), `tool`, and the raw `details`. Filters: `run_id`, `ticket_id`, `since` (ISO timestamp, for polling), `limit` (default 200), `include_tool_results`. |
| GET | `/api/approvals` | Payment and purchase requests the agents prepared, newest first. Filters: `status`, `ticket_id`. |
| POST | `/api/approvals/{approval_id}/approve` | **Human approval.** Body: `{"approver": "Your name", "confirm_approval_id": "<same ID>"}`. A **payment** is marked approved, then the Accounting Agent executes it (response includes `execution_run_id`). A **purchase approval only records the human decision**: no order is placed, and cash and inventory don't change. The response's `effects` says exactly what happened (`decision_recorded`, `payment_execution_started`, `order_placed: false`, `cash_changed_now: false`, `inventory_changed: false`), and the message tells the person to order from the vendor themselves. 400 if the confirmation doesn't match, 409 if not pending, if the vendor is restricted, or if another run is in progress. |
| POST | `/api/approvals/{approval_id}/reject` | **Human rejection**, same body. Nothing is paid or ordered. |
| POST | `/api/approvals/{approval_id}/execute` | Retries execution of an already-approved payment (e.g. if the Accounting run failed), same body. Starts an Accounting run. |
| GET / POST | `/api/tickets/{id}/updates`, `/api/tickets/{id}/customer-response`, `/api/tickets/{id}/pricing-decision`, `/api/tickets/{id}/fulfilment`, `/api/approvals/{id}/place-order`, `/api/approvals/{id}/cancel`, `/api/inventory/receipts` | **Manager actions** (Problem 9): read a ticket's events and status, or record a human/manager event. Each needs a name and a typed confirmation, and none moves cash. See *Manager actions* below. `/approve` and `/reject` also take an optional `reason`. |
| GET | `/api/cash` | Current checking balance from the `cash_accounts` table (via `get_cash_position`): `{account, balance, as_of, shop_date}`. |
| POST | `/api/reset` | Body `{"confirm": "RESET"}`. Restores `data/campus_customs_new.db` from the untouched `data/campus_customs.db` (checked by hash). Moves `output/payment_approvals.json` to `output/approvals_archive/`, and clears the run list. The audit trail is **kept** and gets a `database_reset` record. 409 while a run is in progress. |

**Ticket run flow:**
1. `POST /run` starts the Boss on the ticket. The Boss is told to prepare, never execute, anything that needs money or an order. **Accounting** files every payment request, and the Boss reports Accounting's approval IDs (enforced by the Boss output check). **Inventory** files restock purchase requests. The backend files nothing itself.
2. **Only the Boss resolves a ticket.** A finished run is not a resolved ticket. The backend sets `resolved` only if:
   - the Boss's latest decision has `resolution: "resolved"` (nothing else needed), **or**
   - the Boss named payments in `resolves_when_payments_executed` with **no** other `remaining_actions`, and all of those payments have been executed.

   In every other case the ticket stays **`open`**:
   - **Paying doesn't resolve it by itself.** Paying invoice 501 doesn't resolve Ticket 101 while the tee is out of stock and a reply is owed.
   - **A purchase approval never resolves it.** It only records a decision.
   - **A rejection keeps it open.** `next_step` asks for a re-run.

   Run the team again on an open ticket to let the Boss reassess with the new facts. Status is re-checked after every run, approval, and rejection.
3. The backend runs **one agent run at a time**.

## React dashboard (Problem 8)

`frontend/` is a React + Vite + TypeScript app (Lecture 7 structure, plain CSS, no UI library) that uses **only** the Problem 7 API routes. It doesn't change any business rule or safety mechanism: the backend still decides ticket status and resolution, and still enforces every approval and payment rule. See `frontend/README.md`.

**Run:** backend from `backend/` with `../.venv/bin/uvicorn main:app --reload --port 8010`, then frontend from `frontend/` with `npm run dev`, which serves the dashboard on http://localhost:5180 (`--strictPort`: it stops instead of switching ports if 5180 is busy) and proxies `/api` to port 8010. If 8010 is busy, use another backend port and `BACKEND_PORT=<port> npm run dev`. No secrets are in the frontend.

| Column | Component(s) | API routes used |
|---|---|---|
| Left: tickets | `TicketList`, `TicketCard` | `GET /api/tickets` |
| Center: next action | `NextAction` (top of the selected ticket) | `GET /api/tickets` (`next_step`, `remaining_actions`, `resolution`, `pending_approvals`), `POST /api/tickets/{id}/run` |
| Center: Boss decision | `TicketDetail` | `GET /api/runs` (run `output`) |
| Center: agent activity | `AgentActivity`, `AgentRoster`, `ActivityItem` / `ToolGroup` | `GET /api/events?ticket_id=…&since=…`, `GET /api/runs` |
| Right: cash | `CashCard` | `GET /api/cash` |
| Right: approvals | `ApprovalQueue`, `ApprovalCard` | `GET /api/approvals`, `POST /api/approvals/{id}/approve`, `/reject`, `/execute` |
| Header | `Header` | `GET /api/health`, `POST /api/reset` |

**Agent characters:** each agent is a friendly cartoon character with a face, drawn as an inline SVG in `components/AgentCharacter.tsx`. Each one's look reflects its role:

| Agent | Colour | Look |
|---|---|---|
| Boss | purple | Suit and tie |
| Inventory | teal | Beanie, carrying a carton |
| Accounting | blue | Round glasses, pencil behind the ear |
| Facilities | coral | Hard hat and overalls |
| Customer Service | pink | Headset with a mic |

There's also "You" (the manager) for human approval steps.

- **Where they appear:** the team row, the agent details roster, every timeline row, the collaboration flow, and approval cards ("Prepared by Accounting").
- **Expressions follow real state** from `/api/events`:

  | Expression | When |
  |---|---|
  | Calm | Ready, or not needed this run |
  | Focused | Working, with a typing bubble |
  | Glancing aside | Waiting on a teammate (it delegated and is waiting for the report) |
  | Smiling | Done |
  | Worried | Stopped, refused, or an error |
  | Celebrating | The ticket became resolved |

**Collaboration flow** (`components/CollaborationFlow.tsx`, built by `buildFlow` in `activity.ts`): a left-to-right diagram of who delegated to whom in the selected run, built **only from real events**:

| Event | Becomes |
|---|---|
| `delegation_started` | A numbered arrow |
| `delegation_result` | "✓ reported" (green) |
| `delegation_refused` / `delegation_failed` | Red dashed |
| `approval_requested` | A final arrow to "You" |
| Payment-execution runs | Start with You → Accounting |

Arrows still waiting for a report are animated dashed lines while the team works. Clicking an agent filters the timeline to it; clicking an arrow scrolls the timeline to that delegation. The flow sits between the team row and the timeline.

**Animation:**
- **Gentle, state-driven motion:** blinking, a bob while working, a sway while waiting, a pop when done, a small shake on a refusal, and animated dashed arrows for delegations in progress.
- **Celebration:** a short confetti burst over the Next action banner, celebrating characters, and a glow on the ticket card. It appears **only** when a ticket the backend had as `open` changes to `resolved` while the page is open, never on page load and never for a merely finished run.
- **Reduced motion:** with `prefers-reduced-motion: reduce`, every character, flow, and celebration animation is off and confetti is hidden.

**Manager-focused features:**
- **Next action:** a banner at the top of the selected ticket.
  - Shows the backend's `next_step` as the headline, with `remaining_actions` as a checklist.
  - Has "Review N approvals" and "Run team again" buttons.
  - Its tone shows whether the ticket needs your decision, still has work to do, is running, is resolved, or failed. A finished run is never shown as resolved unless the backend says so.
- **Agent activity:**
  - **Roster:** one card per agent showing what it's doing now (live while running) or its final summary, with tool and delegation counts. Expand a card for its tools, findings, recommendations, and escalations, or to show only that agent's activity.
  - **Timeline:** messages, delegations, approval requests, payments, and errors stay visible. Each agent's consecutive MCP tool calls collapse into one line of tool names that expands to show arguments and results, and "Expand all tool details" opens them all.
  - **Live updates:** while a run is active the panel refreshes every 1.5 s, fetching only new events, and auto-scrolls. Separate tabs show each team run and payment execution.
- **Payment approvals:**
  - Each payment card shows the **actual** checking balance from `/api/cash` and the **projected** balance after that payment. When several are pending, it also shows the balance after all of them. Projections are labelled as estimates.
  - The actual balance is re-read from the backend on every refresh, and the cash card flags the change after a payment is executed.
  - **Purchase requests** are in their own section marked "no cash impact", and the card says approving only records the decision.

**Checked without running tickets or making payments:**
- `npm run build` (TypeScript type check plus production build) and ESLint pass.
- **Characters and animation** were tested with Playwright, driving the installed Chrome, against the real FastAPI app running on **scratch copies** of the data, with `run_team` replaced by a scripted, slow stand-in (no model calls). That made it possible to click Run, watch mid-run states, and see a ticket become resolved. 22/22 UI checks passed:
  - five characters shown
  - working and waiting moods during a run
  - animated arrows during a run
  - a flow matching the real delegation events, including a refusal and a final arrow to "You"
  - clicking an arrow or a node jumps to or filters the timeline
  - the approval card shows the preparing agent's character
  - confetti only when the ticket genuinely becomes resolved, ending by itself, and not repeated on reload
  - no console errors
  - reduced motion turns every animation off and hides confetti
- Headless Chrome screenshots, in light and dark mode, against a backend running on **scratch copies** of the data, seeded with a sample run for Ticket 102 and pending requests.
- The real database, approvals, and audit trail were unchanged.

## Manager actions (Problem 9)

Some steps of a ticket can't be done by any agent: sending a reply and getting the customer's answer, signing off a discount, ordering from a vendor, receiving goods, and handing an order over. **Manager actions** let a person record these steps. Agents can **read** them, but no agent can create or change them.

**What stays the same:** the payment approval flow, the rule that only the Boss resolves a ticket, the audit trail, and every existing safety gate. The shop date stays fixed at 2026-08-31, and no customer revenue is ever recorded.

**Storage:** `output/manager_events.json`, append-only and lock-protected, handled by `mcp_server/manager_events.py`. Each event records:
- **who:** `recorded_by` and `recorded_at`
- **whether it's simulated:** `simulated: true|false`
- **what it's based on:** `basis`, which is required
- **links:** `refs` (approval or invoice ID) and `ticket_id`

Simulated events stand in for real customer or vendor actions in this assignment. They're labelled **"Simulated"** on the dashboard and in the activity text, and they're never presented as real communications.

**Purchase statuses:** `pending → approved → ordered → received`. An approved purchase can become `cancelled` before it's ordered, and a pending one can be `rejected`. Payments are unchanged.

| Manager action (human-only MCP tool) | Route | What it records / changes | Protections |
|---|---|---|---|
| `record_customer_response` | `POST /api/tickets/{id}/customer-response` | The customer's choice: `accept`, `wait`, `alternative`, `partial`, `decline`, or `other`. Nothing is sent. | The ticket exists; a basis is required. |
| `record_pricing_decision` | `POST /api/tickets/{id}/pricing-decision` | A person approves or declines a discount. Price and margin are recalculated from `pricing`. | An approved price below unit cost is refused. No revenue is recorded. |
| `place_purchase_order` | `POST /api/approvals/{id}/place-order` | `approved → ordered`, with an expected arrival (shop date + vendor delivery days). No money moves. | Only approved purchases can be ordered, and not from a restricted vendor or twice. The **cash warning** and **possible-duplicate warning** must be acknowledged. |
| `cancel_purchase` | `POST /api/approvals/{id}/cancel` | `approved → cancelled`, with a reason. | Only before ordering. |
| `record_stock_receipt` | `POST /api/inventory/receipts` | `inventory.qty` goes up. The receipt is against an ordered purchase (which becomes `received`) or against an invoice. | No more than was ordered, and an order can't be received twice. **Against an invoice:** refused while a purchase for the same item and vendor is still pending, approved, or ordered, and only one receipt per invoice and item. No vendor invoice is created. |
| `record_fulfilment` | `POST /api/tickets/{id}/fulfilment` | `inventory.qty` goes down (the order is handed over). | Needs a recorded customer response that isn't `decline`. A different size needs the customer's recorded `alternative` choice. A price request needs a recorded pricing decision. The total can't exceed the ticket's quantity, and stock can't go negative. No revenue is recorded. |
| `get_ticket_updates` (read-only, for agents) | `GET /api/tickets/{id}/updates` | The ticket's events, purchase and payment status with warnings, quantity fulfilled and still to fulfil, and open steps (e.g. ordered but not received). | Read by Boss, Inventory, Accounting, and Customer Service. |

**Every route** needs `recorded_by` plus a typed confirmation (ticket ID, approval ID, or source ID) and is refused while an agent run is active. Each one is written to `audit_trail.json` as `manager_<kind>` with `via: "dashboard"`. The six write tools and `set_ticket_status` are in `MANAGER_TOOLS`, which is kept out of every agent's tool list (an assertion enforces this), so any agent attempt is `tool_blocked`.

**Cash warning:** a warning appears when a purchase's estimated cost is more than the checking balance minus what's already committed (payments not yet executed, plus purchases already ordered). It shows on purchase requests, on purchase cards, and on the Place order form, and ordering needs explicit acknowledgement. It's a projection: approving or ordering a purchase never moves money.

**Resolution:**
- A manager event **never** resolves a ticket by itself.
- After one, `next_step` says "manager event(s) recorded since the last run … run the team again".
- While a purchase is ordered but not received, `next_step` says "waiting for delivery".
- The Boss reads `get_ticket_updates` and decides. Its output check refuses `resolved` while a recorded purchase order is still waiting for delivery.

**Simulated events in the fictional shop:** Campus Customs is fictional. Its customers and vendors exist only in this assignment, so every customer or vendor event *has* to be recorded by a person and labelled `simulated`. The agents are told (in the Boss, Inventory, and Customer Service prompts, and in the `get_ticket_updates` note) that **a labelled simulated event is a valid business event within this shop**. They must still say which events were simulated, and never describe them as real-world communications.
- The agents also judge an order by `quantity_fulfilled`, not by current stock, which is 0 after a handover.
- Side questions that don't block the ticket's own request go in `risks`, not in remaining actions. Example: what invoice 501's reprint contains.

**What "Resolved" means (all tickets):** every action the shop can take **now** is done, every required human decision has been made, no vendor invoice tied to the ticket is unpaid, and the customer's reply is **drafted** (Customer Service's draft is its deliverable; a person sends it). Future deliveries, customer answers, and pickups are **follow-ups** (`next_steps` / `risks`), not blockers, and they aren't invented.

| Ticket | Resolved when |
|---|---|
| 102 Rent | The notice matches the lease, and rent is paid (human-approved, executed). No reply is needed. |
| 101 Tee | Size S is out of stock, but the **ticket's linked invoice 501** ("Rush reprint CC-TEE-WHITE S") is the restock, and it's **paid**. No duplicate purchase is open. The reply is drafted. The reprint's quantity and delivery date aren't recorded, so they stay follow-ups. |
| 103 Hoodies | A person has recorded the pricing decision, the restock purchase is decided (rejected, or ordered **with its vendor bill paid**), and the reply is drafted. Fulfilment isn't required. If the bill can't be paid (e.g. $264 vs $160), the ticket stays **open** with the cash shortfall as its remaining action. |

**Boss resolution check (deterministic, `backend/agents.py`):** `resolved` is accepted only if, in the same run, the Boss read `get_ticket_updates` for the ticket and:
1. no approval for it is pending, no payment is approved but unpaid, and no purchase is approved but neither ordered nor cancelled
2. no vendor invoice tied to it (its linked invoice, or the bill from its order) is unpaid; the message names any shortfall against checking
3. **customer order:** any shortfall is covered by stock, by the paid linked invoice for that exact item, or by an ordered or received purchase
4. **price request:** a pricing decision is recorded
5. **customer tickets:** Customer Service drafted a reply in this run (or the order is already fulfilled, with the customer's response recorded)

Otherwise the output goes back to the Boss with the missing items. Fulfilment and customer responses are no longer required.

**Linked invoice = restock:** `get_ticket_updates` reports `linked_invoice` (from `tickets.invoice_id`) and whether it names the requested SKU and size. `request_purchase_approval` **refuses** a new purchase for a ticket whose own linked invoice already covers that item, so no quantity or delivery is assumed. Purchases without a ticket link still get the warn-only "possible duplicate" check.

**Human rejections are respected:** a person can give a **reason** when approving or rejecting: the dashboard's reason box, or the `reason` field on `/approve` and `/reject`. It's stored on the request (`rejection_reason` / `approval_reason`) and in the audit trail. `get_ticket_updates` lists `rejected_purchases` with who, when, and why.
- `request_purchase_approval` **refuses** to recreate a purchase a person rejected (same ticket, item, and size, at any quantity), quoting the rejection, unless a relevant circumstance changed: **cash now covers the cost**, or a **customer response was recorded after the rejection**. A pricing decision doesn't count as a change.
- The Boss, Inventory, and the run instructions treat a rejected purchase as a completed human decision.

**Purchases become bills:** `place_purchase_order` creates an **open vendor invoice**: cost = `unit_cost` × quantity from the approved request, due on the expected delivery date. No cash moves. The vendor is restricted until the bill is paid through the normal Accounting → human approval → `execute_payment` flow. Receiving stock creates no second bill. Older purchases ordered before this change have no bill.

**Cash consistency:** commitments are counted once: open invoices, plus unexecuted rent or other payment requests, plus any older ordered purchase without a bill. `get_cash_position` marks rent that's already paid for its current due date as `already_paid` and leaves it out of obligations. The lease's `next_due` is deliberately not moved.

**Reset:** archives `manager_events.json` along with the approvals, because recorded receipts no longer match the restored database.

**Ticket 101 and invoice 501:** a purchase like `BUY-76936C1B` (tee size S from Bulldog Print Co) gets a **possible-duplicate warning**, because paid invoice 501 is "Rush reprint CC-TEE-WHITE S". A receipt against invoice 501 is refused until that purchase is cancelled. Whether invoice 501 really covers the tee is **the manager's decision**: the system doesn't assume it.

**Ticket 103 and cash:** `BUY-9688DD9C` ($264) shows a cash warning against $160 available ($104 short). Ordering it needs explicit acknowledgement. Whether the club accepts 8 now, other sizes, or a wait is **recorded by the manager**: the system doesn't assume it.

## Problem 9 results (actual records)

Generated from `output/audit_trail.json`, `output/payment_approvals.json`, `output/manager_events.json`, and `data/campus_customs_new.db`. Nothing was rerun, approved, or changed to produce them.

| Ticket | Final status | Resolved by | Outcome |
|---|---|---|---|
| 101 Bulldog tee | resolved (2026-10-15 01:30 UTC) | `run-a86189ca4702` (Boss) | Invoice 501 ($840) paid with human approval. The customer response, restock order, receipt, and fulfilment were recorded as **simulated** manager events. The possible duplicate (`BUY-76936C1B` vs invoice 501) is kept as a follow-up risk. |
| 102 Rent due | resolved (2026-10-14 21:29 UTC) | `run-c73c4c25b533` (Accounting payment run) | Rent ($2,400) verified against the lease and paid after human approval. The ticket was resolved by the "payment executed and nothing else needed" rule. |
| 103 Bulk hoodie discount | resolved (2026-10-15 02:20 UTC) | `run-710a7503bb7f` (Boss) | 10% discount ($52.20 each) approved by a person (a manager decision, not simulated). The $264 restock was rejected (`BUY-9688DD9C`), then a repeat request (`BUY-FF090480`) was approved and cancelled for insufficient cash. The reply is drafted. No cash moved. |

**Cash:** 3,400.00 after the reset → −2,400.00 (rent, 102) → −840.00 (invoice 501, 101) → **160.00**, which matches `cash_accounts` checking (160.00): reconciled. No purchase, quote, or manager event moved cash.

**Audit trail:** 780 records, no exact duplicates. There are 14 real agent runs since the reset, each with `run_started` and `run_finished`. All human approvals, rejections, cancellations, and manager events are present, and earlier records are preserved. Note: `run-190bd8b1be01` reproduced `run-0dcc910c122d`'s token usage in 5.5 s, most likely because Portkey served the responses from its cache. Both are kept exactly as logged.

**Deliverables:**
- `output/desk_tickets.html`: Expected (unchanged) vs Actual for each ticket, plus the Cash tab
- `output/resolved_tickets.json`: per-ticket status, outcome, agent contributions, human approvals, manager events (with the simulated flag), and runs, plus the cash ledger
- `output/resolved_board.html`: standalone page with embedded screenshots of the React dashboard showing each resolved ticket

Each ticket in all three files separates **completed financial transactions** (rows in `payments`, the only cash movements) from **non-cash records** (rejected or cancelled purchases, the price quote), **simulated** manager events, and **fulfilment** (101: 1/1 via a simulated event; 102: nothing to fulfil; 103: 0/20, 8 on hand and the 12-unit restock not on order, so delivery is a follow-up).

## Audit trail

`output/audit_trail.json` is one JSON array. Every record is appended under a file lock, so earlier runs are always kept. Each record has a timestamp, `run_id`, `event`, `agent`, delegation `depth`, and `path` (the chain of agents above it). Events:

- **Runs:** `run_started`, `run_finished`, `run_failed` (with team usage and limits)
- **Agents:** `agent_started` (model, prompt, limits), `agent_finished` (structured output, usage), `agent_failed`
- **Delegation:** `delegation_started`, `delegation_result`, `delegation_refused`, `delegation_failed`
- **MCP:** `tool_call`, `tool_result`, `tool_error`, `tool_blocked`
- **Decisions:** `decision` (the Boss's final `BossDecision`)
- **Approvals and payments:** `approval_requested`, `approval_request_refused`, `approval_granted` / `approval_rejected` (written by the dashboard or the human script), `payment_blocked`, `payment_executed`, `payment_refused`

- **Backend (Problem 7):** `ticket_status_changed`, `database_reset`

## Safety

**Real customers.** No agent has any tool that sends email, texts, or any other message. Customer Service only produces drafts (`sent` is fixed to `false` in the output type), and the Boss passes them on for a human to review. Tickets are never edited by any agent.

**Real money.** A payment needs three separate locks:
1. **Request.** Only Accounting can call `request_payment_approval` (and Inventory `request_purchase_approval`). That creates a *pending* request whose amount is read from the DB, and moves no money. The backend never files requests itself, and the Boss can only report IDs that Accounting filed.
2. **Human approval.** A person clicks Approve on the dashboard (`POST /api/approvals/{id}/approve`, which needs their name and the approval ID typed back), or runs `scripts/approve_payment.py <ID> --approver "Name"` in a terminal. No agent has a tool or route that can approve.
3. **Human authorization to execute.** Approving on the dashboard starts the Accounting Agent with that one ID authorized (the CLI equivalent is `--execute-approved <ID>`). The backend blocks `execute_payment` for any agent but Accounting, and for any ID not passed in. The MCP server then refuses anything not marked `approved` by a person, re-checks the amount against the DB, and won't let checking go below $0 (`UPDATE … WHERE balance >= amount`).

On top of that:
- A **purchase approval only records the human decision.** No order is placed, cash and inventory don't change, and it never resolves a ticket by itself. The person orders from the vendor outside this system. Approval is refused if the vendor has become restricted.
- Vendors with any unpaid invoice, overdue or not, are reported as restricted.
- Prices below cost are rejected.
- Cash plans count only cash on hand: there is no revenue field, and quotes are labelled "not revenue".

**Token and loop limits** (`backend/config.py`):

| Limit | Value |
|---|---|
| Model requests per agent run | 8 |
| Tool calls per agent run | 12 |
| Tokens per agent run | 60,000 |
| Model requests per team run (all agents) | 30 |
| Tokens per team run (all agents) | 200,000 |
| Output tokens per model request | 3,000 |
| Delegation depth | 2 (Boss → specialist → specialist) |
| Delegations per team run | 10 |
| Delegating back into the current chain | not allowed |

When a limit is hit, the agent stops. The delegating agent receives an error and is told to decide with what it has, and the stop is recorded in the audit trail.

## Tests (Problems 5–9)

| Test | What it proves | Result |
|---|---|---|
| `tests/test_mcp_server.py` | All 24 tools over real stdio MCP on **scratch copies** of the DB and approvals file, including every payment guard: unknown, pending, or reused IDs refused; negative balance refused; duplicates refused. Also: an unpaid invoice that isn't overdue still restricts its vendor, paying it lifts the restriction, and `days_until_due` follows `desk.date_today` (2 days, or −3 when the date is moved past due) | 34/34 passed |
| `tests/test_backend_gates.py` | Without the model: per-agent tool blocking, the backend `execute_payment` gate, and delegation refusals (target, loop, depth, count), all recorded in the audit trail. Also: a restricted vendor can't be marked orderable, and the Facilities report is rejected unless its `days_until_due` matches MCP. Also: no agent can call `set_ticket_status`, and only Inventory can request purchases. Also: resolution rules (resolved can't have remaining actions; paying can't resolve a ticket with other work left), and the Boss can't list a payment without Accounting's real approval ID, can't make one up, and can't name a purchase as resolving a ticket. Also: every agent is blocked from all 7 human-only tools, and agents can read `get_ticket_updates`. Also, the resolution check under the new definition: without `get_ticket_updates`, without a draft, with an unpaid linked invoice, with no restock secured, with a pending, approved-unpaid, or approved-unordered item, with no pricing decision, or with an unpaid $264 bill vs $160 → refused; 101 with a paid linked invoice and a draft, 103 rejected restock + pricing + draft, rent, and an already-fulfilled order → accepted | 42/42 passed |
| `tests/check_agents_live.py` | Live `gpt-6-luna` run: Boss → all 4 specialists, plus Facilities → Accounting and Customer Service → Inventory at depth 2, using only products that aren't on any ticket (cap, mug). Tickets, DB hash, payments, and approvals unchanged. Summary saved in `output/agent_connection_test.json` | 12/12 passed |
| `tests/test_api.py` | FastAPI app + real MCP server on **scratch copies** with a scripted stand-in for the agents (no model calls). Covers every route: 202 run and status flow, 409 guards, a finished run with remaining work stays open (103), rent approved → Accounting executes → cash 3,400 → 1,000 → 102 resolved because the Boss named that payment as the only thing left, **invoice 501 paid but Ticket 101 still open** (tee out of stock) until the Boss's re-run says resolved, purchase approval records only (no order, cash, or stock change, no resolution), rejection keeps a ticket open, no backend-filed requests, events, CORS for the React dev server, and reset restoring the original DB while keeping the audit trail | 65/65 passed (now including rejection reasons stored and shown, and every manager-action route: confirmations, 409 refusals, warnings, audit records, refusal during an active run) |
| `tests/test_manager_actions.py` | All manager-action MCP tools on **scratch copies**: overlap with invoice 501 (duplicate warning, receipt refused until the BUY is cancelled), duplicate orders, receipts, and fulfilment refused, cash warning acknowledgement, price below cost refused, fulfilment rules (customer response, size, pricing), cash never changes, every event labelled | 45/45 passed (now also: a re-request of a human-rejected purchase is refused with the reason quoted, a quantity change doesn't get around it, and it's allowed again after a newer customer response; a purchase for 101 refused because of linked invoice 501, ordering creates an open $264 bill and restricts the vendor, paying it refused at $160, paid rent not counted twice) |
| `tests/check_rules_live.py` | Live `gpt-6-luna` on a **scratch DB** with a test invoice that isn't due yet and a test lease due 2026-09-20. Inventory marks Elm City Gifts restricted and not orderable. Facilities reports `days_until_due` = 20 and writes its own urgency assessment ("Low", with reasoning). | 7/7 passed |
