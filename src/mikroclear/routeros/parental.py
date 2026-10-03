"""Read-only RouterOS inventory for managed parental-control devices."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any

from mikroclear.routeros.address_list import Key, select_address_rows


@dataclass(frozen=True)
class ParentalDevice:
    ip: str
    name: str = ""
    comment: str = ""
    mac: str = ""


def list_parental_devices(api: Any, list_name: str) -> list[ParentalDevice]:
    resource = api.path("/ip/firewall/address-list")
    rows = list(resource.select(".id", "list", "address", "comment").where(Key("list") == str(list_name)))
    devices = []
    for row in rows:
        if str(row.get("list", "")) != str(list_name):
            continue
        address = str(row.get("address", "")).strip()
        try:
            if ipaddress.ip_address(address).version != 4:
                continue
        except ValueError:
            continue
        comment = str(row.get("comment", "")).strip()
        devices.append(ParentalDevice(address, comment, comment))
    return devices


def get_parental_device(api: Any, ip: str, list_name: str) -> ParentalDevice | None:
    return next((item for item in list_parental_devices(api, list_name) if item.ip == str(ip)), None)


def is_parental_device(api: Any, ip: str, list_name: str) -> bool:
    return get_parental_device(api, ip, list_name) is not None


class RouterOSParentalInventory:
    """Lazy read-only adapter backed by the existing reconnecting client."""

    def __init__(self, get_router_client: Any, list_name: str) -> None:
        self.get_router_client = get_router_client
        self.list_name = str(list_name)

    def list_devices(self) -> list[ParentalDevice]:
        client = self.get_router_client()
        return client.run_with_reconnect(
            "parental device inventory",
            lambda: list_parental_devices(client.ensure_connected(), self.list_name),
        )

    def is_parental_device(self, ip: str) -> bool:
        return any(item.ip == str(ip) for item in self.list_devices())


__all__ = ["ParentalDevice", "RouterOSParentalInventory", "get_parental_device", "is_parental_device", "list_parental_devices"]
