"""Private runtime state file helpers."""

from dataclasses import dataclass
import os
from pathlib import Path


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


__all__ = ["StateStoreConfig", "ensure_private_runtime_file"]
