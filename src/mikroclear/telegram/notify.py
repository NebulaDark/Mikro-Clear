from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

import requests

from mikroclear.security import mask_known_secret
from mikroclear.telegram.formatting import escape_html_safe, format_alert_message, format_system_message
from mikroclear.telegram.rate_limit import TelegramRateLimitLock
from mikroclear.telegram.unblock import build_unblock_keyboard, create_unblock_token


@dataclass(frozen=True)
class TelegramSendResult:
    ok: bool
    status_code: int = 0
    response_text: str = ""
    retry_after: int = 0


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
        response_text=mask_known_secret(response.text, token),
        retry_after=retry_after,
    )


class TelegramNotifier:
    def __init__(
        self,
        settings: Any,
        *,
        peer_formatter: Callable[[Any], str] | None,
        log: Callable[[str], None],
        debug_log: Callable[[str], None],
        sanitize_exception_text: Callable[..., str],
        now: Callable[[], float],
        send_message: Callable[..., TelegramSendResult] = send_telegram_message,
    ) -> None:
        self.settings = settings
        self.peer_formatter = peer_formatter
        self.log = log
        self.debug_log = debug_log
        self.sanitize_exception_text = sanitize_exception_text
        self.now = now
        self.send_message = send_message
        self.last_sent = 0.0
        self.lock = TelegramRateLimitLock(settings.telegram_lock_file, now=now, debug_log=debug_log)

    def send_alert(
        self,
        *,
        event: dict[str, Any] | None = None,
        wanted_ip: str | None = None,
        src_ip: str | None = None,
        wanted_port: Any = None,
        action_type: str = "BLOCKED",
        is_system: bool = False,
        message: str | None = None,
    ) -> bool:
        if not self.settings.enable_telegram:
            return False
        if not self.settings.telegram_token or not self.settings.telegram_chatid:
            self.debug_log("Telegram enabled, but token/chat_id is empty")
            return False

        now = int(self.now())
        locked_until = self.lock.locked_until()
        if locked_until > now:
            self.debug_log(f"Telegram suppressed by rate-limit lock for {locked_until - now}s")
            return False

        min_interval = (
            self.settings.telegram_system_cooldown_seconds
            if is_system
            else self.settings.telegram_cooldown_seconds
        )
        if self.now() - self.last_sent < min_interval:
            self.debug_log("Telegram suppressed by local cooldown")
            return False

        try:
            if is_system:
                if not message:
                    return False
                formatted_message = message
            elif isinstance(event, dict):
                formatted_message = format_alert_message(
                    event,
                    wanted_ip,
                    src_ip,
                    wanted_port,
                    action_type,
                    peer_formatter=self.peer_formatter,
                )
            else:
                formatted_message = (
                    "<b>Mikro-Clear Alert Data Issue</b>\n"
                    f"IP: <code>{escape_html_safe(wanted_ip)}</code>\n"
                    f"Action: <code>{escape_html_safe(action_type)}</code>"
                )

            reply_markup = self._build_reply_markup(event, wanted_ip, action_type, now, is_system)
            result = self.send_message(
                self.settings.telegram_token,
                self.settings.telegram_chatid,
                formatted_message,
                reply_markup=reply_markup,
                timeout=self.settings.telegram_timeout,
            )
            self.last_sent = self.now()

            if result.ok:
                self.debug_log("Telegram message sent successfully")
                return True

            self.log(f"Failed to send Telegram message: {mask_known_secret(result.response_text, self.settings.telegram_token)}")
            if result.status_code == 429:
                retry_after = result.retry_after or self.settings.telegram_system_cooldown_seconds
                self.lock.set(retry_after)
                self.log(f"Telegram flood control active, suppressing Telegram for {retry_after}s")
            return False
        except Exception as exc:
            self.log(f"Error sending Telegram message: {self.sanitize_exception_text(exc, self.settings.telegram_token)}")
            return False

    def send_system_notification(self, message: str, notification_type: str = "SYSTEM") -> bool:
        formatted_message = format_system_message(message, notification_type)
        return self.send_alert(message=formatted_message, is_system=True)

    def _build_reply_markup(
        self,
        event: dict[str, Any] | None,
        wanted_ip: str | None,
        action_type: str,
        now: int,
        is_system: bool,
    ) -> Any:
        if not wanted_ip or is_system or not isinstance(event, dict):
            return None

        token = None
        if self.settings.telegram_unblock_enable and action_type in {"BLOCKED", "UPDATED"}:
            alert = event.get("alert", {})
            sid = str(alert.get("signature_id", "N/A")) if isinstance(alert, dict) else "N/A"
            try:
                token = create_unblock_token(
                    Path(self.settings.telegram_unblock_state_file),
                    wanted_ip=str(wanted_ip),
                    list_name=self.settings.block_list_name,
                    sid=sid,
                    now=now,
                    ttl_seconds=self.settings.telegram_unblock_ttl_seconds,
                )
            except Exception as exc:
                self.log(f"Could not create Telegram unblock token for {wanted_ip}: {exc}")

        if token:
            return build_unblock_keyboard(str(wanted_ip), token)

        return {
            "inline_keyboard": [
                [
                    {"text": "AbuseIPDB", "url": f"https://www.abuseipdb.com/check/{wanted_ip}"},
                    {"text": "VirusTotal", "url": f"https://www.virustotal.com/gui/ip-address/{wanted_ip}"},
                ]
            ]
        }
