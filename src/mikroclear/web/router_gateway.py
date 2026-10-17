"""Narrow RouterOS adapter used by the Web control plane."""

from __future__ import annotations

import ipaddress
from threading import RLock
from time import sleep, time
from typing import Any, Callable

from mikroclear.routeros.address_list import remove_from_address_list
from mikroclear.routeros.client import RouterOSClient
from mikroclear.routeros.mangle import list_managed_mangle_rules, set_mangle_rule_disabled


class RouterWebGateway:
    def __init__(self, settings: Any, *, log: Callable[[str], None] | None = None) -> None:
        self.settings = settings
        self.log = log or (lambda _message: None)
        self._lock = RLock()
        self._client = RouterOSClient(
            settings,
            log=self.log,
            send_system_notification=lambda _message, _kind: False,
            sleep=sleep,
            time=time,
        )

    def close(self) -> None:
        with self._lock:
            self._client.close()

    def _api(self) -> Any:
        return self._client.lifecycle.ensure_connected()

    def status(self) -> dict[str, Any]:
        with self._lock:
            def operation() -> dict[str, Any]:
                row = next(iter(self._api().path("/system/resource")), {})
                return {
                    "connected": True,
                    "version": row.get("version", ""),
                    "uptime": row.get("uptime", ""),
                    "cpu_load": row.get("cpu-load", 0),
                    "free_memory": row.get("free-memory", 0),
                    "total_memory": row.get("total-memory", 0),
                    "board_name": row.get("board-name", ""),
                    "architecture_name": row.get("architecture-name", ""),
                }
            return self._client.run_with_reconnect("web status", operation)

    def block_entries(self, *, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            def operation() -> list[dict[str, Any]]:
                resource = self._api().path("/ip/firewall/address-list")
                rows: list[dict[str, Any]] = []
                for row in resource:
                    if str(row.get("list", "")) != self.settings.block_list_name:
                        continue
                    rows.append({
                        "id": str(row.get(".id", "")),
                        "list": str(row.get("list", "")),
                        "address": str(row.get("address", "")),
                        "comment": str(row.get("comment", "")),
                        "timeout": str(row.get("timeout", "")),
                        "dynamic": str(row.get("dynamic", "")).lower() in {"yes", "true", "1"},
                    })
                    if len(rows) >= max(1, min(int(limit), 2000)):
                        break
                return rows
            return self._client.run_with_reconnect("web block-list read", operation)

    def managed_mangle(self) -> list[dict[str, Any]]:
        if not self.settings.mangle_control_enable:
            return []
        with self._lock:
            def operation() -> list[dict[str, Any]]:
                rules = list_managed_mangle_rules(self._api(), self.settings)
                return [
                    {
                        "id": rule.rule_id,
                        "name": rule.name,
                        "comment": rule.comment,
                        "chain": rule.chain,
                        "action": rule.action,
                        "disabled": rule.disabled,
                        "packets": rule.packets,
                        "bytes": rule.bytes,
                    }
                    for rule in rules
                ]
            return self._client.run_with_reconnect("web mangle read", operation)

    def set_mangle_disabled(self, rule_id: str, disabled: bool) -> None:
        if self.settings.monitor_only:
            raise PermissionError("Mikro-Clear is in monitor-only mode")
        if not self.settings.mangle_control_enable:
            raise PermissionError("Mangle control is disabled")
        with self._lock:
            self._client.lifecycle.heartbeat(False)
            set_mangle_rule_disabled(self._api(), str(rule_id), bool(disabled), self.settings)

    def unblock(self, address: str) -> int:
        if self.settings.monitor_only:
            raise PermissionError("Mikro-Clear is in monitor-only mode")
        normalized = str(ipaddress.ip_address(str(address).strip()))
        with self._lock:
            self._client.lifecycle.heartbeat(False)
            resource = self._api().path("/ip/firewall/address-list")
            return int(remove_from_address_list(resource, self.settings.block_list_name, normalized))


__all__ = ["RouterWebGateway"]
