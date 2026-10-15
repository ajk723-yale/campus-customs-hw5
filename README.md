# Campus Customs: a multi-agent operations desk (Homework 5)

Campus Customs is a fictional campus merch shop. A team of five AI agents (Boss, Inventory, Accounting, Facilities, Customer Service) works through the shop's support tickets using an MCP server as their only source of shop data. A FastAPI backend runs the team, and a React dashboard shows what each agent is doing. **A person approves every payment and purchase**; no agent can move money on its own.

- All agents use **`gpt-6-luna` through Portkey** (`https://api.portkey.ai/v1`).
- The shop's "today" is fixed at **2026-08-31** (from the `desk` table).
- Full system description and safety rules: [`output/harness.md`](output/harness.md).

## What's in this repository

| Path | What it is |
|---|---|
| `data/campus_customs.db` | The **original** shop database. Never modified. |
| `data/campus_customs_new.db` | The **working copy** the agents read and write. Committed in its final Problem 9 state (all three tickets resolved). |
| `mcp_server/` | FastMCP server (`server.py`, 24 tools), approval records (`approvals.py`), manager events (`manager_events.py`). See [`mcp_server/README.md`](mcp_server/README.md). |
| `backend/` | FastAPI app (`main.py`), the agent team (`agents.py`), settings (`config.py`), and the five agent prompts in `backend/prompts/` (`boss.md`, `inventory.md`, `accounting.md`, `facilities.md`, `customer_service.md`). |
| `frontend/` | React + Vite + TypeScript dashboard. See [`frontend/README.md`](frontend/README.md). |
| `scripts/approve_payment.py` | Command-line alternative to the dashboard's Approve / Reject buttons. |
| `tests/` | Offline tests on scratch copies (`test_*.py`) and live model checks (`check_*_live.py`). |
| `output/` | Deliverables and records (see below). |
| `AI_prompts.md` | Every prompt used for Problems 1–11. |
| `.mcp.json` | MCP client config for this server (relative paths). |
| `.env.example` | Template for `.env`. Placeholders only. |

**Deliverables in `output/`:**

- `harness.md`: system design and safety rules
- `design.md`: dashboard design
- `desk_tickets.html`: Expected vs. Actual per ticket, the Cash tab, and the Reflection (standalone; open it by double-clicking)
- `resolved_tickets.json`: per-ticket outcome, agents, delegations, tools, and human approvals, plus the cash ledger
- `resolved_board.html`: standalone page with dashboard screenshots of the three resolved tickets
- `audit_trail.json`, `payment_approvals.json`, `manager_events.json`: the records of the Problem 9 run
- `github_url.txt`: this repository's URL

## Redactions in this public version

Two record files contained absolute paths from the author's computer (a local username and folder names). In the published copies, **only those path strings** were replaced; every other byte of each record is unchanged:

| File | Fields changed | Replacement |
|---|---|---|
| `output/audit_trail.json` | `database` and `restored_from` in the one `database_reset` record (record 46 of 780) | the project folder → `<project-root>` |
| `output/mcp_smoke.json` | `codex_session.cwd` and `codex_session.log_file` | the project folder → `<project-root>`, the home folder → `<home>` |

No records were added, removed, or reordered, and no ticket, approval, payment, or cash data was changed. The unredacted originals are kept only on the author's machine. Note that the reset route writes the absolute database paths into `database_reset` records, so a reset on your machine will record your own paths.

## Requirements

- macOS or Linux (the record files use `fcntl` file locks)
- Python 3 (developed and tested on 3.14)
- Node.js and npm (developed and tested on Node 24)
- A Portkey API key with access to `gpt-6-luna`. It is only needed to run the agents: the backend starts and the dashboard shows tickets, cash, and approvals without it.

## 1. Install

```bash
git clone https://github.com/ajk723-yale/campus-customs-hw5.git
cd campus-customs-hw5

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cd frontend && npm install && cd ..
```

The virtual environment **must** be at `.venv/` in the project folder: the backend starts the MCP server with `.venv/bin/python`.

## 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and replace `your-portkey-api-key-here` with your own key. `.env` is in `.gitignore`; never commit it. The backend finds `.env` by searching upward from the folder you start it in, so keep it in the project root.

## 3. Start from a clean working database (optional)

This repository ships `data/campus_customs_new.db` in its **final** state, after the Problem 9 run. Skip this step to browse those results on the dashboard. To start over, either use the dashboard's Reset (step 7, recommended because it also archives the old approvals), or copy the original over the working copy before starting the backend:

