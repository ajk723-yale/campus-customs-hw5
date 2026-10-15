"""Run the Campus Customs team from the terminal.

  .venv/bin/python -m backend.cli "Review ticket 102 and recommend next steps"
  .venv/bin/python -m backend.cli "Check stock for CC-HAT-BLUE OS" --agent inventory
  .venv/bin/python -m backend.cli "Execute approved payment PAY-XXXX" --execute-approved PAY-XXXX

--execute-approved is the only way to let a run execute a payment, and the
payment must also be approved with scripts/approve_payment.py first.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import get_args

from backend.agents import run_team
from backend.models import AgentName


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task")
    parser.add_argument("--agent", default="boss", choices=get_args(AgentName))
    parser.add_argument("--execute-approved", nargs="*", default=[], metavar="APPROVAL_ID",
                        help="Approval IDs a human approved and now authorizes for execution in this run")
    args = parser.parse_args()
    run_id, output = asyncio.run(run_team(args.task, entry_agent=args.agent,
                                          human_approved_payment_ids=args.execute_approved))
    print(json.dumps({"run_id": run_id, "output": output.model_dump(mode="json")}, indent=2))


if __name__ == "__main__":
    main()
