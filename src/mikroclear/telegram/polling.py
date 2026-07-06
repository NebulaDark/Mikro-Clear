from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.dispatcher import dispatch_message
from mikroclear.bot.settings import BotSettings
from mikroclear.security import mask_known_secret, sanitize_exception_text
from mikroclear.telegram.commands import process_callback_update, process_message_command
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
        if (
            not self.settings.enable_telegram
            or not self.settings.telegram_token
            or not self.settings.telegram_chatid
        ):
            return

        current_time = self.now()
        if not self.backoff.should_poll(current_time):
            return

        try:
            response = self.http_get(
                f"https://api.telegram.org/bot{self.settings.telegram_token}/getUpdates",
                params={
                    "offset": self.update_offset,
                    "timeout": 0,
                    "allowed_updates": ujson.dumps(["callback_query", "message"]),
                },
                timeout=self.settings.telegram_timeout,
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

        for update in body.get("result", []):
            update_id = int(update.get("update_id", 0))
            self.update_offset = max(self.update_offset, update_id + 1)
            if self._process_message(update):
                continue
            self._process_callback(update)

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
        auth = BotAuth(BotSettings.from_env(), legacy_chat_id=str(self.settings.telegram_chatid))
        if self.mangle_handler is not None and self.mangle_handler.handle_message(
            text=message_update.get("text", ""),
            chat_id=chat_id,
            user_id=user_id,
            auth=auth,
            send_message=self.send_message,
            token=self.settings.telegram_token,
            timeout=self.settings.telegram_timeout,
        ):
            return True
        return process_message_command(
            text=message_update.get("text", ""),
            chat_id=chat_id,
            auth=auth,
            status_snapshot_factory=self.status_snapshot_factory,
            dispatch_message=dispatch_message,
            send_message=self.send_message,
            token=self.settings.telegram_token,
            timeout=self.settings.telegram_timeout,
            log=self.log,
        )

    def _process_callback(self, update: dict[str, Any]) -> bool:
        callback = update.get("callback_query") or {}
        if not callback:
            return False

        auth = BotAuth(BotSettings.from_env(), legacy_chat_id=str(self.settings.telegram_chatid))
        if self.mangle_handler is not None and self.mangle_handler.handle_callback(
            callback=callback,
            auth=auth,
            answer_callback=self.answer_callback,
            send_message=self.send_message,
            telegram_token=self.settings.telegram_token,
            timeout=self.settings.telegram_timeout,
            now=int(self.now()),
        ):
            return True

        from mikroclear.telegram.unblock import consume_unblock_token, parse_unblock_callback

        return process_callback_update(
            callback=callback,
            allowed_chat_id=str(self.settings.telegram_chatid),
            state_file=Path(self.settings.telegram_unblock_state_file),
            now=int(self.now()),
            parse_unblock_callback=parse_unblock_callback,
            consume_unblock_token=consume_unblock_token,
            handle_unblock_action=self.handle_unblock_action,
            answer_callback=self.answer_callback,
            send_system_notification=self.send_system_notification,
            log=self.log,
        )


__all__ = ["TelegramPollingBackoff", "TelegramUpdatePoller"]
