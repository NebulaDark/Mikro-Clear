"""Runtime state persistence helpers."""

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any, Callable

import ujson

try:
    from librouteros.query import Key  # type: ignore
except Exception:  # pragma: no cover
    class Key:  # type: ignore
        def __init__(self, name: str) -> None:
            self.name = name

        def __eq__(self, other: Any) -> tuple[str, Any]:
            return (self.name, other)

from mikroclear.suricata.alert_logic import is_ip_in_whitelist


@dataclass(frozen=True)
class StateStoreConfig:
    save_lists_location: str = "/var/lib/mikroclear/savelists-tzsp0.json"
    save_lists_location_v6: str = "/var/lib/mikroclear/savelists-tzsp0_v6.json"
    uptime_bookmark: str = "/var/lib/mikroclear/uptime-tzsp0.bookmark"
    save_lists: tuple[str, ...] = ("Suricata",)
    block_list_name: str = "Suricata"
    timeout: str = "1d"
    whitelist_ips: tuple[str, ...] = ()


def ensure_private_runtime_file(path_text: str, initial: str = "") -> None:
    path = Path(path_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(initial)
    os.chmod(path, 0o600)


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


def save_lists(address_list: Any, *, config: StateStoreConfig, is_v6: bool = False, debug_log: Callable[[str], None]) -> None:
    _address = Key("address")
    _list = Key("list")
    _timeout = Key("timeout")
    _comment = Key("comment")
    curr_file = config.save_lists_location_v6 if is_v6 else config.save_lists_location
    tmp_file = curr_file + ".tmp"

    Path(curr_file).parent.mkdir(parents=True, exist_ok=True)
    os.chmod(Path(curr_file).parent, 0o700)
    descriptor = os.open(tmp_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        for save_list in config.save_lists:
            for row in address_list.select(_list, _address, _timeout, _comment).where(_list == save_list):
                handle.write(ujson.dumps(row) + "\n")
    os.chmod(tmp_file, 0o600)

    os.replace(tmp_file, curr_file)
    os.chmod(curr_file, 0o600)
    debug_log(f"Saved address-list state to {curr_file}")


def add_saved_lists(
    address_list: Any,
    *,
    config: StateStoreConfig,
    is_v6: bool = False,
    debug_log: Callable[[str], None],
) -> None:
    curr_file = config.save_lists_location_v6 if is_v6 else config.save_lists_location

    try:
        with open(curr_file, "r", encoding="utf-8") as handle:
            rows = [ujson.loads(line) for line in handle if line.strip()]
    except FileNotFoundError:
        debug_log(f"No saved list file: {curr_file}")
        return

    restored = 0
    skipped = 0

    for row in rows:
        address = row.get("address")
        if not address or is_ip_in_whitelist(str(address), config.whitelist_ips):
            skipped += 1
            continue

        try:
            address_list.add(
                list=row.get("list", config.block_list_name),
                address=address,
                comment=row.get("comment") or "",
                timeout=row.get("timeout") or config.timeout,
            )
            restored += 1
        except Exception as exc:
            if "already have such entry" in str(exc):
                continue
            raise

    debug_log(f"Restored {restored} saved addresses from {curr_file}, skipped={skipped}")


__all__ = [
    "StateStoreConfig",
    "add_saved_lists",
    "check_tik_uptime",
    "ensure_private_runtime_file",
    "parse_routeros_uptime",
    "save_lists",
]
