"""Suricata eve.json watcher."""

from __future__ import annotations

import json
import os
from time import sleep as default_sleep
from typing import Any, Callable


class EveJsonTailer:
    def __init__(
        self,
        *,
        add_on_start: bool,
        shutdown_requested: Callable[[], bool],
        log: Callable[[str], None] | None = None,
        debug_log: Callable[[str], None] | None = None,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        self.add_on_start = add_on_start
        self.shutdown_requested = shutdown_requested
        self.log = log or (lambda message: None)
        self.debug_log = debug_log or (lambda message: None)
        self.sleep = sleep
        self.last_pos = 0
        self.last_inode: int | None = None

    def reset(self) -> None:
        self.last_pos = 0
        self.last_inode = None

    def seek_to_end(self, fpath: str) -> None:
        if self.add_on_start:
            self.reset()
            return

        while not self.shutdown_requested():
            try:
                stat = os.stat(fpath)
                self.last_pos = stat.st_size
                self.last_inode = stat.st_ino
                self.debug_log(f"Initial file position set to EOF: {self.last_pos}")
                return
            except FileNotFoundError:
                self.log(f"File {fpath} not found. Retrying in 10 seconds...")
                self.sleep(10)

    def read_json(self, fpath: str) -> list[dict[str, Any]]:
        try:
            stat = os.stat(fpath)
            if self.last_inode is not None and stat.st_ino != self.last_inode:
                self.debug_log("eve.json inode changed, resetting position")
                self.last_pos = 0
            if stat.st_size < self.last_pos:
                self.debug_log("eve.json truncated/rotated, resetting position")
                self.last_pos = 0
            self.last_inode = stat.st_ino
        except FileNotFoundError:
            self.log(f"File {fpath} not found")
            return []

        alerts: list[dict[str, Any]] = []
        error_lines = 0
        other_events = 0

        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(self.last_pos)
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except Exception as exc:
                        error_lines += 1
                        if error_lines <= 3:
                            self.debug_log(f"JSON parse error, skipping line: {str(exc)[:120]}")
                        continue
                    if data.get("event_type") == "alert":
                        alerts.append(data)
                    else:
                        other_events += 1
                self.last_pos = handle.tell()
        except Exception as exc:
            self.log(f"Error reading {fpath}: {type(exc).__name__}: {exc}")
            return []

        self.debug_log(
            f"Read summary: {len(alerts)} alerts, {other_events} other events, {error_lines} errors, pos={self.last_pos}"
        )
        return alerts


__all__ = ["EveJsonTailer"]
