"""Router uptime bookmark helpers."""

import os
import re
from typing import Any, Callable

from mikroclear.state.files import StateStoreConfig, ensure_private_runtime_file


def parse_routeros_uptime(uptime: str) -> int:
    units = {"w": 7 * 24 * 3600, "d": 24 * 3600, "h": 3600, "m": 60, "s": 1}
    total = 0
    for num, unit in re.findall(r"(\d+)([wdhms])", uptime):
        total += int(num) * units[unit]
    return total


def check_tik_uptime(
    resources: Any,
    *,
    config: StateStoreConfig,
    debug_log: Callable[[str], None],
) -> bool:
    uptime = "0s"
    for row in resources:
        uptime = row.get("uptime", "0s")
        break

    total_seconds = parse_routeros_uptime(str(uptime))
    if total_seconds < 900:
        total_seconds = 900

    try:
        with open(config.uptime_bookmark, "r", encoding="utf-8") as handle:
            bookmark = int(handle.read().strip() or "0")
    except Exception:
        bookmark = 0

    ensure_private_runtime_file(config.uptime_bookmark, "0")
    with open(config.uptime_bookmark, "w", encoding="utf-8") as handle:
        handle.write(str(total_seconds))
    os.chmod(config.uptime_bookmark, 0o600)

    rebooted = total_seconds < bookmark
    debug_log(f"Router uptime={total_seconds}s previous={bookmark}s rebooted={rebooted}")
    return rebooted


__all__ = ["StateStoreConfig", "check_tik_uptime", "parse_routeros_uptime"]
