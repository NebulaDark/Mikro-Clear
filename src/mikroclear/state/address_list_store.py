"""RouterOS address-list save/restore helpers."""

import os
from pathlib import Path
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

from mikroclear.state.files import StateStoreConfig
from mikroclear.suricata.alert_logic import is_ip_in_whitelist


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


__all__ = ["StateStoreConfig", "add_saved_lists", "save_lists"]
