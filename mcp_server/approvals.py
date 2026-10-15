"""Payment and purchase approval records (output/payment_approvals.json).

Shared by the MCP server (agents create *pending* requests and Accounting
executes approved payments), the human approval script, and the FastAPI
backend (the dashboard's Approve / Reject buttons). Only `record_human_decision`
changes a request to approved or rejected, and no agent has a tool that calls it.

Statuses: pending -> approved -> executed (payments)
          pending -> approved              (purchases: the order is placed outside this system)
          pending -> rejected
"""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPROVALS_PATH = Path(os.getenv("CAMPUS_APPROVALS_PATH", ROOT / "output" / "payment_approvals.json"))

PAYMENT_KINDS = ("invoice", "rent")
PURCHASE_KIND = "purchase"


@contextmanager
def approvals_file():
    """Lock the approvals file, yield its records, and save them on exit."""
    APPROVALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = APPROVALS_PATH.with_suffix(".lock")
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        records = json.loads(APPROVALS_PATH.read_text()) if APPROVALS_PATH.exists() else []
        yield records
        tmp = APPROVALS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(records, indent=2))
        tmp.replace(APPROVALS_PATH)


def read_approvals() -> list[dict]:
    return json.loads(APPROVALS_PATH.read_text()) if APPROVALS_PATH.exists() else []


def record_human_decision(approval_id: str, approver: str, approve: bool, reason: str | None = None) -> dict:
    """Mark a pending request approved or rejected by a named person.

    Raises ValueError if the request doesn't exist, isn't pending, or no
    approver name is given. Returns the updated record.
    """
    approver = (approver or "").strip()
    if not approver:
        raise ValueError("An approver name is required.")
    with approvals_file() as records:
        record = next((r for r in records if r["approval_id"] == approval_id), None)
        if record is None:
            raise LookupError(f"No approval request {approval_id!r}.")
        if record["status"] != "pending":
            raise ValueError(f"Request {approval_id} is {record['status']!r}; only pending requests can be decided.")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        reason = (reason or "").strip() or None
        if approve:
            record.update(status="approved", approved_by=approver, approved_at=now, approval_reason=reason)
        else:
            record.update(status="rejected", rejected_by=approver, rejected_at=now, rejection_reason=reason)
        return dict(record)
