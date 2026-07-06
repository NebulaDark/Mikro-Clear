"""Telegram command and callback handling for RouterOS mangle control."""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
from time import time
from typing import Any, Callable

from mikroclear.bot.mangle_control import build_mangle_confirm_keyboard, build_mangle_keyboard, format_mangle_status
from mikroclear.routeros.mangle import get_managed_mangle_rule, list_managed_mangle_rules, set_mangle_rule_disabled
from mikroclear.security import sanitize_exception_text


def _command_name(text: Any) -> str:
    value = str(text or "").strip()
    if not value.startswith("/"):
        return ""
    return value.split()[0].split("@", 1)[0].lower()


def _ensure_private_json(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("{}")
    os.chmod(path, 0o600)


def _read_state(path: Path) -> dict[str, dict[str, Any]]:
    _ensure_private_json(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(key): value for key, value in data.items() if isinstance(value, dict)}
    except Exception:
        pass
    return {}


def _write_state(path: Path, state: dict[str, dict[str, Any]]) -> None:
    _ensure_private_json(path)
    path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.chmod(path, 0o600)


class TelegramMangleHandler:
    def __init__(
        self,
        settings: Any,
        *,
        get_router_client: Callable[[], Any],
        log: Callable[[str], None],
        now: Callable[[], float] = time,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.settings = settings
        self.get_router_client = get_router_client
        self.log = log
        self.now = now
        self.token_factory = token_factory or (lambda: secrets.token_urlsafe(12))

    @property
    def state_file(self) -> Path:
        return Path(str(getattr(self.settings, "state_dir", "/var/lib/mikroclear"))) / "telegram-mangle-actions.json"

    def create_action_token(
        self,
        rule_id: str,
        action: str,
        requester_chat_id: str,
        requester_user_id: str,
        *,
        now: int | None = None,
        ttl_seconds: int = 300,
    ) -> str:
        token = self.token_factory()
        current = int(self.now() if now is None else now)
        state = _read_state(self.state_file)
        state[token] = {
            "rule_id": str(rule_id),
            "action": str(action),
            "created_at": current,
            "expires_at": current + max(1, int(ttl_seconds)),
            "requester_chat_id": str(requester_chat_id),
            "requester_user_id": str(requester_user_id),
        }
        _write_state(self.state_file, state)
        return token

    def _consume_token(self, token: str, *, now: int) -> dict[str, Any] | None:
        state = _read_state(self.state_file)
        payload = state.pop(token, None)
        changed = payload is not None
        for key, value in list(state.items()):
            if int(value.get("expires_at", 0)) <= int(now):
                state.pop(key, None)
                changed = True
        if changed:
            _write_state(self.state_file, state)
        if not payload or int(payload.get("expires_at", 0)) <= int(now):
            return None
        return payload

    def _peek_token(self, token: str, *, now: int) -> dict[str, Any] | None:
        state = _read_state(self.state_file)
        payload = state.get(token)
        if not payload or int(payload.get("expires_at", 0)) <= int(now):
            return None
        return dict(payload)

    def _cancel_token(self, token: str, *, now: int) -> bool:
        return self._consume_token(token, now=now) is not None

    def _api(self) -> Any:
        client = self.get_router_client()
        return client.ensure_connected()

    def _send_status(self, *, send_message: Callable[..., Any], chat_id: str, token: str, timeout: int) -> None:
        rules = list_managed_mangle_rules(self._api(), self.settings)
        send_message(
            token=token,
            chat_id=chat_id,
            text=format_mangle_status(rules),
            reply_markup=build_mangle_keyboard(
                rules,
                token_factory=lambda rule, action: self.create_action_token(
                    rule.rule_id,
                    action,
                    chat_id,
                    "",
                    now=int(self.now()),
                ),
            ),
            timeout=timeout,
        )

    def handle_message(
        self,
        *,
        text: Any,
        chat_id: str,
        auth: Any,
        send_message: Callable[..., Any],
        token: str,
        timeout: int,
    ) -> bool:
        if _command_name(text) != "/mangle":
            return False
        if not self.settings.mangle_control_enable:
            return True
        if not auth.can_read(chat_id):
            self.log(f"Rejected Telegram /mangle from unauthorized chat {chat_id}")
            return True
        try:
            self._send_status(send_message=send_message, chat_id=chat_id, token=token, timeout=timeout)
        except Exception as exc:
            self.log(f"TELEGRAM MANGLE STATUS FAILED: {sanitize_exception_text(exc, self.settings.telegram_token)}")
            send_message(token=token, chat_id=chat_id, text="Could not read mangle rules", timeout=timeout)
        return True

    def handle_callback(
        self,
        *,
        callback: dict[str, Any],
        auth: Any,
        answer_callback: Callable[[str, str, bool], None],
        send_message: Callable[..., Any],
        telegram_token: str,
        timeout: int,
        now: int,
    ) -> bool:
        data = str(callback.get("data", ""))
        if not data.startswith("mangle:"):
            return False

        callback_id = str(callback.get("id", ""))
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        user = callback.get("from") or {}
        user_id = str(user.get("id", ""))

        if not auth.can_write(chat_id):
            answer_callback(callback_id, "Unauthorized", True)
            self.log(f"Rejected Telegram mangle callback from unauthorized chat {chat_id}")
            return True

        parts = data.split(":", 2)
        action_name = parts[1] if len(parts) > 1 else ""
        action_token = parts[2] if len(parts) > 2 else ""

        if action_name == "refresh":
            self._send_status(send_message=send_message, chat_id=chat_id, token=telegram_token, timeout=timeout)
            answer_callback(callback_id, "Mangle status refreshed", False)
            return True

        if action_name == "request":
            payload = self._peek_token(action_token, now=now)
            if not payload:
                answer_callback(callback_id, "Mangle request expired or already used", True)
                return True
            if str(payload.get("requester_chat_id", "")) != chat_id:
                answer_callback(callback_id, "Unauthorized", True)
                return True
            rule = get_managed_mangle_rule(self._api(), str(payload.get("rule_id", "")), self.settings)
            if rule is None:
                answer_callback(callback_id, "Mangle rule is no longer managed", True)
                return True
            label = "Enable" if payload.get("action") == "enable" else "Disable"
            send_message(
                token=telegram_token,
                chat_id=chat_id,
                text=f"Confirm mangle change?\n\nRule: {rule.name}\nAction: {label}",
                reply_markup=build_mangle_confirm_keyboard(action_token),
                timeout=timeout,
            )
            answer_callback(callback_id, "Confirm mangle change in chat", False)
            return True

        if action_name == "cancel":
            if self._cancel_token(action_token, now=now):
                answer_callback(callback_id, "Mangle change cancelled", False)
            else:
                answer_callback(callback_id, "Mangle request expired or already used", True)
            return True

        if action_name == "confirm":
            payload = self._consume_token(action_token, now=now)
            if not payload:
                answer_callback(callback_id, "Mangle request expired or already used", True)
                return True
            if str(payload.get("requester_chat_id", "")) != chat_id:
                answer_callback(callback_id, "Unauthorized", True)
                return True
            disabled = payload.get("action") == "disable"
            try:
                client = self.get_router_client()
                client.run_with_reconnect(
                    "telegram mangle control",
                    lambda: set_mangle_rule_disabled(client.ensure_connected(), str(payload.get("rule_id", "")), disabled, self.settings),
                )
                answer_callback(callback_id, "Mangle rule updated", False)
                self._send_status(send_message=send_message, chat_id=chat_id, token=telegram_token, timeout=timeout)
            except Exception as exc:
                self.log(f"TELEGRAM MANGLE UPDATE FAILED: {sanitize_exception_text(exc, self.settings.telegram_token)}")
                answer_callback(callback_id, "Could not update mangle rule", True)
            return True

        return False


__all__ = ["TelegramMangleHandler"]
