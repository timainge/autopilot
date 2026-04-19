import json
import os
import uuid
from pathlib import Path

from autopilot.domain.clock import now

_RUN_ID_ENV = "AUTOPILOT_RUN_ID"
_PROJECT_ROOT_ENV = "AUTOPILOT_PROJECT_ROOT"


def _resolve_run_id(fields: dict) -> str:
    rid = fields.pop("run_id", None) or os.environ.get(_RUN_ID_ENV)
    if rid:
        return rid
    return uuid.uuid4().hex[:12]


def _resolve_log_path(run_id: str) -> Path:
    # Project root may be supplied via env; otherwise fall back to cwd/.dev/logs.
    root_env = os.environ.get(_PROJECT_ROOT_ENV)
    root = Path(root_env) if root_env else Path.cwd()
    return root / ".dev" / "logs" / f"run-{run_id}.jsonl"


def emit(event: str, **fields: object) -> None:
    """Append one JSON line to .dev/logs/run-{run_id}.jsonl."""
    run_id = _resolve_run_id(fields)
    path = _resolve_log_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts_utc": now().isoformat(),
        "run_id": run_id,
        "event": event,
        **fields,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
