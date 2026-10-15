"""Human approval for Campus Customs payments and purchases. Agents cannot run this.

Agents can only *request* a payment (request_payment_approval) or a purchase
(request_purchase_approval). A person uses this script, or the dashboard's
Approve / Reject buttons, to approve or reject the request. It must be run in an interactive
terminal, and the person must type the approval ID to confirm.

  .venv/bin/python scripts/approve_payment.py --list
  .venv/bin/python scripts/approve_payment.py PAY-1234ABCD --approver "Your Name"
  .venv/bin/python scripts/approve_payment.py PAY-1234ABCD --approver "Your Name" --reject

After approving, let the Accounting Agent execute it by passing the ID to the
team run explicitly:

  .venv/bin/python -m backend.cli "Execute approved payment PAY-1234ABCD" --execute-approved PAY-1234ABCD
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mcp_server"))

from backend import audit  # noqa: E402
from approvals import APPROVALS_PATH, read_approvals, record_human_decision  # noqa: E402


def show(r: dict) -> str:
    what = (f"purchase {r['quantity']} x {r['sku']} {r['size']}" if r["kind"] == "purchase"
            else f"{r['kind']} #{r['ref_id']}")
    due = f"  due {r['due_date']}" if r.get("due_date") else ""
    return (f"{r['approval_id']}  [{r['status']}]  {what}  ${r['amount']:,.2f} to {r['payee']}{due}"
            f"\n    reason: {r['reason']}  (requested by {r['requested_by']} at {r['requested_at']})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("approval_id", nargs="?")
    parser.add_argument("--approver", help="Your name, recorded as approved_by")
    parser.add_argument("--reject", action="store_true", help="Reject instead of approve")
    parser.add_argument("--list", action="store_true", help="List all requests")
    args = parser.parse_args()

    if args.list or not args.approval_id:
        records = read_approvals()
        print(f"{APPROVALS_PATH}: {len(records)} request(s)")
        for r in records:
            print(show(r))
        return 0

    if not sys.stdin.isatty():
        print("Refused: approvals must be made by a person in an interactive terminal.")
        return 2
    if not args.approver or not args.approver.strip():
        print("Refused: --approver with your name is required.")
        return 2

    record = next((r for r in read_approvals() if r["approval_id"] == args.approval_id), None)
    if record is None:
        print(f"No request {args.approval_id}.")
        return 1
    if record["status"] != "pending":
        print(f"Request is {record['status']!r}; only pending requests can be approved or rejected.")
        return 1
    print(show(record))
    action = "REJECT" if args.reject else "APPROVE"
    typed = input(f"\nType the approval ID to {action} this request: ").strip()
    if typed != record["approval_id"]:
        print("Not confirmed. Nothing changed.")
        return 1
    try:
        record = record_human_decision(args.approval_id, args.approver, approve=not args.reject)
    except (LookupError, ValueError) as exc:
        print(f"Refused: {exc}")
        return 1

    event = "approval_rejected" if args.reject else "approval_granted"
    audit.record(event, run_id="human", agent=None, approval_id=record["approval_id"], by=args.approver.strip(),
                 kind=record["kind"], ref_id=record["ref_id"], amount=record["amount"])
    print(f"{record['approval_id']} is now {record['status']}. No money has moved yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
