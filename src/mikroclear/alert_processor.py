"""Alert processing orchestration."""

from dataclasses import dataclass
from datetime import datetime as dt
from time import time
from typing import Any, Callable

try:
    from librouteros.query import Key  # type: ignore
except Exception:  # pragma: no cover
    class Key:  # type: ignore
        def __init__(self, name: str) -> None:
            self.name = name

        def __eq__(self, other: Any) -> tuple[str, Any]:
            return (self.name, other)

from mikroclear.routeros.address_list import add_to_address_list
from mikroclear.suricata.alert_logic import is_ip_in_whitelist
from mikroclear.suricata.events import should_process_event
from mikroclear.telegram.formatting import sanitize_text


@dataclass(frozen=True)
class AlertProcessorConfig:
    severities: tuple[str, ...]
    listen_interfaces: tuple[str, ...]
    whitelist_ips: tuple[str, ...]
    block_list_name: str
    timeout: str
    monitor_only: bool = False
    enable_ipv6: bool = False
    comment_time_format: str = "%-d %b %Y %H:%M:%S.%f"


def format_event_timestamp(value: Any, comment_time_format: str) -> str:
    try:
        return dt.strptime(str(value), "%Y-%m-%dT%H:%M:%S.%f%z").strftime(comment_time_format)
    except Exception:
        return dt.now().strftime(comment_time_format)


def update_existing_address(
    curr_list: Any,
    wanted_ip: str,
    comment: str,
    event: dict[str, Any],
    peer_ip: str,
    wanted_port: Any,
    *,
    config: AlertProcessorConfig,
    send_telegram: Callable[..., Any],
    log: Callable[[str], None],
) -> None:
    _address = Key("address")
    _id = Key(".id")
    _list = Key("list")

    rows = list(curr_list.select(_id, _list, _address).where(_address == wanted_ip, _list == config.block_list_name))
    for row in rows:
        curr_list.remove(row[".id"])

    add_to_address_list(curr_list, config.block_list_name, wanted_ip, comment, config.timeout)
    sid = event.get("alert", {}).get("signature_id", "N/A")
    log(f"UPDATED: {wanted_ip} - SID:{sid}")
    send_telegram(event=event, wanted_ip=wanted_ip, src_ip=peer_ip, wanted_port=wanted_port, action_type="UPDATED")


def process_single_alert(
    event: dict[str, Any],
    address_list: Any,
    address_list_v6: Any,
    *,
    config: AlertProcessorConfig,
    ignore_predicate: Callable[[dict[str, Any]], bool],
    send_telegram: Callable[..., Any],
    log: Callable[[str], None],
    debug_log: Callable[[str], None],
) -> None:
    alert = event["alert"]
    sid = str(alert.get("signature_id", "N/A"))
    filter_decision = should_process_event(
        event,
        severities=config.severities,
        listen_interfaces=config.listen_interfaces,
        ignore_predicate=lambda item: ignore_predicate(dict(item)),
        enable_ipv6=config.enable_ipv6,
    )
    if not filter_decision.should_process:
        if filter_decision.log_method == "log":
            log(filter_decision.message)
        else:
            debug_log(filter_decision.message)
        return

    src = str(event["src_ip"])
    dst = str(event["dest_ip"])
    is_v6 = ":" in src
    curr_list = address_list_v6 if config.enable_ipv6 and is_v6 and address_list_v6 is not None else address_list

    if is_ip_in_whitelist(src, config.whitelist_ips):
        if is_ip_in_whitelist(dst, config.whitelist_ips):
            debug_log(f"Skipping SID={sid}: src and dst are whitelisted")
            return
        wanted_ip = dst
        wanted_port = event.get("dest_port")
        peer_ip = src
    else:
        wanted_ip = src
        wanted_port = event.get("dest_port")
        peer_ip = dst

    if is_ip_in_whitelist(wanted_ip, config.whitelist_ips):
        log(f"Skipping target IP {wanted_ip}: whitelisted")
        return

    timestamp = format_event_timestamp(event.get("timestamp"), config.comment_time_format)
    signature = sanitize_text(alert.get("signature", ""), 180)
    gid = alert.get("gid", 1)
    severity = str(alert.get("severity", "N/A"))
    proto = event.get("proto", "")
    comment = f"[{gid}:{sid}] {signature} ::: Port: {wanted_port}/{proto} ::: timestamp: {timestamp}"

    if config.monitor_only:
        log(f"MONITOR_ONLY: would block {wanted_ip} - SID:{sid} - Severity:{severity}")
        send_telegram(event=event, wanted_ip=wanted_ip, src_ip=peer_ip, wanted_port=wanted_port, action_type="MONITOR")
        return

    try:
        debug_log(f"Adding to MikroTik list={config.block_list_name}, address={wanted_ip}, timeout={config.timeout}")
        add_to_address_list(curr_list, config.block_list_name, wanted_ip, comment, config.timeout)
        log(f"BLOCKED: {wanted_ip} - SID:{sid} - Severity:{severity}")
        send_telegram(event=event, wanted_ip=wanted_ip, src_ip=peer_ip, wanted_port=wanted_port, action_type="BLOCKED")
    except Exception as exc:
        if "already have such entry" in str(exc):
            update_existing_address(
                curr_list,
                wanted_ip,
                comment,
                event,
                peer_ip,
                wanted_port,
                config=config,
                send_telegram=send_telegram,
                log=log,
            )
            return
        log(f"MikroTik TrapError for {wanted_ip}: {exc}")
        raise


def process_alert_batch(
    alerts: list[dict[str, Any]] | None,
    *,
    client: Any,
    config: AlertProcessorConfig,
    validate_event: Callable[[Any], dict[str, Any] | None],
    process_single: Callable[[dict[str, Any], Any, Any], None],
    save_restore: Callable[[Any], None],
    last_save_time: int,
    save_interval: int,
    now: Callable[[], float] = time,
    log: Callable[[str], None],
    debug_log: Callable[[str], None],
) -> int:
    if not alerts:
        debug_log("No alerts to process")
        return last_save_time

    valid_events: list[dict[str, Any]] = []
    for raw in alerts:
        event = validate_event(raw)
        if event is not None:
            valid_events.append(event)

    if not valid_events:
        return last_save_time

    unique: dict[str, dict[str, Any]] = {}
    for event in valid_events:
        src = str(event["src_ip"])
        dst = str(event["dest_ip"])
        target_ip = dst if is_ip_in_whitelist(src, config.whitelist_ips) else src
        unique[target_ip] = event

    debug_log(f"Processing {len(unique)} unique target IPs from {len(valid_events)} valid alerts")

    def process_batch() -> None:
        address_list, address_list_v6, _resources = client.paths()
        for event in unique.values():
            process_single(event, address_list, address_list_v6)

    client.run_with_reconnect("processing alerts", process_batch)

    current_time = int(now())
    if current_time - last_save_time < save_interval:
        return last_save_time

    def save_restore_batch() -> None:
        save_restore(client)

    try:
        client.run_with_reconnect("saving/restoring lists", save_restore_batch)
    except Exception as exc:
        log(f"ERROR while saving/restoring lists after reconnect retry: {type(exc).__name__}: {exc}")

    return current_time


__all__ = [
    "AlertProcessorConfig",
    "format_event_timestamp",
    "process_alert_batch",
    "process_single_alert",
    "update_existing_address",
]
