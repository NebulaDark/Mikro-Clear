#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mikro-Clear v3.1.0-STABLE
Suricata eve.json -> MikroTik RouterOS API-SSL -> address-list -> Telegram

Main v3.1 fixes:
- RouterOS API wrapper with hard reconnect;
- old SSL/API objects are never reused after reconnect;
- api.path() objects are created fresh for each operation batch;
- SSL BAD_LENGTH / record overflow / ConnectionClosed handled with reconnect;
- optional heartbeat before RouterOS operations;
- no hardcoded secrets; all configuration via environment file;
- safe eve.json tailing with log rotation handling;
- whitelist, ignore-list, Telegram flood-control, save/restore lists preserved.
"""

import html
import ipaddress
import json
import os
import re
import signal
import socket
import ssl
import sys
import traceback
from pathlib import Path
from datetime import datetime as dt
from time import sleep, time
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import ujson  # type: ignore
except Exception:  # pragma: no cover
    ujson = json  # type: ignore

import pyinotify  # type: ignore
import requests
import librouteros
from librouteros import connect
from librouteros.query import Key

try:
    from mikroclear.config import env_bool, env_csv, env_int, env_name_candidates, env_str
except Exception:  # pragma: no cover - production single-file fallback
    def env_name_candidates(name: str) -> Tuple[str, ...]:
        if name.startswith("MIKROCATA_"):
            return ("MIKROCLEAR_" + name.removeprefix("MIKROCATA_"), name)
        return (name,)

    def env_str(name: str, default: str = "") -> str:
        for candidate in env_name_candidates(name):
            value = os.getenv(candidate)
            if value is not None:
                return value.strip()
        return default.strip()

    def env_bool(name: str, default: bool = False) -> bool:
        for candidate in env_name_candidates(name):
            value = os.getenv(candidate)
            if value is not None:
                return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return default

    def env_int(name: str, default: int) -> int:
        for candidate in env_name_candidates(name):
            value = os.getenv(candidate)
            if value is None:
                continue
            if value.strip() == "":
                return default
            try:
                return int(value.strip())
            except ValueError:
                return default
        return default

    def env_csv(name: str, default: Iterable[str]) -> Tuple[str, ...]:
        value = None
        for candidate in env_name_candidates(name):
            value = os.getenv(candidate)
            if value is not None:
                break
        if value is None or value.strip() == "":
            return tuple(default)

        normalized = value.replace("\n", ",").replace(";", ",")
        return tuple(
            item.strip().strip('"').strip("'")
            for item in normalized.split(",")
            if item.strip().strip('"').strip("'")
        )

try:
    from mikroclear.security import mask_known_secret, sanitize_exception_text
except Exception:  # pragma: no cover - production single-file fallback
    def mask_telegram_bot_token(text: Any) -> str:
        return re.sub(r"/bot[0-9]+:[A-Za-z0-9_-]+/", "/bot***MASKED***/", str(text))

    def mask_known_secret(text: Any, secret: str | None, label: str = "SECRET") -> str:
        value = mask_telegram_bot_token(text)
        if secret:
            value = value.replace(secret, "***MASKED***")
        return value

    def sanitize_exception_text(exc: BaseException, *secrets: str) -> str:
        value = f"{type(exc).__name__}: {exc}"
        for secret in secrets:
            value = mask_known_secret(value, secret)
        return mask_telegram_bot_token(value)

try:
    from mikroclear.telegram_polling import TelegramPollingBackoff
except Exception:  # pragma: no cover - production single-file fallback
    class TelegramPollingBackoff:
        def __init__(
            self,
            base_seconds: int = 30,
            max_seconds: int = 300,
            log_every_seconds: int = 120,
        ) -> None:
            self.base_seconds = base_seconds
            self.max_seconds = max_seconds
            self.log_every_seconds = log_every_seconds
            self.failure_count = 0
            self.next_poll_at = 0.0
            self.last_logged_at = 0.0
            self.last_error_key = ""

        def should_poll(self, now: float) -> bool:
            return now >= self.next_poll_at

        def record_success(self, now: float) -> None:
            self.failure_count = 0
            self.next_poll_at = now
            self.last_logged_at = 0.0
            self.last_error_key = ""

        def record_failure(self, now: float, error_key: str) -> Tuple[bool, int]:
            delay = min(self.max_seconds, self.base_seconds * (2 ** self.failure_count))
            self.failure_count += 1
            self.next_poll_at = now + delay

            should_log = error_key != self.last_error_key or now - self.last_logged_at >= self.log_every_seconds
            if should_log:
                self.last_logged_at = now
                self.last_error_key = error_key

            return should_log, delay

try:
    from mikroclear.telegram_notify import (
        TelegramSendResult,
        format_alert_message,
        format_system_message,
        send_telegram_message,
    )
except Exception:  # pragma: no cover - production single-file fallback
    class TelegramSendResult:
        def __init__(
            self,
            ok: bool,
            status_code: int = 0,
            response_text: str = "",
            retry_after: int = 0,
        ) -> None:
            self.ok = ok
            self.status_code = status_code
            self.response_text = response_text
            self.retry_after = retry_after

    def format_alert_message(
        event: Dict[str, Any],
        wanted_ip: Any,
        peer_ip: Any,
        wanted_port: Any,
        action_type: str,
        peer_formatter: Any = None,
    ) -> str:
        alert = event.get("alert", {})
        if not isinstance(alert, dict):
            alert = {}

        timestamp = event.get("timestamp", "N/A")
        protocol = event.get("proto", "N/A")
        in_iface = event.get("in_iface", "N/A")

        try:
            event_time = dt.strptime(str(timestamp), "%Y-%m-%dT%H:%M:%S.%f%z")
            formatted_time = event_time.strftime("%d.%m.%Y %H:%M:%S")
        except Exception:
            formatted_time = "N/A"

        signature = sanitize_text(alert.get("signature", "N/A"), 150) or "N/A"
        format_peer = peer_formatter or (lambda ip_text: f"<code>{escape_html_safe(ip_text or 'N/A')}</code>")

        return f"""
<b>Mikro-Clear Alert - {escape_html_safe(action_type)}</b>

<b>Target IP:</b> <code>{escape_html_safe(wanted_ip or 'N/A')}</code>
<b>Action:</b> <code>{escape_html_safe(action_type)}</code>
<b>Severity:</b> <code>{escape_html_safe(alert.get('severity', 'N/A'))}</code>
<b>Time:</b> <code>{escape_html_safe(formatted_time)}</code>

<b>Network:</b>
- Source/peer: {format_peer(peer_ip)}
- Protocol: <code>{escape_html_safe(protocol)}</code>
- Port: <code>{escape_html_safe(wanted_port or 'N/A')}</code>
- Interface: <code>{escape_html_safe(in_iface)}</code>

<b>Alert:</b>
- SID: <code>{escape_html_safe(alert.get('signature_id', 'N/A'))}</code>
- GID: <code>{escape_html_safe(alert.get('gid', 'N/A'))}</code>
- Category: <code>{escape_html_safe(alert.get('category', 'N/A'))}</code>
- Signature: <i>{escape_html_safe(signature)}</i>

#mikroclear #security #alert
""".strip()

    def format_system_message(message: str, notification_type: str = "SYSTEM") -> str:
        return f"""
<b>Mikro-Clear System Notification</b>

<b>Type:</b> <code>{escape_html_safe(notification_type)}</code>
<b>Time:</b> <code>{dt.now().strftime('%d.%m.%Y %H:%M:%S')}</code>
<b>Message:</b> <i>{escape_html_safe(message)}</i>

