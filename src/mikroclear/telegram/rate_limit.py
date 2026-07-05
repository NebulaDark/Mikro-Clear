"""Telegram rate-limit lock file helpers."""

import os
from typing import Callable

from mikroclear.state_store import ensure_private_runtime_file


class TelegramRateLimitLock:
    def __init__(self, path: str, *, now: Callable[[], float], debug_log: Callable[[str], None]) -> None:
        self.path = path
        self.now = now
        self.debug_log = debug_log

    def locked_until(self) -> int:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                return int(handle.read().strip() or "0")
        except Exception:
            return 0

    def set(self, seconds: int) -> None:
        try:
            until = int(self.now()) + max(1, int(seconds))
            ensure_private_runtime_file(self.path)
            with open(self.path, "w", encoding="utf-8") as handle:
                handle.write(str(until))
            os.chmod(self.path, 0o600)
        except Exception as exc:
            self.debug_log(f"Could not write Telegram lock file: {exc}")


__all__ = ["TelegramRateLimitLock"]
