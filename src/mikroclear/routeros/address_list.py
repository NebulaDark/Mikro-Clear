"""RouterOS firewall address-list helpers."""

from typing import Any

try:
    from librouteros.query import Key  # type: ignore
except Exception:  # pragma: no cover
    class Key:  # type: ignore
        def __init__(self, name: str) -> None:
            self.name = name

        def __eq__(self, other: Any) -> tuple[str, Any]:
            return (self.name, other)


def select_address_rows(address_list: Any, list_name: str, address: str) -> list[dict[str, Any]]:
    _address = Key("address")
    _id = Key(".id")
    _list = Key("list")
    return list(address_list.select(_id, _list, _address).where(_address == address, _list == list_name))


def remove_from_address_list(address_list: Any, list_name: str, address: str) -> int:
    removed = 0
    for row in select_address_rows(address_list, list_name, address):
        address_list.remove(row[".id"])
        removed += 1
    return removed


def add_to_address_list(address_list: Any, list_name: str, address: str, comment: str, timeout: str) -> None:
    address_list.add(list=list_name, address=address, comment=comment, timeout=timeout)


def update_address_list_entry(address_list: Any, list_name: str, address: str, comment: str, timeout: str) -> None:
    remove_from_address_list(address_list, list_name, address)
    add_to_address_list(address_list, list_name, address, comment, timeout)


__all__ = [
    "add_to_address_list",
    "remove_from_address_list",
    "select_address_rows",
    "update_address_list_entry",
]
