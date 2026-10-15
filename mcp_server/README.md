# Campus Customs MCP Server

A [FastMCP](https://gofastmcp.com) server that is the Campus Customs agents' **only** source of shop facts and their only way to change shop data. It has 24 tools (17 core + 7 for manager actions, see below): 13 lookups, two tools to *request* a payment or a purchase, one tool to *execute* a payment a human approved, and one backend-only tool that sets a ticket's status.

## Data

- **Shop database:** `../data/campus_customs_new.db` (SQLite), the working copy of the original `campus_customs.db`.
  - **Lookups** open it in SQLite read-only mode (`mode=ro`), so they can't change anything.
  - **`execute_payment`** writes only for a human-approved payment. **`set_ticket_status`** writes `tickets.status`; only the FastAPI backend calls it, and no agent has it.
- **Payment and purchase approvals:** `../output/payment_approvals.json`, managed by `approvals.py`. These are requests and their human decisions, kept outside the shop database. Agents can create *pending* requests. Only a person can approve or reject one: on the dashboard (`POST /api/approvals/{id}/approve` or `/reject`) or with `../scripts/approve_payment.py`.
- **"Today":** the shop date comes from the `desk` table (2026-08-31), not the real clock.
- **No invented data:** tools return only what's in the database. A missing row returns `"found": false` (or `"created"/"executed": false`) with an error message instead of a guess.

## Tools

| Tool | Reads | Writes | Returns |
|---|---|---|---|
| `get_shop_date()` | `desk` | – | `date_today`, `notes` |
| `list_tickets(status=None)` | `tickets` | – | All tickets, or only those with that status |
| `get_ticket(ticket_id)` | `tickets` | – | One ticket: type, requester, sku/size/qty, lease_id, invoice_id, status, notes |
| `get_product_info(sku, size)` | `inventory`, `pricing` | – | `qty`, `location`, `unit_cost`, `list_price`; if not found, `sizes_for_sku` |
| `get_product_sizes(sku)` | `inventory`, `pricing` | – | Every size with qty, `total_qty`, `unit_cost`, `list_price` |
| `quote_price(sku, quantity, discount_pct=0)` | `pricing` | – | `unit_price`, `margin_per_unit`, `quote_total`, `max_discount_pct_at_cost`, `allowed` (false if below cost). It's a proposal, not revenue. |
| `get_invoice_info(invoice_id)` | `invoices`, `vendors` | – | Amount, due date, status, description, vendor name/specialty, `lead_days` |
| `list_open_invoices()` | `invoices`, `vendors`, `desk` | – | Open invoices with `days_overdue`, plus `total_open` |
| `list_vendors()` | `vendors` | – | id, name, specialty, `lead_days` |
| `get_vendor_status(vendor_id)` | `vendors`, `invoices`, `desk` | – | Vendor, open invoices (with `days_overdue` for information), `restricted`, `restriction_reason` |
| `get_rent_info(lease_id)` | `leases`, `payments`, `cash_accounts`, `desk` | – | Rent, `next_due`, `shop_date`, `days_until_due`, rent payments, checking account |
| `get_cash_position()` | `cash_accounts`, `invoices`, `leases`, `payments`, `desk` | – | Balances, open invoices, upcoming rent, recent payments, `checking_after_all_obligations` (cash on hand only) |
| `request_payment_approval(kind, ref_id, requested_by, reason, ticket_id=None)` | `invoices`/`vendors` or `leases`, `cash_accounts`, `desk` | approvals file | A **pending** request (`approval_id`, amount from the DB). No money moves. |
| `request_purchase_approval(sku, size, quantity, vendor_id, requested_by, reason, ticket_id=None)` | `inventory`, `pricing`, `vendors`, `invoices`, `desk` | approvals file | A **pending** purchase (`BUY-…`), with cost = `unit_cost` × quantity from the DB. Refused for a restricted vendor (any unpaid invoice). No order is placed and no money moves. |
| `list_payment_approvals(status=None)` | approvals file | – | Payment and purchase requests and their status: `pending`, `approved`, `rejected`, or `executed` (payments only) |
| `set_ticket_status(ticket_id, status)` | – | `tickets` | `open` or `resolved`. **Backend only** (not in any agent's tool list); the backend sets `resolved` only when the Boss's decision says the ticket is fully handled. |
| `execute_payment(approval_id)` | approvals file, `invoices`/`leases` | `payments`, `cash_accounts`, `invoices`, approvals file | `payment_id`, amount, `balance_after`, or a refusal |

Lookup tools carry the MCP `readOnlyHint` annotation.

### Shop rules built into the tools

- **Purchases:** `request_purchase_approval` refuses vendors with any unpaid invoice. Approving a purchase **only records the human decision**: it places no order (the person orders from the vendor outside this system), changes no cash or inventory, and never resolves a ticket by itself.
- **Vendor restriction:** `get_vendor_status` marks a vendor `restricted` whenever it has **any** unpaid (`open`) invoice, whether or not it is overdue. The restriction lifts once every open invoice is paid. Example: Bulldog Print Co is restricted because invoice 501 ($840, due 2026-08-28) is unpaid.
- **Days until rent is due:** `get_rent_info` (and `get_cash_position`) return `days_until_due` = `next_due` − `desk.date_today`; a negative number means past due. The server applies no urgency threshold. The Facilities Agent judges urgency from this number.
- **Never below cost:** `quote_price` returns `allowed: false` when the discounted price is below `unit_cost`.
- **Cash on hand only:** `get_cash_position` counts only account balances. Quotes and expected orders are never added.
- **Rent payments:** `get_rent_info` counts a `payments` row as rent for a lease when `ref_id` is the lease ID and `kind` is `rent` or `lease`. `execute_payment` records rent with `kind = 'rent'`. A rent payment for a given due date can be made only once.

### How a payment happens

1. **Request.** An agent calls `request_payment_approval`. The server reads the amount, payee, and due date from the DB. It refuses if the item isn't payable (e.g. invoice not `open`), if a pending or approved request already exists, or if paying would make checking negative.
2. **Human decision.** A person approves or rejects on the dashboard, giving their name and typing the approval ID back, or runs `scripts/approve_payment.py <ID> --approver "Name"` in an interactive terminal and types the ID to confirm. On the dashboard, approving a payment then starts the Accounting Agent with only that ID authorized.
3. **Execute.** `execute_payment(approval_id)` refuses unless the request is `approved` with a human `approved_by`. It then checks the amount and due date against the DB again, and in **one transaction**:
   - lowers checking with `UPDATE … WHERE balance >= amount`, so the balance can't go negative
   - inserts a `payments` row (`approved_by` = the person)
   - marks a paid invoice `paid`

   The request then becomes `executed` and can't be used again.

The agent backend adds its own gate on top: only the Accounting Agent may call `execute_payment`, and only for IDs the person passed into that run (see `backend/mcp_client.py`).

## Setup and run

From the `hw5` folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python mcp_server/server.py          # stdio (for MCP clients and the agents)
.venv/bin/python mcp_server/server.py --http   # HTTP at http://127.0.0.1:8002/mcp
```

- **Codex:** `.codex/config.toml` launches the server over stdio as `campus-customs`.
- **The agents:** `backend/mcp_client.py` launches the server the same way.
- **Tests:** set `CAMPUS_DB_PATH` and `CAMPUS_APPROVALS_PATH` to point the server at scratch copies (see `tests/test_mcp_server.py`).

## Manager actions (Problem 9)

These seven tools record what a person did: things agents can't do (`manager_events.py`, stored in `../output/manager_events.json`). The six write tools are **human-only**, called by the backend's dashboard routes. No agent has them.

| Tool | Effect |
|---|---|
| `get_ticket_updates(ticket_id)` | Read-only. A ticket's manager events, purchase and payment status with cash and duplicate warnings, quantity fulfilled, and open steps. Agents read this. |
| `record_customer_response(ticket_id, choice, summary, channel, recorded_by, simulated, basis)` | Event only. Nothing is sent to anyone. |
| `record_pricing_decision(ticket_id, sku, size, quantity, discount_pct, decision, recorded_by, note, simulated, basis)` | Event only. The price is recalculated from `pricing`, and a price below cost is refused. |
| `place_purchase_order(approval_id, recorded_by, vendor_reference, acknowledge_cash_warning, acknowledge_duplicate_warning, simulated, basis)` | `approved → ordered`, with an expected arrival. The warnings must be acknowledged. No money moves. |
| `cancel_purchase(approval_id, reason, recorded_by)` | `approved → cancelled`, only before ordering. |
| `record_stock_receipt(sku, size, quantity, source_kind, source_id, recorded_by, simulated, basis, ticket_id=None)` | `inventory.qty` goes up. Against an ordered purchase: no more than ordered, then `received`. Against an invoice: refused while a purchase for the same item and vendor is active, and only once per invoice and item. |
| `record_fulfilment(ticket_id, sku, size, quantity, recorded_by, simulated, basis)` | `inventory.qty` goes down. Needs a recorded customer response; a different size needs `alternative`; a price request needs a pricing decision. Can't exceed the ticket quantity or the stock on hand. |

`request_purchase_approval` now also returns `cash_warning` and `duplicate_warnings` (information only). It refuses a new request while a purchase for the same item and vendor is pending, approved, **or ordered**.

None of these tools changes cash, records revenue, creates vendor invoices, or moves the shop date.
