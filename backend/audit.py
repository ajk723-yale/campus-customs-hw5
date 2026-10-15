"""Append-only audit trail at output/audit_trail.json.

The file is one JSON array. Each call to `record` locks the file, reads the
existing records, appends one, and writes the whole array back atomically, so
records from earlier runs are always kept.
"""

from __future__ import annotations

import fcntl
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from backend.config import AUDIT_PATH

# Long tool results are cut to this many characters so the trail stays readable.
MAX_DETAIL_CHARS = 4_000


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _trim(value: Any) -> Any:
    text = json.dumps(value, default=str)
    if len(text) <= MAX_DETAIL_CHARS:
        return value
    return {"truncated": True, "preview": text[:MAX_DETAIL_CHARS]}


def record(event: str, *, run_id: str, agent: str | None = None, depth: int | None = None,
           path: tuple[str, ...] | list[str] = (), **details: Any) -> dict:
    """Append one event to the audit trail and return it."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "run_id": run_id,
        "event": event,
        "agent": agent,
        "depth": depth,
        "path": list(path),
        **{k: _trim(_jsonable(v)) for k, v in details.items()},
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_PATH.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = json.loads(AUDIT_PATH.read_text()) if AUDIT_PATH.exists() and AUDIT_PATH.stat().st_size else []
        existing.append(entry)
        tmp = AUDIT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        tmp.replace(AUDIT_PATH)
    return entry
