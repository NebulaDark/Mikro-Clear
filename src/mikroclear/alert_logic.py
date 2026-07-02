"""Pure alert decision helpers extracted for tests before refactoring legacy.py."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from typing import Any, Iterable, Mapping, Optional


@dataclass(frozen=True)
class AlertDecision:
    wanted_ip: str
    peer_ip: str
    wanted_port: Any
    is_ipv6: bool


def is_valid_ip(ip_text: Any) -> bool:
    if not isinstance(ip_text, str) or not ip_text:
        return False
    try:
        ipaddress.ip_address(ip_text)
        return True
    except ValueError:
        return False


def is_ip_in_whitelist(ip_to_check: Any, whitelist: Iterable[str]) -> bool:
    if not isinstance(ip_to_check, str) or not ip_to_check:
        return False

    try:
        ip_obj = ipaddress.ip_address(ip_to_check)
    except ValueError:
        return False

    for item in whitelist:
        item = str(item).strip()
        if not item:
            continue
        if ip_to_check == item:
            return True
        if "/" in item:
            try:
                if ip_obj in ipaddress.ip_network(item, strict=False):
                    return True
            except ValueError:
                continue
        elif not any(ch not in "0123456789abcdefABCDEF:." for ch in item):
            if ip_to_check.startswith(item):
                return True

    return False


def legacy_decide_alert_target(
    event: Mapping[str, Any],
    whitelist: Iterable[str],
    *,
    enable_ipv6: bool = False,
) -> Optional[AlertDecision]:
    """Return the current legacy target choice without RouterOS side effects."""

    src = str(event["src_ip"])
    dst = str(event["dest_ip"])
    is_v6 = ":" in src

    if is_v6 and not enable_ipv6:
        return None

    if is_ip_in_whitelist(src, whitelist):
        if is_ip_in_whitelist(dst, whitelist):
            return None
        return AlertDecision(
            wanted_ip=dst,
            wanted_port=event.get("dest_port"),
            peer_ip=src,
            is_ipv6=is_v6,
        )

    wanted_ip = src
    if is_ip_in_whitelist(wanted_ip, whitelist):
        return None

    return AlertDecision(
        wanted_ip=wanted_ip,
        wanted_port=event.get("dest_port"),
        peer_ip=dst,
        is_ipv6=is_v6,
    )


def legacy_deduplicate_by_src_ip(events: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    unique: dict[str, Mapping[str, Any]] = {}
    for event in events:
        unique[str(event["src_ip"])] = event
    return list(unique.values())


def target_aware_deduplicate(
    events: Iterable[Mapping[str, Any]],
    whitelist: Iterable[str],
    *,
    enable_ipv6: bool = False,
) -> list[Mapping[str, Any]]:
    unique: dict[str, Mapping[str, Any]] = {}
    for event in events:
        decision = legacy_decide_alert_target(event, whitelist, enable_ipv6=enable_ipv6)
        if decision is None:
            continue
        unique[decision.wanted_ip] = event
    return list(unique.values())


def deduplicate_alerts_by_target(
    events: Iterable[Mapping[str, Any]],
    whitelist: Iterable[str],
    *,
    enable_ipv6: bool = False,
) -> list[Mapping[str, Any]]:
    return target_aware_deduplicate(events, whitelist, enable_ipv6=enable_ipv6)
