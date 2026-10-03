"""Safe operations limited to the configured YouTube policy group."""

from __future__ import annotations

from typing import Any

from mikroclear.pihole.models import PiholeClientRecord, PiholeGroup, payload_items


def list_groups(client: Any) -> list[PiholeGroup]:
    payload = client.request("GET", "/api/groups")
    return [PiholeGroup(item.get("id", item.get("group_id", "")), str(item.get("name", "")))
            for item in payload_items(payload, "groups", "data") if item.get("name")]


def find_group(client: Any, name: str) -> PiholeGroup | None:
    return next((group for group in list_groups(client) if group.name == str(name)), None)


def list_clients(client: Any) -> list[PiholeClientRecord]:
    payload = client.request("GET", "/api/clients")
    records = []
    for item in payload_items(payload, "clients", "data"):
        value = item.get("client", item.get("ip", item.get("name", "")))
        groups = item.get("groups", item.get("group_ids", ()))
        if isinstance(groups, (str, int)):
            groups = (groups,)
        records.append(PiholeClientRecord(item.get("id", value), str(value), tuple(groups or ())))
    return records


def find_client(client: Any, ip: str) -> PiholeClientRecord | None:
    return next((item for item in list_clients(client) if item.client == str(ip)), None)


def add_client(client: Any, ip: str) -> PiholeClientRecord:
    payload = client.request("POST", "/api/clients", json={"client": str(ip)})
    item = payload if isinstance(payload, dict) else {}
    return PiholeClientRecord(item.get("id", ip), str(item.get("client", ip)), tuple(item.get("groups", ())))


def set_group_membership(client: Any, record: PiholeClientRecord, group: PiholeGroup, enabled: bool) -> None:
    groups = set(record.groups)
    if enabled:
        groups.add(group.id)
    else:
        groups.discard(group.id)
    client.request("PUT", f"/api/clients/{record.id}", json={"groups": sorted(groups, key=str)})


__all__ = ["add_client", "find_client", "find_group", "list_clients", "list_groups", "set_group_membership"]