#mikroclear #system
""".strip()

    def send_telegram_message(
        token: str,
        chat_id: str,
        text: str,
        reply_markup: Any = None,
        timeout: int = 10,
    ) -> TelegramSendResult:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup if isinstance(reply_markup, str) else ujson.dumps(reply_markup)

        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            timeout=timeout,
        )
        retry_after = 0
        if response.status_code == 429:
            try:
                retry_after = int(response.json().get("parameters", {}).get("retry_after", 0))
            except Exception:
                retry_after = 0
        return TelegramSendResult(
            ok=response.status_code == 200,
            status_code=response.status_code,
            response_text=mask_known_secret(response.text, token),
            retry_after=retry_after,
        )

try:
    from mikroclear.routeros_client import (
        RouterOsClientConfig,
        RouterOsConnectionManager,
        add_to_address_list,
        remove_from_address_list,
    )
except Exception:  # pragma: no cover - production single-file fallback
    class RouterOsClientConfig:
        def __init__(self, reconnect_sleep_seconds: int = 2) -> None:
            self.reconnect_sleep_seconds = reconnect_sleep_seconds

    class RouterOsConnectionManager:
        def __init__(
            self,
            config: Any,
            *,
            heartbeat: Any,
            reconnect: Any,
            log: Any,
            sleep: Any,
            transient_errors: Any = None,
        ) -> None:
            self._heartbeat = heartbeat
            self._reconnect = reconnect
            self._log = log
            self._transient_errors = transient_errors or (
                ssl.SSLError,
                librouteros.exceptions.ConnectionClosed,
                socket.timeout,
                TimeoutError,
            )

        def run_with_reconnect(self, operation_name: str, func: Any) -> Any:
            try:
                self._heartbeat(False)
                return func()
            except self._transient_errors as exc:
                self._log(f"RouterOS API error during {operation_name}: {type(exc).__name__}: {exc}")
                self._reconnect(f"{operation_name} failed")
                return func()

    def remove_from_address_list(address_list: Any, list_name: str, address: str) -> int:
        _address = Key("address")
        _id = Key(".id")
        _list = Key("list")
        rows = list(address_list.select(_id, _list, _address).where(_address == address, _list == list_name))
        removed = 0
        for row in rows:
            address_list.remove(row[".id"])
            removed += 1
        return removed

    def add_to_address_list(address_list: Any, list_name: str, address: str, comment: str, timeout: str) -> None:
        address_list.add(list=list_name, address=address, comment=comment, timeout=timeout)

try:
    from mikroclear.events import (
        should_process_event as decide_should_process_event,
        validate_event as validate_suricata_event,
    )
except Exception:  # pragma: no cover - production single-file fallback
    class _EventFilterDecision:
        def __init__(self, should_process: bool, message: str = "", log_method: str = "debug") -> None:
            self.should_process = should_process
            self.message = message
            self.log_method = log_method

    def validate_suricata_event(event: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(event, dict):
            return None
        alert = event.get("alert")
        if not isinstance(alert, dict) or "signature_id" not in alert:
            return None
        if not is_valid_ip(event.get("src_ip")) or not is_valid_ip(event.get("dest_ip")):
            return None
        return event

    def decide_should_process_event(
        event: Dict[str, Any],
        *,
        severities: Iterable[str],
        listen_interfaces: Iterable[str],
        ignore_predicate: Any,
        enable_ipv6: bool,
    ) -> Any:
        alert = event["alert"]
        sid = str(alert.get("signature_id", "N/A"))
        severity = str(alert.get("severity", ""))
        if severity not in tuple(str(item) for item in severities):
            return _EventFilterDecision(False, f"Skipping SID={sid}: severity={severity}")
        in_iface = str(event.get("in_iface", ""))
        allowed_interfaces = tuple(str(item) for item in listen_interfaces)
        if allowed_interfaces and in_iface not in allowed_interfaces:
            return _EventFilterDecision(False, f"Skipping SID={sid}: interface={in_iface}, allowed={allowed_interfaces}")
        if ignore_predicate(event):
            return _EventFilterDecision(False, f"Skipping alert SID={sid} - in ignore list", "log")
        src = str(event["src_ip"])
        if ":" in src and not enable_ipv6:
            return _EventFilterDecision(False, f"Skipping IPv6 alert because IPv6 disabled: {src}")
        return _EventFilterDecision(True)

try:
    from mikroclear.telegram_unblock import (
        build_unblock_keyboard,
        consume_unblock_token,
        create_unblock_token,
        parse_unblock_callback,
    )
except Exception:  # pragma: no cover - production single-file fallback
    import secrets

    _UNBLOCK_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")

    def _read_unblock_state(path: Path) -> Dict[str, Dict[str, Any]]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): v for k, v in data.items() if isinstance(v, dict)}
        except Exception:
            pass
        return {}

    def _write_unblock_state(path: Path, state: Dict[str, Dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")

    def create_unblock_token(
        path: Path,
        *,
        wanted_ip: str,
        list_name: str,
        sid: str,
        now: int,
        ttl_seconds: int,
        token_factory: Any = None,
    ) -> str:
        token = (token_factory or (lambda: secrets.token_urlsafe(12)))()
        state = _read_unblock_state(path)
        state[token] = {
            "wanted_ip": wanted_ip,
            "list_name": list_name,
            "sid": sid,
            "expires_at": int(now) + max(1, int(ttl_seconds)),
        }
        _write_unblock_state(path, state)
        return token

    def consume_unblock_token(path: Path, token: str, *, now: int) -> Optional[Dict[str, Any]]:
        if not _UNBLOCK_TOKEN_RE.match(token):
            return None
        state = _read_unblock_state(path)
        action = state.pop(token, None)
        changed = action is not None
        for key, value in list(state.items()):
            if int(value.get("expires_at", 0)) <= int(now):
                state.pop(key, None)
                changed = True
        if changed:
            _write_unblock_state(path, state)
        if not action or int(action.get("expires_at", 0)) <= int(now):
            return None
        return action

    def parse_unblock_callback(data: Any) -> Optional[str]:
        if not isinstance(data, str) or not data.startswith("unblock:"):
            return None
        token = data.partition(":")[2]
        return token if _UNBLOCK_TOKEN_RE.match(token) else None

    def build_unblock_keyboard(wanted_ip: str, token: str) -> Dict[str, Any]:
        return {
            "inline_keyboard": [
                [{"text": f"Unblock {wanted_ip}", "callback_data": f"unblock:{token}"}],
                [
                    {"text": "AbuseIPDB", "url": f"https://www.abuseipdb.com/check/{wanted_ip}"},
                    {"text": "VirusTotal", "url": f"https://www.virustotal.com/gui/ip-address/{wanted_ip}"},
                ],
            ]
        }

try:
    import librouteros.login as routeros_login  # type: ignore
except Exception:  # pragma: no cover
    routeros_login = None

VERSION = "3.1.1-TZSP0-ASSET-RESOLVER"

# ------------------------------------------------------------------------------
################# START EDIT SETTINGS
################# END EDIT SETTINGS
# ------------------------------------------------------------------------------


USERNAME = env_str("MIKROCATA_ROUTER_USERNAME", "mikrocata2selks")
PASSWORD = env_str("MIKROCATA_ROUTER_PASSWORD", "")
ROUTER_IP = env_str("MIKROCATA_ROUTER_IP", "192.168.10.1")
USE_SSL = env_bool("MIKROCATA_USE_SSL", True)
PORT = env_int("MIKROCATA_ROUTER_PORT", 8729 if USE_SSL else 8728)
ALLOW_SELF_SIGNED_CERTS = env_bool("MIKROCATA_ALLOW_SELF_SIGNED_CERTS", False)
CA_FILE = env_str("MIKROCATA_CA_FILE", "/etc/mikrocata/certs/mikrotik-ca.crt")
ROUTER_CONNECT_RETRY_SECONDS = env_int("MIKROCATA_ROUTER_CONNECT_RETRY_SECONDS", 30)
SOCKET_TIMEOUT_SECONDS = env_int("MIKROCATA_SOCKET_TIMEOUT_SECONDS", 20)
ROUTER_HEARTBEAT_SECONDS = env_int("MIKROCATA_ROUTER_HEARTBEAT_SECONDS", 60)
ROUTER_RECONNECT_SLEEP_SECONDS = env_int("MIKROCATA_ROUTER_RECONNECT_SLEEP_SECONDS", 2)

BLOCK_LIST_NAME = env_str("MIKROCATA_BLOCK_LIST_NAME", "Suricata")
TIMEOUT = env_str("MIKROCATA_BLOCK_TIMEOUT", "1d")
MONITOR_ONLY = env_bool("MIKROCATA_MONITOR_ONLY", False)

ENABLE_TELEGRAM = env_bool("MIKROCATA_TELEGRAM_ENABLE", False)
TELEGRAM_TOKEN = env_str("MIKROCATA_TELEGRAM_TOKEN", "")
TELEGRAM_CHATID = env_str("MIKROCATA_TELEGRAM_CHATID", "")
TELEGRAM_TIMEOUT = env_int("MIKROCATA_TELEGRAM_TIMEOUT", 10)
TELEGRAM_COOLDOWN_SECONDS = env_int("MIKROCATA_TELEGRAM_COOLDOWN_SECONDS", 2)
TELEGRAM_SYSTEM_COOLDOWN_SECONDS = env_int("MIKROCATA_TELEGRAM_SYSTEM_COOLDOWN_SECONDS", 300)
TELEGRAM_UNBLOCK_ENABLE = env_bool("MIKROCATA_TELEGRAM_UNBLOCK_ENABLE", True)
TELEGRAM_UNBLOCK_TTL_SECONDS = env_int("MIKROCATA_TELEGRAM_UNBLOCK_TTL_SECONDS", 24 * 3600)
TELEGRAM_UPDATES_INTERVAL_SECONDS = env_int("MIKROCATA_TELEGRAM_UPDATES_INTERVAL_SECONDS", 5)

WAN_IP = env_str("MIKROCATA_WAN_IP", "")
LOCAL_IP_PREFIX = env_str("MIKROCATA_LOCAL_IP_PREFIX", "192.168.0.0/16")
DEFAULT_WHITELIST = tuple(
    item
    for item in (
        WAN_IP,
        LOCAL_IP_PREFIX,
        "127.0.0.1",
        "1.1.1.1",
        "8.8.8.8",
        "fe80:",
        "10.0.0.0/8",
        "172.16.0.0/12",
    )
    if item
)
WHITELIST_IPS = env_csv("MIKROCATA_WHITELIST_IPS", DEFAULT_WHITELIST)
ENABLE_IPV6 = env_bool("MIKROCATA_ENABLE_IPV6", False)

SEVERITY = env_csv("MIKROCATA_SEVERITY", ("1", "2"))
LISTEN_INTERFACES = env_csv("MIKROCATA_LISTEN_INTERFACES", ("tzsp0",))
ADD_ON_START = env_bool("MIKROCATA_ADD_ON_START", False)
DEBUG_MODE = env_bool("MIKROCATA_DEBUG", False)

COMMENT_TIME_FORMAT = env_str("MIKROCATA_COMMENT_TIME_FORMAT", "%-d %b %Y %H:%M:%S.%f")
SELKS_CONTAINER_DATA_SURICATA_LOG = env_str(
    "MIKROCATA_SURICATA_LOG_DIR",
    "/opt/SELKS/docker/containers-data/suricata/logs/",
)
FILEPATH = os.path.abspath(
    env_str(
        "MIKROCATA_EVE_JSON",
        os.path.join(SELKS_CONTAINER_DATA_SURICATA_LOG, "eve.json"),
    )
)
STATE_DIR = os.path.abspath(env_str("MIKROCATA_STATE_DIR", "/var/lib/mikroclear"))
SAVE_LISTS_LOCATION = os.path.abspath(
    env_str("MIKROCATA_SAVE_LISTS_LOCATION", os.path.join(STATE_DIR, "savelists-tzsp0.json"))
)
SAVE_LISTS_LOCATION_V6 = os.path.abspath(
    env_str("MIKROCATA_SAVE_LISTS_LOCATION_V6", os.path.join(STATE_DIR, "savelists-tzsp0_v6.json"))
)
UPTIME_BOOKMARK = os.path.abspath(
    env_str("MIKROCATA_UPTIME_BOOKMARK", os.path.join(STATE_DIR, "uptime-tzsp0.bookmark"))
)
IGNORE_LIST_LOCATION = os.path.abspath(
    env_str("MIKROCATA_IGNORE_LIST_LOCATION", os.path.join(STATE_DIR, "ignore-tzsp0.conf"))
)
TELEGRAM_LOCK_FILE = os.path.abspath(
    env_str("MIKROCATA_TELEGRAM_LOCK_FILE", os.path.join(STATE_DIR, "telegram-rate-limit.lock"))
)
TELEGRAM_UNBLOCK_STATE_FILE = os.path.abspath(
    env_str("MIKROCATA_TELEGRAM_UNBLOCK_STATE_FILE", os.path.join(STATE_DIR, "telegram-unblock-actions.json"))
)
SAVE_LISTS = list(env_csv("MIKROCATA_SAVE_LISTS", (BLOCK_LIST_NAME,)))
SAVE_INTERVAL = env_int("MIKROCATA_SAVE_INTERVAL", 300)

# Asset Resolver: MikroTik DHCP leases + PTR DNS fallback for Telegram context
ASSET_RESOLVER_ENABLE = env_bool("MIKROCATA_ASSET_RESOLVER_ENABLE", True)
ASSET_RESOLVER_PRIVATE_ONLY = env_bool("MIKROCATA_ASSET_RESOLVER_PRIVATE_ONLY", True)
ASSET_RESOLVER_DHCP_ENABLE = env_bool("MIKROCATA_ASSET_RESOLVER_DHCP_ENABLE", True)
ASSET_RESOLVER_PTR_ENABLE = env_bool("MIKROCATA_ASSET_RESOLVER_PTR_ENABLE", True)
ASSET_RESOLVER_CACHE_TTL = env_int("MIKROCATA_ASSET_RESOLVER_CACHE_TTL", 3600)

ASSET_CACHE: Dict[str, Tuple[float, Dict[str, str]]] = {}

last_pos = 0
last_inode: Optional[int] = None
ignore_list: List[str] = []
last_save_time = 0
last_telegram_sent = 0.0
last_telegram_updates_check = 0.0
telegram_update_offset = 0
telegram_polling_backoff = TelegramPollingBackoff(
    base_seconds=max(TELEGRAM_UPDATES_INTERVAL_SECONDS, 30),
    max_seconds=300,
    log_every_seconds=120,
)
shutdown_requested = False
router_client: Optional["RouterOSClient"] = None


def log(message: str) -> None:
    print(f"[Mikro-Clear] {message}", flush=True)


def debug_log(message: str) -> None:
    if DEBUG_MODE:
        timestamp = dt.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp} Mikro-Clear-DEBUG] {message}", flush=True)


def on_signal(signum: int, frame: Any) -> None:
    global shutdown_requested
    shutdown_requested = True
    log(f"Signal {signum} received, stopping gracefully...")


def ensure_dirs() -> None:
    for path in (
        SAVE_LISTS_LOCATION,
        SAVE_LISTS_LOCATION_V6,
        UPTIME_BOOKMARK,
        IGNORE_LIST_LOCATION,
        TELEGRAM_LOCK_FILE,
    ):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)


def escape_html_safe(text: Any) -> str:
    if text is None:
        return ""
    return html.escape(str(text))


def sanitize_text(text: Any, max_len: int = 220) -> str:
    if text is None:
        return ""
    clean = "".join(char for char in str(text) if ord(char) < 128)
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > max_len:
        return clean[: max_len - 3] + "..."
    return clean


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
    except ValueError as exc:
        debug_log(f"Invalid IP while checking whitelist: {ip_to_check}: {exc}")
        return False

    for item in whitelist:
        if not item:
            continue
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
                log(f"Warning: invalid CIDR in whitelist: {item}")
            continue
        if not re.search(r"[^0-9a-fA-F:.]", item) and ip_to_check.startswith(item):
            return True
    return False


def telegram_locked_until() -> int:
    try:
        with open(TELEGRAM_LOCK_FILE, "r", encoding="utf-8") as fh:
            return int(fh.read().strip() or "0")
    except Exception:
        return 0


def set_telegram_lock(seconds: int) -> None:
    try:
        until = int(time()) + max(1, int(seconds))
        with open(TELEGRAM_LOCK_FILE, "w", encoding="utf-8") as fh:
            fh.write(str(until))
    except Exception as exc:
        debug_log(f"Could not write Telegram lock file: {exc}")


def sendTelegram(
    event: Optional[Dict[str, Any]] = None,
    wanted_ip: Optional[str] = None,
    src_ip: Optional[str] = None,
    wanted_port: Optional[Any] = None,
    action_type: str = "BLOCKED",
    is_system: bool = False,
    message: Optional[str] = None,
) -> bool:
    global last_telegram_sent

    if not ENABLE_TELEGRAM:
        return False
    if not TELEGRAM_TOKEN or not TELEGRAM_CHATID:
        debug_log("Telegram enabled, but token/chat_id is empty")
        return False

    now = int(time())
    locked_until = telegram_locked_until()
    if locked_until > now:
        debug_log(f"Telegram suppressed by rate-limit lock for {locked_until - now}s")
        return False

    min_interval = TELEGRAM_SYSTEM_COOLDOWN_SECONDS if is_system else TELEGRAM_COOLDOWN_SECONDS
    if time() - last_telegram_sent < min_interval:
        debug_log("Telegram suppressed by local cooldown")
        return False

    try:
        if is_system:
            if not message:
                return False
            formatted_message = message
        elif isinstance(event, dict):
            formatted_message = format_telegram_message_safe(event, wanted_ip, src_ip, wanted_port, action_type)
        else:
            formatted_message = (
                f"<b>Mikro-Clear Alert Data Issue</b>\n"
                f"IP: <code>{escape_html_safe(wanted_ip)}</code>\n"
                f"Action: <code>{escape_html_safe(action_type)}</code>"
            )

        reply_markup = None

        if wanted_ip and not is_system and isinstance(event, dict):
            token = None
            if TELEGRAM_UNBLOCK_ENABLE and action_type in {"BLOCKED", "UPDATED"}:
                alert = event.get("alert", {})
                sid = str(alert.get("signature_id", "N/A")) if isinstance(alert, dict) else "N/A"
                try:
                    token = create_unblock_token(
                        Path(TELEGRAM_UNBLOCK_STATE_FILE),
                        wanted_ip=str(wanted_ip),
                        list_name=BLOCK_LIST_NAME,
                        sid=sid,
                        now=now,
                        ttl_seconds=TELEGRAM_UNBLOCK_TTL_SECONDS,
                    )
                except Exception as exc:
                    log(f"Could not create Telegram unblock token for {wanted_ip}: {exc}")

            reply_markup = (
                build_unblock_keyboard(str(wanted_ip), token)
                if token
                else {
                    "inline_keyboard": [
                        [
                            {"text": "AbuseIPDB", "url": f"https://www.abuseipdb.com/check/{wanted_ip}"},
                            {"text": "VirusTotal", "url": f"https://www.virustotal.com/gui/ip-address/{wanted_ip}"},
                        ]
                    ]
                }
            )

        result = send_telegram_message(
            TELEGRAM_TOKEN,
            TELEGRAM_CHATID,
            formatted_message,
            reply_markup=reply_markup,
            timeout=TELEGRAM_TIMEOUT,
        )
        last_telegram_sent = time()

        if result.ok:
            debug_log("Telegram message sent successfully")
            return True

        log(f"Failed to send Telegram message: {mask_known_secret(result.response_text, TELEGRAM_TOKEN)}")
        if result.status_code == 429:
            retry_after = result.retry_after or TELEGRAM_SYSTEM_COOLDOWN_SECONDS
            set_telegram_lock(retry_after)
            log(f"Telegram flood control active, suppressing Telegram for {retry_after}s")
        return False
    except Exception as exc:
        log(f"Error sending Telegram message: {sanitize_exception_text(exc, TELEGRAM_TOKEN)}")
        return False



def is_private_ip_text(ip_text: Optional[str]) -> bool:
    if not ip_text:
        return False

    try:
        return ipaddress.ip_address(ip_text).is_private
    except ValueError:
        return False


def asset_cache_get(ip_text: str) -> Optional[Dict[str, str]]:
    cached = ASSET_CACHE.get(ip_text)

    if not cached:
        return None

    cached_time, cached_value = cached

    if time() - cached_time > ASSET_RESOLVER_CACHE_TTL:
        ASSET_CACHE.pop(ip_text, None)
        return None

    return cached_value


def asset_cache_set(ip_text: str, value: Dict[str, str]) -> Dict[str, str]:
    ASSET_CACHE[ip_text] = (time(), value)
    return value


def sanitize_asset_value(value: Any, max_len: int = 80) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)

    if len(text) > max_len:
        text = text[: max_len - 3] + "..."

    return text


def resolve_asset_from_dhcp(ip_text: str) -> Dict[str, str]:
    if not ASSET_RESOLVER_DHCP_ENABLE:
        return {}

    try:
        client = get_router_client()
        api = client.ensure_connected()
        leases = api.path("/ip/dhcp-server/lease")

        _address = Key("address")
        rows = list(
            leases.select(
                ".id",
                "address",
                "host-name",
                "comment",
                "mac-address",
                "server",
                "status",
                "dynamic",
            ).where(_address == ip_text)
        )

        if not rows:
            return {}

        row = rows[0]

        hostname = sanitize_asset_value(row.get("host-name"))
        comment = sanitize_asset_value(row.get("comment"))
        mac = sanitize_asset_value(row.get("mac-address"))
        server = sanitize_asset_value(row.get("server"))
        status = sanitize_asset_value(row.get("status"))
        dynamic = sanitize_asset_value(row.get("dynamic"))

        display_name = hostname or comment or mac

        return {
            "source": "dhcp",
            "name": display_name,
            "hostname": hostname,
            "comment": comment,
            "mac": mac,
            "server": server,
            "status": status,
            "dynamic": dynamic,
        }

    except (ssl.SSLError, librouteros.exceptions.ConnectionClosed, socket.timeout, TimeoutError) as exc:
        debug_log(f"Asset DHCP resolver connection error for {ip_text}: {type(exc).__name__}: {exc}")
        try:
            get_router_client().reconnect("asset resolver DHCP lookup failed")
        except Exception:
            pass
        return {}
    except Exception as exc:
        debug_log(f"Asset DHCP resolver failed for {ip_text}: {type(exc).__name__}: {exc}")
        return {}


def resolve_asset_from_ptr(ip_text: str) -> Dict[str, str]:
    if not ASSET_RESOLVER_PTR_ENABLE:
        return {}

    try:
        hostname = socket.gethostbyaddr(ip_text)[0]
        hostname = sanitize_asset_value(hostname)

        if not hostname:
            return {}

        return {
            "source": "ptr",
            "name": hostname,
            "hostname": hostname,
            "comment": "",
            "mac": "",
            "server": "",
            "status": "",
            "dynamic": "",
        }

    except Exception:
        return {}


def resolve_asset(ip_text: Optional[str]) -> Dict[str, str]:
    if not ASSET_RESOLVER_ENABLE:
        return {}

    if not ip_text or not is_valid_ip(ip_text):
        return {}

    if ASSET_RESOLVER_PRIVATE_ONLY and not is_private_ip_text(ip_text):
        return {}

    cached = asset_cache_get(ip_text)
    if cached is not None:
        return cached

    asset = resolve_asset_from_dhcp(ip_text)

    if not asset:
        asset = resolve_asset_from_ptr(ip_text)

    if not asset:
        asset = {
            "source": "",
            "name": "",
            "hostname": "",
            "comment": "",
            "mac": "",
            "server": "",
            "status": "",
            "dynamic": "",
        }

    return asset_cache_set(ip_text, asset)


def format_peer_with_asset(ip_text: Optional[str]) -> str:
    if not ip_text:
        return "<code>N/A</code>"

    asset = resolve_asset(ip_text)
    name = asset.get("name", "")
    source = asset.get("source", "")
    mac = asset.get("mac", "")
    comment = asset.get("comment", "")

    if not name:
        return f"<code>{escape_html_safe(ip_text)}</code>"

    result = f"<code>{escape_html_safe(ip_text)}</code> — <b>{escape_html_safe(name)}</b>"

    if source:
        result += f" <code>{escape_html_safe(source)}</code>"

    details = []

    if mac:
        details.append(f"MAC: <code>{escape_html_safe(mac)}</code>")

    if comment and comment != name:
        details.append(f"Comment: <code>{escape_html_safe(comment)}</code>")

    if details:
        result += "\n  " + "\n  ".join(details)

    return result

def format_telegram_message_safe(
    event: Dict[str, Any],
    wanted_ip: Optional[str],
    src_ip: Optional[str],
    wanted_port: Optional[Any],
    action_type: str,
) -> str:
    return format_alert_message(
        event,
        wanted_ip,
        src_ip,
        wanted_port,
        action_type,
        peer_formatter=format_peer_with_asset,
    )


def send_system_notification(message: str, notification_type: str = "SYSTEM") -> bool:
    formatted_message = format_system_message(message, notification_type)
    return sendTelegram(message=formatted_message, is_system=True)


def answer_telegram_callback(callback_id: str, text: str, alert: bool = False) -> None:
    if not TELEGRAM_TOKEN or not callback_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
            data={"callback_query_id": callback_id, "text": text, "show_alert": "true" if alert else "false"},
            timeout=TELEGRAM_TIMEOUT,
        )
    except Exception as exc:
        log(f"Error answering Telegram callback: {sanitize_exception_text(exc, TELEGRAM_TOKEN)}")


def record_telegram_polling_failure(error_text: str) -> None:
    should_log, delay = telegram_polling_backoff.record_failure(time(), error_text)
    if should_log:
        log(f"Error processing Telegram updates; retry in {delay}s: {error_text}")


def remove_address_from_list(address_list: Any, wanted_ip: str, list_name: str) -> bool:
    return remove_from_address_list(address_list, list_name, wanted_ip) > 0


def handle_unblock_action(action: Dict[str, Any]) -> str:
    wanted_ip = str(action.get("wanted_ip", ""))
    list_name = str(action.get("list_name") or BLOCK_LIST_NAME)
    if not is_valid_ip(wanted_ip):
        return "Invalid unblock target"
    if is_ip_in_whitelist(wanted_ip, WHITELIST_IPS):
        return f"Refusing to unblock whitelisted target {wanted_ip}"

    client = get_router_client()

    def remove_batch() -> bool:
        address_list, address_list_v6, _resources = client.paths()
        target_list = address_list_v6 if ":" in wanted_ip and address_list_v6 is not None else address_list
        return remove_address_from_list(target_list, wanted_ip, list_name)

    removed = client.run_with_reconnect("telegram unblock", remove_batch)
    if removed:
        log(f"TELEGRAM UNBLOCKED: {wanted_ip} from {list_name} - SID:{action.get('sid', 'N/A')}")
        return f"Unblocked {wanted_ip}"
    log(f"TELEGRAM UNBLOCK NOOP: {wanted_ip} not found in {list_name}")
    return f"{wanted_ip} was not found in {list_name}"


def process_telegram_updates() -> None:
    global telegram_update_offset

    if not ENABLE_TELEGRAM or not TELEGRAM_UNBLOCK_ENABLE or not TELEGRAM_TOKEN or not TELEGRAM_CHATID:
        return

    now = time()
    if not telegram_polling_backoff.should_poll(now):
        return

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"offset": telegram_update_offset, "timeout": 0, "allowed_updates": ujson.dumps(["callback_query"])},
            timeout=TELEGRAM_TIMEOUT,
        )
        if response.status_code != 200:
            error_text = mask_known_secret(
                f"HTTP {response.status_code}: {response.text[:120]}",
                TELEGRAM_TOKEN,
            )
            record_telegram_polling_failure(error_text)
            return

        body = response.json()
        if not body.get("ok"):
            error_text = mask_known_secret(f"not ok: {str(body)[:120]}", TELEGRAM_TOKEN)
            record_telegram_polling_failure(error_text)
            return
        telegram_polling_backoff.record_success(time())
    except Exception as exc:
        record_telegram_polling_failure(sanitize_exception_text(exc, TELEGRAM_TOKEN))
        return

    for update in body.get("result", []):
        update_id = int(update.get("update_id", 0))
        telegram_update_offset = max(telegram_update_offset, update_id + 1)
        callback = update.get("callback_query") or {}
        callback_id = str(callback.get("id", ""))
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        if chat_id != str(TELEGRAM_CHATID):
            answer_telegram_callback(callback_id, "Unauthorized chat", True)
            log(f"Rejected Telegram callback from unauthorized chat {chat_id}")
            continue

        token = parse_unblock_callback(callback.get("data"))
        if not token:
            continue

        action = consume_unblock_token(Path(TELEGRAM_UNBLOCK_STATE_FILE), token, now=int(time()))
        if not action:
            answer_telegram_callback(callback_id, "Unblock request expired or already used", True)
            continue

        result = handle_unblock_action(action)
        answer_telegram_callback(callback_id, result)
        send_system_notification(result, "UNBLOCK")


def make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2

    if ALLOW_SELF_SIGNED_CERTS:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    else:
        if not os.path.isfile(CA_FILE):
            raise FileNotFoundError(f"CA file not found: {CA_FILE}")
        ctx.load_verify_locations(cafile=CA_FILE)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED

    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except Exception:
        pass

    ctx.options |= ssl.OP_NO_COMPRESSION
    return ctx


class RouterOSClient:
    def __init__(self) -> None:
        self.api: Any = None
        self.connected_at: float = 0.0
        self.last_heartbeat: float = 0.0

    def close(self) -> None:
        if self.api is not None:
            try:
                close_method = getattr(self.api, "close", None)
                if callable(close_method):
                    close_method()
            except Exception:
                pass
        self.api = None

    def connect_once(self) -> Any:
        actual_port = PORT or (8729 if USE_SSL else 8728)
        socket.setdefaulttimeout(SOCKET_TIMEOUT_SECONDS)

        kwargs: Dict[str, Any] = {
            "username": USERNAME,
            "password": PASSWORD,
            "host": ROUTER_IP,
            "port": actual_port,
        }

        if routeros_login is not None and hasattr(routeros_login, "plain"):
            kwargs["login_method"] = routeros_login.plain

        if USE_SSL:
            ctx = make_ssl_context()
            kwargs["ssl_wrapper"] = ctx.wrap_socket

        return connect(**kwargs)

    def connect(self) -> None:
        actual_port = PORT or (8729 if USE_SSL else 8728)

        if not USERNAME or not PASSWORD or not ROUTER_IP:
            log("RouterOS credentials are incomplete. Check MIKROCLEAR_ROUTER_USERNAME/PASSWORD/IP.")
            while not shutdown_requested:
                sleep(ROUTER_CONNECT_RETRY_SECONDS)
            return

        while not shutdown_requested:
            try:
                self.close()
                log(f"Connecting to MikroTik {ROUTER_IP}:{actual_port} via {'SSL' if USE_SSL else 'plain API'}...")
                self.api = self.connect_once()
                self.connected_at = time()
                self.last_heartbeat = 0.0
                log("Connected to MikroTik")
                send_system_notification(
                    f"Connected to MikroTik {ROUTER_IP}:{actual_port} via {'SSL' if USE_SSL else 'plain API'}",
                    "SYSTEM",
                )
                return
            except librouteros.exceptions.TrapError as exc:
                msg = str(exc).lower()
                if "invalid user name or password" in msg:
                    log("Invalid MikroTik username or password. Retrying later.")
                else:
                    log(f"MikroTik TrapError during login: {exc}")
                sleep(ROUTER_CONNECT_RETRY_SECONDS)
            except librouteros.exceptions.ConnectionClosed as exc:
                log(f"Connection closed during RouterOS login: {exc}. Retrying in {ROUTER_CONNECT_RETRY_SECONDS}s.")
                sleep(ROUTER_CONNECT_RETRY_SECONDS)
            except (ssl.SSLError, socket.timeout, TimeoutError) as exc:
                log(f"SSL/socket error connecting to MikroTik: {type(exc).__name__}: {exc}. Retrying in {ROUTER_CONNECT_RETRY_SECONDS}s.")
                sleep(ROUTER_CONNECT_RETRY_SECONDS)
            except ConnectionRefusedError:
                log(f"Connection refused. Check /ip service api-ssl and firewall. Retrying in {ROUTER_CONNECT_RETRY_SECONDS}s.")
                sleep(ROUTER_CONNECT_RETRY_SECONDS)
            except OSError as exc:
                log(f"OS error connecting to MikroTik: {exc}. Retrying in {ROUTER_CONNECT_RETRY_SECONDS}s.")
                sleep(ROUTER_CONNECT_RETRY_SECONDS)
            except Exception as exc:
                log(f"Unexpected error connecting to MikroTik: {type(exc).__name__}: {exc}")
                if DEBUG_MODE:
                    print(traceback.format_exc(), flush=True)
                sleep(ROUTER_CONNECT_RETRY_SECONDS)

    def reconnect(self, reason: str = "") -> None:
        if reason:
            log(f"RouterOS API reconnect requested: {reason}")
        self.close()
        sleep(max(0, ROUTER_RECONNECT_SLEEP_SECONDS))
        self.connect()

    def ensure_connected(self) -> Any:
        if self.api is None:
            self.connect()
        return self.api

    def heartbeat(self, force: bool = False) -> bool:
        now = time()
        if not force and now - self.last_heartbeat < ROUTER_HEARTBEAT_SECONDS:
            return True

        try:
            api = self.ensure_connected()
            resources = api.path("/system/resource")
            for _ in resources:
                break
            self.last_heartbeat = now
            return True
        except (ssl.SSLError, librouteros.exceptions.ConnectionClosed, socket.timeout, TimeoutError) as exc:
            self.reconnect(f"heartbeat failed: {type(exc).__name__}: {exc}")
            return False
        except Exception as exc:
            log(f"RouterOS heartbeat error: {type(exc).__name__}: {exc}")
            return False

    def paths(self) -> Tuple[Any, Optional[Any], Any]:
        api = self.ensure_connected()
        address_list = api.path("/ip/firewall/address-list")
        address_list_v6 = api.path("/ipv6/firewall/address-list") if ENABLE_IPV6 else None
        resources = api.path("/system/resource")
        return address_list, address_list_v6, resources

    def run_with_reconnect(self, operation_name: str, func: Any) -> Any:
        manager = RouterOsConnectionManager(
            RouterOsClientConfig(reconnect_sleep_seconds=ROUTER_RECONNECT_SLEEP_SECONDS),
            heartbeat=self.heartbeat,
            reconnect=self.reconnect,
            log=log,
            sleep=sleep,
            transient_errors=(ssl.SSLError, librouteros.exceptions.ConnectionClosed, socket.timeout, TimeoutError),
        )
        return manager.run_with_reconnect(operation_name, func)


def get_router_client() -> RouterOSClient:
    global router_client
    if router_client is None:
        router_client = RouterOSClient()
    return router_client


class EventHandler(pyinotify.ProcessEvent):
    def process_IN_MODIFY(self, event: Any) -> None:
        if event.pathname == FILEPATH:
            try:
                add_to_tik(read_json(FILEPATH))
            except Exception as exc:
                log(f"Error processing eve.json modification: {type(exc).__name__}: {exc}")
                if DEBUG_MODE:
                    print(traceback.format_exc(), flush=True)

    def process_IN_CREATE(self, event: Any) -> None:
        if event.pathname == FILEPATH:
            global last_pos, last_inode
            log("New eve.json detected. Resetting file position.")
            last_pos = 0
            last_inode = None
            self.process_IN_MODIFY(event)

    def process_IN_DELETE(self, event: Any) -> None:
        if event.pathname == FILEPATH:
            log("eve.json deleted. Waiting for new file.")

    def process_IN_MOVED_TO(self, event: Any) -> None:
        if event.pathname == FILEPATH:
            self.process_IN_CREATE(event)


def seek_to_end(fpath: str) -> None:
    global last_pos, last_inode
    if ADD_ON_START:
        last_pos = 0
        last_inode = None
        return

    while not shutdown_requested:
        try:
            stat = os.stat(fpath)
            last_pos = stat.st_size
            last_inode = stat.st_ino
            debug_log(f"Initial file position set to EOF: {last_pos}")
            return
        except FileNotFoundError:
            log(f"File {fpath} not found. Retrying in 10 seconds...")
            sleep(10)


def read_json(fpath: str) -> List[Dict[str, Any]]:
    global last_pos, last_inode

    try:
        stat = os.stat(fpath)
        if last_inode is not None and stat.st_ino != last_inode:
            debug_log("eve.json inode changed, resetting position")
            last_pos = 0
        if stat.st_size < last_pos:
            debug_log("eve.json truncated/rotated, resetting position")
            last_pos = 0
        last_inode = stat.st_ino
    except FileNotFoundError:
        log(f"File {fpath} not found")
        return []

    alerts: List[Dict[str, Any]] = []
    valid_lines = 0
    error_lines = 0
    other_events = 0

    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
            fh.seek(last_pos)
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except Exception as exc:
                    error_lines += 1
                    if DEBUG_MODE and error_lines <= 3:
                        debug_log(f"JSON parse error, skipping line: {str(exc)[:120]}")
                    continue
                valid_lines += 1
                if data.get("event_type") == "alert":
                    alerts.append(data)
                else:
                    other_events += 1
            last_pos = fh.tell()
    except Exception as exc:
        log(f"Error reading {fpath}: {type(exc).__name__}: {exc}")
        return []

    debug_log(f"Read summary: {len(alerts)} alerts, {other_events} other events, {error_lines} errors, pos={last_pos}")
    return alerts


def validate_event(event: Any) -> Optional[Dict[str, Any]]:
    validated = validate_suricata_event(event)
    if validated is not None:
        return validated

    if not isinstance(event, dict):
        debug_log(f"Skipping non-dict event: {type(event)}")
        return None

    alert = event.get("alert")
    if not isinstance(alert, dict):
        debug_log("Skipping event without alert dict")
        return None

    if "signature_id" not in alert:
        debug_log("Skipping event without alert.signature_id")
        return None

    src_ip = event.get("src_ip")
    dest_ip = event.get("dest_ip")
    if not is_valid_ip(src_ip) or not is_valid_ip(dest_ip):
        debug_log(f"Skipping event with invalid src/dest IP: {src_ip} -> {dest_ip}")
        return None

    return None


def add_to_tik(alerts: Optional[List[Dict[str, Any]]]) -> None:
    global last_save_time

    if not alerts:
        debug_log("No alerts to process")
        return

    client = get_router_client()

    valid_events: List[Dict[str, Any]] = []
    for raw in alerts:
        event = validate_event(raw)
        if event is not None:
            valid_events.append(event)

    if not valid_events:
        return

    unique: Dict[str, Dict[str, Any]] = {}
    for event in valid_events:
        src = str(event["src_ip"])
        dst = str(event["dest_ip"])
        target_ip = dst if is_ip_in_whitelist(src, WHITELIST_IPS) else src
        unique[target_ip] = event

    debug_log(f"Processing {len(unique)} unique target IPs from {len(valid_events)} valid alerts")

    def process_batch() -> None:
        address_list, address_list_v6, _resources = client.paths()
        for event in unique.values():
            process_single_alert(event, address_list, address_list_v6)

    client.run_with_reconnect("processing alerts", process_batch)

    current_time = int(time())
    if current_time - last_save_time >= SAVE_INTERVAL:
        last_save_time = current_time

        def save_restore_batch() -> None:
            address_list, address_list_v6, resources = client.paths()

            if check_tik_uptime(resources):
                log("Router reboot detected - restoring saved lists")
                send_system_notification("Router reboot detected - restoring saved address lists", "RESTORE")
                add_saved_lists(address_list)
                if ENABLE_IPV6 and address_list_v6 is not None:
                    add_saved_lists(address_list_v6, True)

            save_lists(address_list)

            if ENABLE_IPV6 and address_list_v6 is not None:
                save_lists(address_list_v6, True)

        try:
            client.run_with_reconnect("saving/restoring lists", save_restore_batch)
        except Exception as exc:
            log(f"ERROR while saving/restoring lists after reconnect retry: {type(exc).__name__}: {exc}")
            if DEBUG_MODE:
                print(traceback.format_exc(), flush=True)


def process_single_alert(event: Dict[str, Any], address_list: Any, address_list_v6: Any) -> None:
    alert = event["alert"]
    sid = str(alert.get("signature_id", "N/A"))
    filter_decision = decide_should_process_event(
        event,
        severities=SEVERITY,
        listen_interfaces=LISTEN_INTERFACES,
        ignore_predicate=lambda item: in_ignore_list(ignore_list, dict(item)),
        enable_ipv6=ENABLE_IPV6,
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
    curr_list = address_list_v6 if ENABLE_IPV6 and is_v6 and address_list_v6 is not None else address_list

    if is_ip_in_whitelist(src, WHITELIST_IPS):
        if is_ip_in_whitelist(dst, WHITELIST_IPS):
            debug_log(f"Skipping SID={sid}: src and dst are whitelisted")
            return
        wanted_ip = dst
        wanted_port = event.get("dest_port")
        peer_ip = src
    else:
        wanted_ip = src
        wanted_port = event.get("dest_port")
        peer_ip = dst

    if is_ip_in_whitelist(wanted_ip, WHITELIST_IPS):
        log(f"Skipping target IP {wanted_ip}: whitelisted")
        return

    timestamp = format_event_timestamp(event.get("timestamp"))
    signature = sanitize_text(alert.get("signature", ""), 180)
    gid = alert.get("gid", 1)
    severity = str(alert.get("severity", "N/A"))
    proto = event.get("proto", "")
    comment = f"[{gid}:{sid}] {signature} ::: Port: {wanted_port}/{proto} ::: timestamp: {timestamp}"

    if MONITOR_ONLY:
        log(f"MONITOR_ONLY: would block {wanted_ip} - SID:{sid} - Severity:{severity}")
        sendTelegram(event=event, wanted_ip=wanted_ip, src_ip=peer_ip, wanted_port=wanted_port, action_type="MONITOR")
        return

    try:
        debug_log(f"Adding to MikroTik list={BLOCK_LIST_NAME}, address={wanted_ip}, timeout={TIMEOUT}")
        add_to_address_list(curr_list, BLOCK_LIST_NAME, wanted_ip, comment, TIMEOUT)
        log(f"BLOCKED: {wanted_ip} - SID:{sid} - Severity:{severity}")
        sendTelegram(event=event, wanted_ip=wanted_ip, src_ip=peer_ip, wanted_port=wanted_port, action_type="BLOCKED")
    except librouteros.exceptions.TrapError as exc:
        if "already have such entry" in str(exc):
            update_existing_address(curr_list, wanted_ip, comment, event, peer_ip, wanted_port)
            return
        log(f"MikroTik TrapError for {wanted_ip}: {exc}")
        raise


def update_existing_address(curr_list: Any, wanted_ip: str, comment: str, event: Dict[str, Any], peer_ip: str, wanted_port: Any) -> None:
    _address = Key("address")
    _id = Key(".id")
    _list = Key("list")

    rows = list(curr_list.select(_id, _list, _address).where(_address == wanted_ip, _list == BLOCK_LIST_NAME))
    for row in rows:
        curr_list.remove(row[".id"])

    add_to_address_list(curr_list, BLOCK_LIST_NAME, wanted_ip, comment, TIMEOUT)
    sid = event.get("alert", {}).get("signature_id", "N/A")
    log(f"UPDATED: {wanted_ip} - SID:{sid}")
    sendTelegram(event=event, wanted_ip=wanted_ip, src_ip=peer_ip, wanted_port=wanted_port, action_type="UPDATED")


def format_event_timestamp(value: Any) -> str:
    try:
        return dt.strptime(str(value), "%Y-%m-%dT%H:%M:%S.%f%z").strftime(COMMENT_TIME_FORMAT)
    except Exception:
        return dt.now().strftime(COMMENT_TIME_FORMAT)


def check_tik_uptime(resources: Any) -> bool:
    uptime = "0s"
    for row in resources:
        uptime = row.get("uptime", "0s")
        break

    total_seconds = parse_routeros_uptime(str(uptime))
    if total_seconds < 900:
        total_seconds = 900

    try:
        with open(UPTIME_BOOKMARK, "r", encoding="utf-8") as fh:
            bookmark = int(fh.read().strip() or "0")
    except Exception:
        bookmark = 0

    with open(UPTIME_BOOKMARK, "w", encoding="utf-8") as fh:
        fh.write(str(total_seconds))

    rebooted = total_seconds < bookmark
    debug_log(f"Router uptime={total_seconds}s previous={bookmark}s rebooted={rebooted}")
    return rebooted


def parse_routeros_uptime(uptime: str) -> int:
    units = {"w": 7 * 24 * 3600, "d": 24 * 3600, "h": 3600, "m": 60, "s": 1}
    total = 0
    for num, unit in re.findall(r"(\d+)([wdhms])", uptime):
        total += int(num) * units[unit]
    return total


def save_lists(address_list: Any, is_v6: bool = False) -> None:
    _address = Key("address")
    _list = Key("list")
    _timeout = Key("timeout")
    _comment = Key("comment")
    curr_file = SAVE_LISTS_LOCATION_V6 if is_v6 else SAVE_LISTS_LOCATION
    tmp_file = curr_file + ".tmp"

    with open(tmp_file, "w", encoding="utf-8") as fh:
        for save_list in SAVE_LISTS:
            for row in address_list.select(_list, _address, _timeout, _comment).where(_list == save_list):
                fh.write(ujson.dumps(row) + "\n")

    os.replace(tmp_file, curr_file)
    debug_log(f"Saved address-list state to {curr_file}")


def add_saved_lists(address_list: Any, is_v6: bool = False) -> None:
    curr_file = SAVE_LISTS_LOCATION_V6 if is_v6 else SAVE_LISTS_LOCATION

    try:
        with open(curr_file, "r", encoding="utf-8") as fh:
            rows = [ujson.loads(line) for line in fh if line.strip()]
    except FileNotFoundError:
        debug_log(f"No saved list file: {curr_file}")
        return

    restored = 0
    skipped = 0

    for row in rows:
        address = row.get("address")
        if not address or is_ip_in_whitelist(str(address), WHITELIST_IPS):
            skipped += 1
            continue

        try:
            address_list.add(
                list=row.get("list", BLOCK_LIST_NAME),
                address=address,
                comment=row.get("comment") or "",
                timeout=row.get("timeout") or TIMEOUT,
            )
            restored += 1
        except librouteros.exceptions.TrapError as exc:
            if "already have such entry" in str(exc):
                continue
            raise

    debug_log(f"Restored {restored} saved addresses from {curr_file}, skipped={skipped}")


def read_ignore_list(fpath: str) -> None:
    global ignore_list
    ignore_list = []

    try:
        with open(fpath, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.partition("#")[0].strip()
                if line:
                    ignore_list.append(line)
    except FileNotFoundError:
        log(f"Ignore list {fpath} not found. Continuing.")

    debug_log(f"Ignore list loaded: {len(ignore_list)} entries")


def in_ignore_list(ignr_list: Iterable[str], event: Dict[str, Any]) -> bool:
    alert = event.get("alert", {})
    if not isinstance(alert, dict):
        return False

    sid = str(alert.get("signature_id", ""))
    signature = str(alert.get("signature", ""))

    for entry in ignr_list:
        try:
            if entry.isdigit() and sid.isdigit() and int(entry) == int(sid):
                debug_log(f"SID {sid} matched ignore entry {entry}")
                return True

            if entry.startswith("re:"):
                pattern = entry.partition("re:")[2].strip()
                if pattern and re.search(pattern, signature):
                    debug_log(f"Signature matched ignore regex: {pattern}")
                    return True
        except Exception as exc:
            log(f"Invalid ignore-list entry {entry!r}: {exc}")

    return False


def print_startup_config() -> None:
    log(f"Starting Mikro-Clear v{VERSION}")
    log(f"Python: {sys.version.split()[0]}")
    log(f"eve.json: {FILEPATH}")
    log(f"RouterOS API: {ROUTER_IP}:{PORT} {'SSL' if USE_SSL else 'plain'}")
    log(f"CA file: {CA_FILE if USE_SSL else 'N/A'}")
    log(f"Address-list: {BLOCK_LIST_NAME}, timeout={TIMEOUT}, monitor_only={MONITOR_ONLY}")
    log(f"Save interval: {SAVE_INTERVAL}s, heartbeat={ROUTER_HEARTBEAT_SECONDS}s")
    log(
        f"Asset resolver: {'enabled' if ASSET_RESOLVER_ENABLE else 'disabled'}, "
        f"dhcp={'enabled' if ASSET_RESOLVER_DHCP_ENABLE else 'disabled'}, "
        f"ptr={'enabled' if ASSET_RESOLVER_PTR_ENABLE else 'disabled'}, "
        f"private_only={ASSET_RESOLVER_PRIVATE_ONLY}, ttl={ASSET_RESOLVER_CACHE_TTL}s"
    )
    log(f"Interfaces: {LISTEN_INTERFACES}, severities={SEVERITY}")
    log(f"Telegram: {'enabled' if ENABLE_TELEGRAM else 'disabled'}")
    log(f"Debug: {'enabled' if DEBUG_MODE else 'disabled'}")


def main() -> int:
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    ensure_dirs()
    print_startup_config()
    send_system_notification(f"Mikro-Clear v{VERSION} started", "START")

    seek_to_end(FILEPATH)

    client = get_router_client()
    client.connect()
    client.heartbeat(force=True)

    read_ignore_list(IGNORE_LIST_LOCATION)

    directory_to_monitor = os.path.dirname(FILEPATH) or "."
    wm = pyinotify.WatchManager()
    handler = EventHandler()
    notifier = pyinotify.Notifier(wm, handler)
    mask = pyinotify.IN_CREATE | pyinotify.IN_MODIFY | pyinotify.IN_DELETE | pyinotify.IN_MOVED_TO
    wm.add_watch(directory_to_monitor, mask, rec=False)

    log(f"Monitoring {FILEPATH} for Suricata alerts")
    log(f"Whitelist: {WHITELIST_IPS}")

    last_idle_heartbeat = 0.0
    global last_telegram_updates_check

    while not shutdown_requested:
        try:
            notifier.process_events()
            if notifier.check_events(timeout=1000):
                notifier.read_events()

            if time() - last_telegram_updates_check >= TELEGRAM_UPDATES_INTERVAL_SECONDS:
                last_telegram_updates_check = time()
                process_telegram_updates()

            if time() - last_idle_heartbeat >= ROUTER_HEARTBEAT_SECONDS:
                last_idle_heartbeat = time()
                client.heartbeat()

        except KeyboardInterrupt:
            break
        except Exception as exc:
            log(f"Unexpected error in main loop: {type(exc).__name__}: {exc}")
            if DEBUG_MODE:
                print(traceback.format_exc(), flush=True)
            sleep(5)

    try:
        notifier.stop()
    except Exception:
        pass

    try:
        client.close()
    except Exception:
        pass

    send_system_notification(f"Mikro-Clear v{VERSION} stopped", "STOP")
    log("Stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
