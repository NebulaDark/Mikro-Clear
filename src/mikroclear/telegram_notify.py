from dataclasses import dataclass
from datetime import datetime as dt
import html
import json
import re
from typing import Any, Callable

import requests


@dataclass(frozen=True)
class TelegramSendResult:
    ok: bool
    status_code: int = 0
    response_text: str = ""
    retry_after: int = 0


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


def default_peer_formatter(ip_text: Any) -> str:
    return f"<code>{escape_html_safe(ip_text or 'N/A')}</code>"


def format_alert_message(
    event: dict[str, Any],
    wanted_ip: Any,
    peer_ip: Any,
    wanted_port: Any,
    action_type: str,
    peer_formatter: Callable[[Any], str] | None = None,
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
    format_peer = peer_formatter or default_peer_formatter

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
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup if isinstance(reply_markup, str) else json.dumps(reply_markup)

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
        response_text=response.text,
        retry_after=retry_after,
    )
