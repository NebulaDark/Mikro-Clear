"""Suricata ignore-list loading and matching."""

import re
from typing import Any, Callable, Iterable


class IgnoreRules:
    def __init__(
        self,
        *,
        log: Callable[[str], None],
        debug_log: Callable[[str], None],
    ) -> None:
        self.log = log
        self.debug_log = debug_log
        self.entries: list[str] = []

    def load(self, path: str) -> None:
        self.entries = []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.partition("#")[0].strip()
                    if line:
                        self.entries.append(line)
        except FileNotFoundError:
            self.log(f"Ignore list {path} not found. Continuing.")

        self.debug_log(f"Ignore list loaded: {len(self.entries)} entries")

    def matches(self, event: dict[str, Any]) -> bool:
        return in_ignore_list(self.entries, event, log=self.log, debug_log=self.debug_log)


def in_ignore_list(
    entries: Iterable[str],
    event: dict[str, Any],
    *,
    log: Callable[[str], None] | None = None,
    debug_log: Callable[[str], None] | None = None,
) -> bool:
    alert = event.get("alert", {})
    if not isinstance(alert, dict):
        return False

    log = log or (lambda message: None)
    debug_log = debug_log or (lambda message: None)
    sid = str(alert.get("signature_id", ""))
    signature = str(alert.get("signature", ""))

    for entry in entries:
        try:
            if entry.isdigit() and sid.isdigit() and int(entry) == int(sid):
                debug_log(f"SID {sid} matched ignore entry {entry}")
                return True

            if entry.startswith("re:"):
                pattern = entry.partition("re:")[2].strip()
                if pattern and re.search(pattern, signature):
                    debug_log(f"Signature matched ignore regex: {pattern}")
                    return True
        except Exception as exc:
            log(f"Invalid ignore-list entry {entry!r}: {exc}")

    return False


__all__ = ["IgnoreRules", "in_ignore_list"]
