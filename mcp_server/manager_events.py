"""Manager-recorded events (output/manager_events.json).

Things a person records about the business that the agents can't do or see
for themselves: a customer's response, a discount decision, a purchase order
placed with a vendor, a cancelled purchase, stock received, an order fulfilled.

- Only people create events: the MCP tools that write here are human-only
  (no agent has them), and the backend calls them from dashboard routes that
  require a name and a typed confirmation.
- Agents can read events through get_ticket_updates.
- Every event says whether it is simulated (for this assignment there is no
  real customer or vendor) and what it is based on, so it is never presented
  as a real communication.
- The file is append-only: events are never edited or deleted.
"""

from __future__ import annotations

import fcntl
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS_PATH = Path(os.getenv("CAMPUS_MANAGER_EVENTS_PATH", ROOT / "output" / "manager_events.json"))

KINDS = ("customer_response", "pricing_decision", "purchase_order", "purchase_cancelled", "stock_receipt", "fulfilment")


def read_events(ticket_id: int | None = None) -> list[dict]:
    events = json.loads(EVENTS_PATH.read_text()) if EVENTS_PATH.exists() and EVENTS_PATH.stat().st_size else []
    return [e for e in events if ticket_id is None or e.get("ticket_id") == ticket_id]


def append_event(kind: str, *, ticket_id: int | None, recorded_by: str, shop_date: str, simulated: bool,
                 basis: str, details: dict, refs: dict | None = None) -> dict:
    """Append one event under a file lock and return it."""
    if kind not in KINDS:
        raise ValueError(f"Unknown event kind {kind!r}.")
    event = {
        "event_id": "EVT-" + uuid.uuid4().hex[:8].upper(),
        "kind": kind,
        "ticket_id": ticket_id,
        "recorded_by": recorded_by,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "shop_date": shop_date,
        "simulated": simulated,
        "basis": basis,
        "details": details,
        "refs": refs or {},
        "source": "manager",
    }
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EVENTS_PATH.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        events = json.loads(EVENTS_PATH.read_text()) if EVENTS_PATH.exists() and EVENTS_PATH.stat().st_size else []
        events.append(event)
        tmp = EVENTS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(events, indent=2))
        tmp.replace(EVENTS_PATH)
    return event
