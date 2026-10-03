"""Small, API-independent Pi-hole models."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PiholeGroup:
    id: int | str
    name: str


@dataclass(frozen=True)
class PiholeClientRecord:
    id: int | str
    client: str
    groups: tuple[int | str, ...] = ()


def payload_items(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


__all__ = ["PiholeClientRecord", "PiholeGroup", "payload_items"]
