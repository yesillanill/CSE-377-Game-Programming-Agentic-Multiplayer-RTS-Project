"""JSONL logs for the agent (tool calls per request) and for security events. Secrets are never logged:
the session token is replaced by a short hash and snapshots are not written."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(os.environ.get("RTS_AI_LOG_DIR", Path(__file__).resolve().parents[1] / "logs"))


def session_hash(session_id: str) -> str:
    return "sess-" + hashlib.sha256((session_id or "").encode("utf-8")).hexdigest()[:10]


class AgentLogger:
    def __init__(self, log_dir: Path = LOG_DIR, enabled: bool = True):
        self.log_dir = Path(log_dir)
        self.enabled = enabled
        self._lock = threading.Lock()

    def _write(self, name: str, record: dict) -> None:
        if not self.enabled:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"{name}_{datetime.now().strftime('%Y%m%d')}.jsonl"
        line = json.dumps(record, ensure_ascii=False)
        with self._lock, path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def log_request(self, record: dict) -> None:
        self._write("agent", record)

    def log_security(self, record: dict) -> None:
        self._write("security", record)

    def log_plan_decision(self, record: dict) -> None:
        self._write("plan_decisions", record)
