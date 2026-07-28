"""Private JSONL audit logging for bot actions."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from mikroclear.telegram.formatting import sanitize_text


class BotAuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def record(
        self,
        action: str,
        outcome: str,
        chat_id: str,
        user_id: str,
        target: str,
        detail: str = "",
    ) -> None:
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": sanitize_text(action, 80),
            "outcome": sanitize_text(outcome, 40),
            "chat_id": sanitize_text(str(chat_id), 80),
            "user_id": sanitize_text(str(user_id), 80),
            "target": sanitize_text(str(target), 80),
            "detail": sanitize_text(str(detail), 240),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            os.fchmod(descriptor, 0o600)
            line = (json.dumps(row, sort_keys=True) + "\n").encode("utf-8")
            os.write(descriptor, line)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
