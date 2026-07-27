"""Validated persistent storage for the managed dynamic whitelist."""

import ipaddress
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any


RFC1918_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


class DynamicWhitelistError(RuntimeError):
    pass


def is_managed_private_ipv4(value: Any) -> bool:
    try:
        address = ipaddress.ip_address(str(value))
    except ValueError:
        return False
    return isinstance(address, ipaddress.IPv4Address) and any(
        address in network for network in RFC1918_NETWORKS
    )


class DynamicWhitelistStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._addresses = self._load()

    def snapshot(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._addresses))

    def contains(self, address: str) -> bool:
        return str(address) in self.snapshot()

    def add(self, address: str) -> bool:
        if not is_managed_private_ipv4(address):
            raise ValueError("managed whitelist accepts only exact RFC1918 IPv4")
        with self._lock:
            if address in self._addresses:
                return False
            updated = set(self._addresses)
            updated.add(address)
            self._persist(updated)
            self._addresses = updated
            return True

    def remove(self, address: str) -> bool:
        with self._lock:
            if address not in self._addresses:
                return False
            updated = set(self._addresses)
            updated.remove(address)
            self._persist(updated)
            self._addresses = updated
            return True

    def _load(self) -> set[str]:
        if not self.path.exists():
            return set()
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DynamicWhitelistError(
                f"cannot read managed whitelist: {type(exc).__name__}"
            ) from exc
        if not isinstance(document, dict) or set(document) != {"version", "addresses"}:
            raise DynamicWhitelistError("managed whitelist schema is invalid")
        if (
            type(document["version"]) is not int
            or document["version"] != 1
            or not isinstance(document["addresses"], list)
        ):
            raise DynamicWhitelistError("managed whitelist version or addresses is invalid")
        values = document["addresses"]
        if any(
            not isinstance(value, str) or not is_managed_private_ipv4(value)
            for value in values
        ):
            raise DynamicWhitelistError("managed whitelist contains an invalid address")
        if len(values) != len(set(values)):
            raise DynamicWhitelistError("managed whitelist contains duplicates")
        return set(values)

    def _persist(self, addresses: set[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=self.path.parent,
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    {"version": 1, "addresses": sorted(addresses)},
                    handle,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary.exists():
                temporary.unlink()


__all__ = [
    "DynamicWhitelistError",
    "DynamicWhitelistStore",
    "is_managed_private_ipv4",
]
