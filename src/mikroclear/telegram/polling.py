from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.dispatcher import dispatch_message
from mikroclear.bot.settings import BotSettings
from mikroclear.security import mask_known_secret, sanitize_exception_text
from mikroclear.telegram.commands import (
    process_callback_update,
    process_message_command,
    raise_for_retryable_delivery,
)
from mikroclear.telegram.notify import send_telegram_message

try:
    import ujson  # type: ignore
except Exception:  # pragma: no cover
    import json as ujson  # type: ignore


@dataclass
class TelegramPollingBackoff:
    base_seconds: int = 30
    max_seconds: int = 300
    log_every_seconds: int = 120
    failure_count: int = 0
    next_poll_at: float = 0.0
    last_logged_at: float = 0.0
    last_error_key: str = ""

    def should_poll(self, now: float) -> bool:
        return now >= self.next_poll_at

    def record_success(self, now: float) -> None:
        self.failure_count = 0
        self.next_poll_at = now
        self.last_logged_at = 0.0
        self.last_error_key = ""

    def record_failure(self, now: float, error_key: str) -> tuple[bool, int]:
        delay = min(self.max_seconds, self.base_seconds * (2 ** self.failure_count))
        self.failure_count += 1
        self.next_poll_at = now + delay

        should_log = error_key != self.last_error_key or now - self.last_logged_at >= self.log_every_seconds
        if should_log:
            self.last_logged_at = now
            self.last_error_key = error_key

        return should_log, delay


