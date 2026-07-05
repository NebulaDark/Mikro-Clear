"""Pure Suricata event validation and filtering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional

from mikroclear.suricata.alert_logic import is_valid_ip


@dataclass(frozen=True)
class EventFilterDecision:
    should_process: bool
    message: str = ""
    log_method: str = "debug"


def validate_event(event: Any) -> Optional[dict[str, Any]]:
    if not isinstance(event, dict):
        return None

    alert = event.get("alert")
    if not isinstance(alert, dict):
        return None

    if "signature_id" not in alert:
        return None

    src_ip = event.get("src_ip")
    dest_ip = event.get("dest_ip")
    if not is_valid_ip(src_ip) or not is_valid_ip(dest_ip):
        return None

    return event


def should_process_event(
    event: Mapping[str, Any],
    *,
    severities: Iterable[str],
    listen_interfaces: Iterable[str],
    ignore_predicate: Callable[[Mapping[str, Any]], bool],
    enable_ipv6: bool,
) -> EventFilterDecision:
    alert = event["alert"]
    sid = str(alert.get("signature_id", "N/A"))
    severity = str(alert.get("severity", ""))
    allowed_severities = tuple(str(item) for item in severities)

    if severity not in allowed_severities:
        return EventFilterDecision(False, f"Skipping SID={sid}: severity={severity}")

    in_iface = str(event.get("in_iface", ""))
    allowed_interfaces = tuple(str(item) for item in listen_interfaces)
    if allowed_interfaces and in_iface not in allowed_interfaces:
        return EventFilterDecision(
            False,
            f"Skipping SID={sid}: interface={in_iface}, allowed={allowed_interfaces}",
        )

    if ignore_predicate(event):
        return EventFilterDecision(False, f"Skipping alert SID={sid} - in ignore list", "log")

    src = str(event["src_ip"])
    if ":" in src and not enable_ipv6:
        return EventFilterDecision(False, f"Skipping IPv6 alert because IPv6 disabled: {src}")

    return EventFilterDecision(True)
