"""Effective system and managed whitelist policy."""

from dataclasses import dataclass
from typing import Any

from mikroclear.state.dynamic_whitelist import DynamicWhitelistStore
from mikroclear.suricata.alert_logic import is_ip_in_whitelist


@dataclass(frozen=True)
class WhitelistPolicy:
    system_entries: tuple[str, ...]
    managed_store: DynamicWhitelistStore

    def snapshot(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (*self.system_entries, *self.managed_store.snapshot())
            )
        )

    def contains(self, address: Any) -> bool:
        return is_ip_in_whitelist(address, self.snapshot())


__all__ = ["WhitelistPolicy"]
