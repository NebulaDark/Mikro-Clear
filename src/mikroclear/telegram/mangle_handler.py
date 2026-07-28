"""Telegram command and callback handling for RouterOS mangle control."""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
from time import time
from typing import Any, Callable

from mikroclear.bot.audit import BotAuditLog
from mikroclear.bot.mangle_control import (
    build_mangle_confirm_keyboard,
    build_mangle_control_keyboard,
    build_mangle_status_keyboard,
    format_mangle_status,
)
from mikroclear.bot.menu import MenuView
from mikroclear.bot.settings import BotSettings
from mikroclear.routeros.mangle import get_managed_mangle_rule, list_managed_mangle_rules, set_mangle_rule_disabled
from mikroclear.security import mask_known_secret, sanitize_exception_text
from mikroclear.telegram.commands import (
    RetryableTelegramDeliveryError,
    raise_for_retryable_delivery,
)


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
        bot_settings: BotSettings | None = None,
        audit: BotAuditLog | None = None,
        now: Callable[[], float] = time,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.settings = settings
        self.bot_settings = bot_settings or BotSettings.from_env()
        self.audit = audit or BotAuditLog(Path(self.bot_settings.audit_log))
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
        source_update_id: str = "",
    ) -> str:
        current = int(self.now() if now is None else now)
        state = _read_state(self.state_file)
        if source_update_id:
            for existing_token, payload in state.items():
                if (
                    str(payload.get("source_update_id", "")) == source_update_id
                    and str(payload.get("rule_id", "")) == str(rule_id)
                    and str(payload.get("action", "")) == str(action)
                    and str(payload.get("requester_chat_id", "")) == str(requester_chat_id)
                    and str(payload.get("requester_user_id", "")) == str(requester_user_id)
                    and int(payload.get("expires_at", 0)) > current
                ):
                    return existing_token

        token = self.token_factory()
        state[token] = {
            "rule_id": str(rule_id),
            "action": str(action),
            "created_at": current,
            "expires_at": current + max(1, int(ttl_seconds)),
            "requester_chat_id": str(requester_chat_id),
            "requester_user_id": str(requester_user_id),
        }
        if source_update_id:
            state[token]["source_update_id"] = source_update_id
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

    def _read_rules(self) -> list[Any]:
        client = self.get_router_client()
        return client.run_with_reconnect(
            "telegram mangle read",
            lambda: list_managed_mangle_rules(
                client.ensure_connected(),
                self.settings,
            ),
        )

    def _read_rule(self, rule_id: str) -> Any:
        client = self.get_router_client()
        return client.run_with_reconnect(
            "telegram mangle read",
            lambda: get_managed_mangle_rule(
                client.ensure_connected(),
                rule_id,
                self.settings,
            ),
        )

    def control_view(
        self,
        *,
        chat_id: str,
        user_id: str,
        update_id: str = "",
    ) -> MenuView:
        rules = self._read_rules()
        self.log(
            f"Telegram /mangle managed rules: {len(rules)} for chat {chat_id}"
        )
        return MenuView(
            "<b>Mangle</b>",
            build_mangle_control_keyboard(
                rules,
                token_factory=lambda rule, action: self.create_action_token(
                    rule.rule_id,
                    action,
                    chat_id,
                    user_id,
                    now=int(self.now()),
                    source_update_id=update_id,
                ),
            ),
        )

    def status_view(self) -> MenuView:
        rules = self._read_rules()
        return MenuView(
            format_mangle_status(rules),
            build_mangle_status_keyboard(),
        )

    def _send_status(
        self,
        *,
        send_message: Callable[..., Any],
        chat_id: str,
        user_id: str,
        token: str,
        timeout: int,
        update_id: str = "",
    ) -> None:
        view = self.control_view(
            chat_id=chat_id,
            user_id=user_id,
            update_id=update_id,
        )
        result = send_message(
            token=token,
            chat_id=chat_id,
            text=view.text,
            reply_markup=view.reply_markup,
            timeout=timeout,
        )
        if getattr(result, "ok", True) is False:
            response_text = mask_known_secret(str(getattr(result, "response_text", "")), token)
            self.log(f"TELEGRAM MANGLE STATUS SEND FAILED: {response_text}")

    @staticmethod
    def _edit_or_send_view(
        view: MenuView,
        *,
        message_id: Any,
        edit_message: Callable[..., Any] | None,
        send_message: Callable[..., Any],
        token: str,
        chat_id: str,
        timeout: int,
    ) -> Any:
        if edit_message is not None and message_id not in (None, ""):
            response = edit_message(
                token=token,
                chat_id=chat_id,
                message_id=message_id,
                text=view.text,
                reply_markup=view.reply_markup,
                timeout=timeout,
            )
            raise_for_retryable_delivery(response)
            if getattr(response, "ok", True) is not False:
                return response
        response = send_message(
            token=token,
            chat_id=chat_id,
            text=view.text,
            reply_markup=view.reply_markup,
            timeout=timeout,
        )
        raise_for_retryable_delivery(response)
        return response

    def _record_audit(
        self,
        outcome: str,
        chat_id: str,
        user_id: str,
        target: str = "",
        detail: str = "",
    ) -> None:
        if self.audit is not None:
            self.audit.record(
                "mangle.change",
                outcome,
                chat_id,
                user_id,
                target,
                detail,
            )

    def _payload_matches_requester(self, payload: dict[str, Any], chat_id: str, user_id: str) -> bool:
        return (
            str(payload.get("requester_chat_id", "")) == str(chat_id)
            and str(payload.get("requester_user_id", "")) == str(user_id)
        )

    def _apply_change(
        self,
        payload: dict[str, Any],
        *,
        callback_id: str,
        message_id: Any,
        chat_id: str,
        user_id: str,
        answer_callback: Callable[[str, str, bool], None],
        send_message: Callable[..., Any],
        edit_message: Callable[..., Any] | None,
        telegram_token: str,
        timeout: int,
        update_id: str,
    ) -> None:
        rule_id = str(payload.get("rule_id", ""))
        action = str(payload.get("action", ""))
        try:
            rule = self._read_rule(rule_id)
        except Exception as exc:
            self.log(
                "TELEGRAM MANGLE READ BEFORE UPDATE FAILED: "
                f"{type(exc).__name__}"
            )
            self._record_audit("failure", chat_id, user_id, rule_id, action)
            answer_callback(callback_id, "Could not update mangle rule", True)
            return
        if rule is None:
            self._record_audit("stale", chat_id, user_id, rule_id, action)
            answer_callback(
                callback_id,
                "Mangle rule is no longer managed",
                True,
            )
            return

        self._record_audit("attempted", chat_id, user_id, rule_id, action)
        if self.bot_settings.dry_run:
            self._record_audit("dry-run", chat_id, user_id, rule_id, action)
            answer_text = "Dry-run: no change applied"
        else:
            disabled = action == "disable"
            try:
                client = self.get_router_client()
                client.run_with_reconnect(
                    "telegram mangle control",
                    lambda: set_mangle_rule_disabled(
                        client.ensure_connected(),
                        rule_id,
                        disabled,
                        self.settings,
                    ),
                )
            except Exception as exc:
                self.log(
                    f"TELEGRAM MANGLE UPDATE FAILED: {type(exc).__name__}"
                )
                self._record_audit(
                    "failure",
                    chat_id,
                    user_id,
                    rule_id,
                    action,
                )
                answer_callback(
                    callback_id,
                    "Could not update mangle rule",
                    True,
                )
                return
            self._record_audit("success", chat_id, user_id, rule_id, action)
            answer_text = "Mangle rule updated"

        try:
            view = self.control_view(
                chat_id=chat_id,
                user_id=user_id,
                update_id=update_id,
            )
            self._edit_or_send_view(
                view,
                message_id=message_id,
                edit_message=edit_message,
                send_message=send_message,
                token=telegram_token,
                chat_id=chat_id,
                timeout=timeout,
            )
        except Exception as exc:
            self.log(
                "TELEGRAM MANGLE POST-WRITE STATUS FAILED: "
                f"{sanitize_exception_text(exc, self.settings.telegram_token)}"
            )
        answer_callback(callback_id, answer_text, False)

    def handle_message(
        self,
        *,
        text: Any,
        chat_id: str,
        user_id: str = "",
        auth: Any,
        send_message: Callable[..., Any],
        token: str,
        timeout: int,
        update_id: str = "",
    ) -> bool:
        if _command_name(text) != "/mangle":
            return False
        self.log(f"Telegram /mangle received from chat {chat_id}")
        if not auth.can_read(chat_id):
            self.log(f"Rejected Telegram /mangle from unauthorized chat {chat_id}")
            return True
        if not self.settings.mangle_control_enable:
            send_message(token=token, chat_id=chat_id, text="Mangle control is disabled", timeout=timeout)
            return True
        try:
            self._send_status(send_message=send_message, chat_id=chat_id, user_id=user_id, token=token, timeout=timeout, update_id=update_id)
        except RetryableTelegramDeliveryError:
            raise
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
        edit_message: Callable[..., Any] | None = None,
        update_id: str = "",
    ) -> bool:
        data = str(callback.get("data", ""))
        if not data.startswith("mangle:"):
            return False

        callback_id = str(callback.get("id", ""))
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        message_id = message.get("message_id")
        user = callback.get("from") or {}
        user_id = str(user.get("id", ""))

        if not auth.can_write(chat_id):
            self._record_audit(
                "denied",
                chat_id,
                user_id,
                "",
                data.split(":", 2)[1] if ":" in data else "",
            )
            answer_callback(callback_id, "Unauthorized", True)
            self.log(f"Rejected Telegram mangle callback from unauthorized chat {chat_id}")
            return True
        if not self.settings.mangle_control_enable:
            answer_callback(callback_id, "Mangle control is disabled", True)
            return True

        parts = data.split(":", 2)
        action_name = parts[1] if len(parts) > 1 else ""
        action_token = parts[2] if len(parts) > 2 else ""

        if action_name == "refresh":
            try:
                view = self.control_view(
                    chat_id=chat_id,
                    user_id=user_id,
                    update_id=update_id,
                )
                self._edit_or_send_view(
                    view,
                    message_id=message_id,
                    edit_message=edit_message,
                    send_message=send_message,
                    token=telegram_token,
                    chat_id=chat_id,
                    timeout=timeout,
                )
            except RetryableTelegramDeliveryError:
                raise
            except Exception as exc:
                self.log(
                    "TELEGRAM MANGLE REFRESH FAILED: "
                    f"{sanitize_exception_text(exc, self.settings.telegram_token)}"
                )
                answer_callback(
                    callback_id,
                    "Could not read mangle rules",
                    True,
                )
                return True
            answer_callback(callback_id, "Mangle status refreshed", False)
            return True

        if action_name == "request":
            payload = self._peek_token(action_token, now=now)
            if not payload:
                self._record_audit("stale", chat_id, user_id)
                answer_callback(callback_id, "Mangle request expired or already used", True)
                return True
            if not self._payload_matches_requester(payload, chat_id, user_id):
                self._record_audit(
                    "denied",
                    chat_id,
                    user_id,
                    str(payload.get("rule_id", "")),
                    str(payload.get("action", "")),
                )
                answer_callback(callback_id, "Unauthorized", True)
                return True
            if not self.settings.mangle_require_confirmation:
                payload = self._consume_token(action_token, now=now)
                if not payload:
                    self._record_audit("stale", chat_id, user_id)
                    answer_callback(
                        callback_id,
                        "Mangle request expired or already used",
                        True,
                    )
                    return True
                self._apply_change(
                    payload,
                    callback_id=callback_id,
                    message_id=message_id,
                    chat_id=chat_id,
                    user_id=user_id,
                    answer_callback=answer_callback,
                    send_message=send_message,
                    edit_message=edit_message,
                    telegram_token=telegram_token,
                    timeout=timeout,
                    update_id=update_id,
                )
                return True
            rule = self._read_rule(str(payload.get("rule_id", "")))
            if rule is None:
                self._record_audit(
                    "stale",
                    chat_id,
                    user_id,
                    str(payload.get("rule_id", "")),
                    str(payload.get("action", "")),
                )
                answer_callback(callback_id, "Mangle rule is no longer managed", True)
                return True
            label = "Enable" if payload.get("action") == "enable" else "Disable"
            self._edit_or_send_view(
                MenuView(
                    f"Confirm mangle change?\n\nRule: {rule.name}\nAction: {label}",
                    build_mangle_confirm_keyboard(action_token),
                ),
                message_id=message_id,
                edit_message=edit_message,
                send_message=send_message,
                token=telegram_token,
                chat_id=chat_id,
                timeout=timeout,
            )
            answer_callback(callback_id, "Confirm mangle change in chat", False)
            return True

        if action_name == "cancel":
            payload = self._peek_token(action_token, now=now)
            if not payload:
                self._record_audit("stale", chat_id, user_id)
                answer_callback(callback_id, "Mangle request expired or already used", True)
            elif not self._payload_matches_requester(payload, chat_id, user_id):
                self._record_audit(
                    "denied",
                    chat_id,
                    user_id,
                    str(payload.get("rule_id", "")),
                    str(payload.get("action", "")),
                )
                answer_callback(callback_id, "Unauthorized", True)
            elif self._cancel_token(action_token, now=now):
                self._record_audit(
                    "cancelled",
                    chat_id,
                    user_id,
                    str(payload.get("rule_id", "")),
                    str(payload.get("action", "")),
                )
                view = self.control_view(
                    chat_id=chat_id,
                    user_id=user_id,
                    update_id=update_id,
                )
                self._edit_or_send_view(
                    view,
                    message_id=message_id,
                    edit_message=edit_message,
                    send_message=send_message,
                    token=telegram_token,
                    chat_id=chat_id,
                    timeout=timeout,
                )
                answer_callback(callback_id, "Mangle change cancelled", False)
            else:
                self._record_audit("stale", chat_id, user_id)
                answer_callback(callback_id, "Mangle request expired or already used", True)
            return True

        if action_name == "confirm":
            payload = self._peek_token(action_token, now=now)
            if not payload:
                self._record_audit("stale", chat_id, user_id)
                answer_callback(callback_id, "Mangle request expired or already used", True)
                return True
            if not self._payload_matches_requester(payload, chat_id, user_id):
                self._record_audit(
                    "denied",
                    chat_id,
                    user_id,
                    str(payload.get("rule_id", "")),
                    str(payload.get("action", "")),
                )
                answer_callback(callback_id, "Unauthorized", True)
                return True
            payload = self._consume_token(action_token, now=now)
            if not payload:
                self._record_audit("stale", chat_id, user_id)
                answer_callback(callback_id, "Mangle request expired or already used", True)
                return True
            self._apply_change(
                payload,
                callback_id=callback_id,
                message_id=message_id,
                chat_id=chat_id,
                user_id=user_id,
                answer_callback=answer_callback,
                send_message=send_message,
                edit_message=edit_message,
                telegram_token=telegram_token,
                timeout=timeout,
                update_id=update_id,
            )
            return True

        return False


__all__ = ["TelegramMangleHandler"]