class TelegramUpdatePoller:
    def __init__(
        self,
        settings: Any,
        *,
        bot_settings: BotSettings | None = None,
        status_snapshot_factory: Callable[[], Any],
        handle_unblock_action: Callable[[dict[str, Any]], Any],
        answer_callback: Callable[[str, str, bool], None],
        send_system_notification: Callable[[str, str], Any],
        log: Callable[[str], None],
        now: Callable[[], float],
        mangle_handler: Any = None,
        http_get: Callable[..., Any] = requests.get,
        send_message: Callable[..., Any] = send_telegram_message,
        backoff: TelegramPollingBackoff | None = None,
    ) -> None:
        self.settings = settings
        self.bot_settings = bot_settings or BotSettings.from_env()
        self.status_snapshot_factory = status_snapshot_factory
        self.handle_unblock_action = handle_unblock_action
        self.answer_callback = answer_callback
        self.send_system_notification = send_system_notification
        self.log = log
        self.now = now
        self.mangle_handler = mangle_handler
        self.http_get = http_get
        self.send_message = send_message
        self.backoff = backoff or TelegramPollingBackoff()
        self.update_offset = 0

    def process_updates(self) -> None:
        updates = self.fetch_updates(long_poll_seconds=0)
        if updates is None:
            return
        for update in updates:
            try:
                self.process_update(update)
            except Exception as exc:
                self._record_failure(
                    sanitize_exception_text(exc, self.settings.telegram_token)
                )
                break
            self.acknowledge_update(update)

    def _enabled(self) -> bool:
        return bool(
            self.settings.enable_telegram
            and self.settings.telegram_token
            and self.settings.telegram_chatid
        )

    def fetch_updates(
        self,
        *,
        long_poll_seconds: int = 0,
    ) -> list[dict[str, Any]] | None:
        if not self._enabled():
            return None
        current_time = self.now()
        if not self.backoff.should_poll(current_time):
            return None
        try:
            response = self.http_get(
                f"https://api.telegram.org/bot{self.settings.telegram_token}/getUpdates",
                params={
                    "offset": self.update_offset,
                    "timeout": long_poll_seconds,
                    "allowed_updates": ujson.dumps(["callback_query", "message"]),
                },
                timeout=max(
                    self.settings.telegram_timeout,
                    long_poll_seconds + 5,
                ),
            )
            if response.status_code != 200:
                error_text = mask_known_secret(
                    f"HTTP {response.status_code}: {response.text[:120]}",
                    self.settings.telegram_token,
                )
                self._record_failure(error_text)
                return

            body = response.json()
            if not body.get("ok"):
                error_text = mask_known_secret(f"not ok: {str(body)[:120]}", self.settings.telegram_token)
                self._record_failure(error_text)
                return
            self.backoff.record_success(self.now())
        except Exception as exc:
            self._record_failure(sanitize_exception_text(exc, self.settings.telegram_token))
            return

        updates = list(body.get("result", []))
        if updates:
            self.log(
                "Telegram updates received: "
                f"{len(updates)} item(s), current offset={self.update_offset}"
            )

        return updates

    def process_update(self, update: dict[str, Any]) -> None:
        if self._process_message(update):
            return
        self._process_callback(update)

    def acknowledge_update(self, update: dict[str, Any]) -> None:
        update_id = int(update["update_id"])
        self.update_offset = max(self.update_offset, update_id + 1)

    def _send_message(self, **kwargs: Any) -> Any:
        response = self.send_message(**kwargs)
        raise_for_retryable_delivery(response)
        return response

    def _answer_callback(self, callback_id: str, text: str, alert: bool) -> Any:
        response = self.answer_callback(callback_id, text, alert)
        raise_for_retryable_delivery(response)
        return response

    def _record_failure(self, error_text: str) -> None:
        should_log, delay = self.backoff.record_failure(self.now(), error_text)
        if should_log:
            self.log(f"Error processing Telegram updates; retry in {delay}s: {error_text}")

    def _process_message(self, update: dict[str, Any]) -> bool:
        message_update = update.get("message") or {}
        if not message_update:
            return False

        chat = message_update.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        user = message_update.get("from") or {}
        user_id = str(user.get("id", ""))
        text = message_update.get("text", "")
        command_name = _command_name(text)
        if command_name:
            self.log(f"Telegram command update: command={command_name} chat={chat_id} user={user_id}")
        auth = BotAuth(self.bot_settings, legacy_chat_id=str(self.settings.telegram_chatid))
        if self.mangle_handler is not None and self.mangle_handler.handle_message(
            text=text,
            chat_id=chat_id,
            user_id=user_id,
            auth=auth,
            send_message=self._send_message,
            token=self.settings.telegram_token,
            timeout=self.settings.telegram_timeout,
        ):
            return True
        return process_message_command(
            text=text,
            chat_id=chat_id,
            auth=auth,
            status_snapshot_factory=self.status_snapshot_factory,
            dispatch_message=dispatch_message,
            send_message=self._send_message,
            token=self.settings.telegram_token,
            timeout=self.settings.telegram_timeout,
            log=self.log,
        )

    def _process_callback(self, update: dict[str, Any]) -> bool:
        callback = update.get("callback_query") or {}
        if not callback:
            return False

        callback_id = str(callback.get("id", ""))
        callback_data = str(callback.get("data", ""))
        callback_action = _callback_action_name(callback_data)
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        user = callback.get("from") or {}
        user_id = str(user.get("id", ""))
        self.log(
            "Telegram callback update: "
            f"id={callback_id} action={callback_action} chat={chat_id} user={user_id}"
        )

        auth = BotAuth(self.bot_settings, legacy_chat_id=str(self.settings.telegram_chatid))
        if self.mangle_handler is not None and self.mangle_handler.handle_callback(
            callback=callback,
            auth=auth,
            answer_callback=self._answer_callback,
            send_message=self._send_message,
            telegram_token=self.settings.telegram_token,
            timeout=self.settings.telegram_timeout,
            now=int(self.now()),
        ):
            return True

        from mikroclear.telegram.unblock import (
            cancel_unblock_token,
            consume_unblock_token,
            parse_unblock_callback,
            peek_unblock_token,
        )

        return process_callback_update(
            callback=callback,
            allowed_chat_id=str(self.settings.telegram_chatid),
            state_file=Path(self.settings.telegram_unblock_state_file),
            now=int(self.now()),
            parse_unblock_callback=parse_unblock_callback,
            consume_unblock_token=consume_unblock_token,
            handle_unblock_action=self.handle_unblock_action,
            answer_callback=self._answer_callback,
            send_system_notification=self.send_system_notification,
            log=self.log,
            peek_unblock_token=peek_unblock_token,
            cancel_unblock_token=cancel_unblock_token,
            send_message=self._send_message,
            telegram_token=self.settings.telegram_token,
            telegram_timeout=self.settings.telegram_timeout,
        )


__all__ = ["TelegramPollingBackoff", "TelegramUpdatePoller"]


def _command_name(text: Any) -> str:
    value = str(text or "").strip()
    if not value.startswith("/"):
        return ""
    return value.split()[0].split("@", 1)[0].lower()


def _callback_action_name(data: Any) -> str:
    value = str(data or "")
    if not value:
        return ""
    parts = value.split(":", 2)
    if len(parts) >= 2:
        return ":".join(parts[:2])
    return value
