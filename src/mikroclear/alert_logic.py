"""Deprecated compatibility shim for Suricata alert logic helpers."""

from mikroclear.suricata.alert_logic import (
    AlertDecision,
    deduplicate_alerts_by_target,
    is_ip_in_whitelist,
    is_valid_ip,
    legacy_decide_alert_target,
    legacy_deduplicate_by_src_ip,
    target_aware_deduplicate,
)

__all__ = [
    "AlertDecision",
    "deduplicate_alerts_by_target",
    "is_ip_in_whitelist",
    "is_valid_ip",
    "legacy_decide_alert_target",
    "legacy_deduplicate_by_src_ip",
    "target_aware_deduplicate",
]