```bash
cp data/campus_customs.db data/campus_customs_new.db
mkdir -p output/approvals_archive
[ -f output/payment_approvals.json ] && mv output/payment_approvals.json output/approvals_archive/
[ -f output/manager_events.json ] && mv output/manager_events.json output/approvals_archive/
```

Approvals and manager events must go with the old database, because they refer to its payments and stock. `audit_trail.json` is append-only and is kept.

## 4. The MCP server

The backend **starts the MCP server automatically** (over stdio) for every agent run, so you don't need to start it separately to use the dashboard.

To start it on its own, or to connect another MCP client:

```bash
.venv/bin/python mcp_server/server.py
```

It talks MCP over stdin/stdout, so it waits silently for a client. Stop it with Ctrl+C. MCP clients that read `.mcp.json` (for example Claude Code) pick it up automatically when started in this folder. For Codex, add the same command to its `mcp_servers` config.

## 5. Start the FastAPI backend

This project uses **port 8010** for the backend and **port 5180** for the dashboard, so it doesn't collide with other local apps on the common ports 8000 and 5173. First check that both ports are free:

```bash
lsof -nP -iTCP:8010 -iTCP:5180 -sTCP:LISTEN
```

If that prints anything, another program is using the port: pick other ports and use them consistently in steps 5–7.

```bash
cd backend
../.venv/bin/uvicorn main:app --port 8010
```

Check that it's up: http://127.0.0.1:8010/api/health should return `"model": "gpt-6-luna"` and `"mcp_tools": 24`.

## 6. Start the React dashboard

In a second terminal:

```bash
cd frontend
npm run dev
```

Open **http://localhost:5180**. The page title is **"Campus Customs ops desk"**.

- `npm run dev` is set up (in `frontend/package.json` and `frontend/vite.config.ts`) to serve on **5180 only** (`--strictPort`: if 5180 is taken it stops with an error instead of switching ports) and to forward `/api` to the backend on **8010**.
- If you started the backend on another port, tell Vite: `BACKEND_PORT=<port> npm run dev`.
- Don't open http://localhost:5173: that's Vite's usual default and may be a different app on your machine.
- Check the dashboard is connected: http://localhost:5180/api/health should show the same `gpt-6-luna` / `24` response as step 5.

Vite forwards `/api` calls to the backend, so no keys reach the browser.

## 7. Reset the database, then run all three tickets

1. **Reset.** Use the Reset button in the dashboard header, or:

   ```bash
   curl -X POST http://127.0.0.1:8010/api/reset -H 'Content-Type: application/json' -d '{"confirm": "RESET"}'
   ```

   This restores `data/campus_customs_new.db` from `data/campus_customs.db` (checked by hash), archives `payment_approvals.json` and `manager_events.json` to `output/approvals_archive/`, and adds a `database_reset` record to the audit trail. Checking goes back to **$3,400.00** and tickets 101, 102, and 103 are `open`.
2. **Run a ticket.** Select it and click Run (or `POST /api/tickets/{id}/run`). Only one agent run happens at a time.
3. **Decide.** Payment and purchase requests appear on the right. Enter your name in "Approving as", type the approval ID back, and Approve or Reject. An approved payment is executed by the Accounting agent; the server refuses any payment that would overdraw checking.
4. **Record manager actions** (customer response, discount sign-off, order, receipt, fulfilment) from the ticket's Manager Actions panel. These are things no agent can do; mark them simulated when they stand in for a customer or vendor in this fictional shop.
5. **Run the ticket again** after new decisions or events. Only the Boss can resolve a ticket, and the backend checks that nothing the shop can do now is left.

## Tests

Offline tests use scratch copies of the database and record files and make no model calls (your real records are not touched):

```bash
.venv/bin/python tests/test_mcp_server.py
.venv/bin/python tests/test_manager_actions.py
.venv/bin/python tests/test_backend_gates.py
.venv/bin/python tests/test_api.py
```

`test_backend_gates.py` and `test_api.py` build the agent team, which needs `PORTKEY_API_KEY` to be set, but they never call the model. Without a `.env`, any placeholder works, e.g. `PORTKEY_API_KEY=placeholder .venv/bin/python tests/test_api.py`.

`tests/check_agents_live.py` and `tests/check_rules_live.py` call `gpt-6-luna` (they need `.env` and cost tokens).

## Safety

- No real money, customers, or vendors: payments only change the SQLite database, and simulated events are labelled as such.
- Agents can only *request* payments and purchases. Approving, rejecting, ordering, receiving, and fulfilment are human-only.
- Per-agent and per-team token, request, tool-call, and delegation limits stop runaway loops.
- Every tool call, delegation, and human decision is written to `output/audit_trail.json`.

Details: [`output/harness.md`](output/harness.md).
