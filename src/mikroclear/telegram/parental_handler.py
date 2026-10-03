"""Telegram confirmation workflow for YouTube policy changes."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any, Callable

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.audit import BotAuditLog
from mikroclear.bot.gates import bot_module_enabled
from mikroclear.bot.modules.parental import (
    build_parental_confirmation,
    build_parental_error_view,
    build_parental_view,
)
from mikroclear.security import sanitize_exception_text
from mikroclear.telegram.commands import raise_for_retryable_delivery


class TelegramParentalHandler:
    def __init__(self, settings: Any, *, policy: Any, bot_settings: Any, audit: BotAuditLog, log: Callable[[str], None], now: Callable[[], float] | None = None, token_factory: Callable[[], str] | None = None):
        self.settings = settings
        self.policy = policy
        self.bot_settings = bot_settings
        self.audit = audit
        self.log = log
        self.now = now or __import__("time").time
        self.token_factory = token_factory or (lambda: secrets.token_urlsafe(12))

    @property
    def state_file(self) -> Path:
        return Path(self.settings.state_dir) / "telegram-parental-actions.json"

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_file.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, ValueError, OSError):
            return {}

    def _write(self, value: dict[str, Any]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        self.state_file.chmod(0o600)

    def _enabled(self) -> bool:
        return bot_module_enabled(self.bot_settings, "parental_control", feature_enabled=bool(self.settings.parental_control_enable and self.settings.pihole_enable))

    def _safe_error(self, exc: BaseException, *extra_secrets: str) -> str:
        secrets = [
            getattr(self.settings, "pihole_app_password", ""),
            getattr(self.settings, "pihole_sid", ""),
            getattr(self.settings, "routeros_password", ""),
            getattr(self.settings, "telegram_token", ""),
            *extra_secrets,
        ]
        return sanitize_exception_text(exc, *(secret for secret in secrets if secret))

    def menu_view(self, *, chat_id: str, user_id: str, now: int, telegram_token: str = "") -> Any:
        if not self._enabled():
            return build_parental_view([])
        try:
            states = [self.policy.get_state(device) for device in self.policy.list_devices()]
            return build_parental_view(states)
        except Exception as exc:
            self.log(f"Parental state failed: {self._safe_error(exc, telegram_token)}")
            return build_parental_error_view(mutation=False)

    def handle_callback(self, *, callback: dict[str, Any], auth: BotAuth, answer_callback: Callable[[str, str, bool], Any], send_message: Callable[..., Any], edit_message: Callable[..., Any], telegram_token: str, timeout: int, now: int) -> bool:
        data = str(callback.get("data", ""))
        if not data.startswith("parental:v1:"):
            return False
        callback_id = str(callback.get("id", ""))
        message = callback.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id", ""))
        user_id = str((callback.get("from") or {}).get("id", ""))
        if not auth.can_write(chat_id) or not self._enabled():
            answer_callback(callback_id, "Unauthorized", True)
            return True
        parts = data.split(":")
        action = parts[2] if len(parts) > 2 else ""
        if action == "refresh":
            answer_callback(callback_id, "", False)
            return self._render(self.menu_view(chat_id=chat_id, user_id=user_id, now=now, telegram_token=telegram_token), callback, edit_message, send_message, telegram_token, chat_id, timeout)
        if action == "youtube" and len(parts) >= 5 and parts[3] == "request":
            try:
                index, wanted = int(parts[4]), parts[5]
                devices = self.policy.list_devices()
                device = devices[index]
                state = self.policy.get_state(device)
            except Exception as exc:
                answer_callback(callback_id, "Устройство недоступно", True)
                self.log(f"Parental request failed: {self._safe_error(exc, telegram_token)}")
                return True
            if wanted not in {"block", "allow"}:
                answer_callback(callback_id, "Недопустимое действие", True)
                return True
            token = self.token_factory()
            state_data = self._read()
            state_data[token] = {"ip": device.ip, "action": wanted, "chat_id": chat_id, "user_id": user_id, "expires_at": int(now) + max(1, int(self.settings.parental_action_ttl_seconds))}
            self._write(state_data)
            answer_callback(callback_id, "", False)
            return self._render(build_parental_confirmation(device, wanted, token), callback, edit_message, send_message, telegram_token, chat_id, timeout)
        if action == "youtube" and len(parts) >= 4 and parts[3] in {"confirm", "cancel"}:
            token = parts[4] if len(parts) > 4 else ""
            state_data = self._read()
            payload = state_data.pop(token, None)
            self._write(state_data)
            if not payload or int(payload.get("expires_at", 0)) <= int(now) or str(payload.get("chat_id")) != chat_id or str(payload.get("user_id")) != user_id:
                answer_callback(callback_id, "Токен недействителен или истёк", True)
                return True
            if parts[3] == "cancel":
                answer_callback(callback_id, "Отменено", False)
                return self._render(self.menu_view(chat_id=chat_id, user_id=user_id, now=now, telegram_token=telegram_token), callback, edit_message, send_message, telegram_token, chat_id, timeout)
            answer_callback(callback_id, "Применяю политику...", False)
            device = None
            try:
                device = next(item for item in self.policy.list_devices() if item.ip == payload["ip"])
                self.policy.block(device) if payload["action"] == "block" else self.policy.allow(device)
                self.audit.record(f"parental.youtube.{payload['action']}", "success", chat_id, user_id, device.ip, f"group={self.settings.parental_youtube_group_name}")
            except Exception as exc:
                try:
                    self.audit.record(f"parental.youtube.{payload['action']}", "error", chat_id, user_id, payload["ip"], type(exc).__name__)
                except Exception as audit_exc:
                    self.log(f"Parental audit failed: {self._safe_error(audit_exc, telegram_token)}")
                self.log(f"Parental action failed: {self._safe_error(exc, telegram_token)}")
                return self._render(build_parental_error_view(mutation=True, device=device, ip=payload["ip"]), callback, edit_message, send_message, telegram_token, chat_id, timeout)
            return self._render(self.menu_view(chat_id=chat_id, user_id=user_id, now=now, telegram_token=telegram_token), callback, edit_message, send_message, telegram_token, chat_id, timeout)
        return False

    @staticmethod
    def _render(view: Any, callback: dict[str, Any], edit_message: Callable[..., Any], send_message: Callable[..., Any], token: str, chat_id: str, timeout: int) -> bool:
        message_id = ((callback.get("message") or {}).get("message_id"))
        if message_id not in (None, ""):
            response = edit_message(token=token, chat_id=chat_id, message_id=message_id, text=view.text, reply_markup=view.reply_markup, timeout=timeout)
            raise_for_retryable_delivery(response)
            if getattr(response, "ok", True) is not False:
                return True
        response = send_message(token=token, chat_id=chat_id, text=view.text, reply_markup=view.reply_markup, timeout=timeout)
        raise_for_retryable_delivery(response)
        return True


__all__ = ["TelegramParentalHandler"]
