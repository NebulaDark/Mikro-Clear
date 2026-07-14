"""Telegram command boundary helpers."""

from __future__ import annotations

from typing import Any, Callable

from mikroclear.telegram.formatting import escape_html_safe
from mikroclear.telegram.unblock import build_unblock_confirm_keyboard


class RetryableTelegramDeliveryError(RuntimeError):
    """Signal a temporary response delivery failure to the polling lifecycle."""


def process_message_command(
    *,
    text: str,
    chat_id: str,
    auth: Any,
    status_snapshot_factory: Callable[[], Any],
    dispatch_message: Callable[[str, str, Any, Callable[[], Any]], Any],
    send_message: Callable[..., Any],
    token: str,
    timeout: int,
    log: Callable[[str], None],
) -> bool:
    result = dispatch_message(text, chat_id, auth, status_snapshot_factory)
    if result is None:
        return False

    if result.alert and result.text == "Unauthorized":
        log(f"Rejected Telegram command from unauthorized chat {chat_id}")
        return True

    response = send_message(
        token=token,
        chat_id=chat_id,
        text=result.text,
        timeout=timeout,
    )
    if getattr(response, "ok", True) is False:
        response_text = str(getattr(response, "response_text", "")).strip()
        if getattr(response, "retryable", False):
            raise RetryableTelegramDeliveryError(
                response_text or "temporary Telegram delivery failure"
            )
        if response_text:
            log(f"Failed to send Telegram command response to chat {chat_id}: {response_text}")
        else:
            log(f"Failed to send Telegram command response to chat {chat_id}")
    return True


def process_callback_update(
    *,
    callback: dict[str, Any],
    allowed_chat_id: str,
    state_file: Any,
    now: int,
    parse_unblock_callback: Callable[[Any], str | None],
    consume_unblock_token: Callable[..., Any],
    handle_unblock_action: Callable[[dict[str, Any]], Any],
    answer_callback: Callable[[str, str, bool], None],
    send_system_notification: Callable[[str, str], Any],
    log: Callable[[str], None],
    peek_unblock_token: Callable[..., Any] | None = None,
    cancel_unblock_token: Callable[..., Any] | None = None,
    send_message: Callable[..., Any] | None = None,
    telegram_token: str = "",
    telegram_timeout: int = 10,
) -> bool:
    callback_id = str(callback.get("id", ""))
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    if chat_id != str(allowed_chat_id):
        answer_callback(callback_id, "Unauthorized chat", True)
        log(f"Rejected Telegram callback from unauthorized chat {chat_id}")
        return True

    parsed = parse_unblock_callback(callback.get("data"))
    if not parsed:
        return False

    if isinstance(parsed, tuple):
        action_name, token = parsed
    else:
        action_name, token = "execute", parsed

    if action_name == "confirm":
        if peek_unblock_token is None or send_message is None:
            answer_callback(callback_id, "Confirm step unavailable", True)
            log("TELEGRAM UNBLOCK CONFIRM UNAVAILABLE: callback dependencies missing")
            return True

        action = peek_unblock_token(state_file, token, now=now)
        if not action:
            answer_callback(callback_id, "Unblock request expired or already used", True)
            log("TELEGRAM UNBLOCK EXPIRED: callback token expired or already used")
            return True

        wanted_ip = str(action.get("wanted_ip", "N/A"))
        send_message(
            token=telegram_token,
            chat_id=chat_id,
            text=f"Confirm unblock?\n\nTarget: <code>{escape_html_safe(wanted_ip)}</code>",
            reply_markup=build_unblock_confirm_keyboard(token),
            timeout=telegram_timeout,
        )
        answer_callback(callback_id, "Confirm unblock in chat", False)
        return True

    if action_name == "cancel":
        if cancel_unblock_token is None:
            answer_callback(callback_id, "Cancel unavailable", True)
            log("TELEGRAM UNBLOCK CANCEL UNAVAILABLE: callback dependencies missing")
            return True
        if cancel_unblock_token(state_file, token, now=now):
            answer_callback(callback_id, "Unblock cancelled", False)
        else:
            answer_callback(callback_id, "Unblock request expired or already used", True)
            log("TELEGRAM UNBLOCK EXPIRED: callback token expired or already used")
        return True

    if action_name != "execute":
        return False

    action = consume_unblock_token(state_file, token, now=now)
    if not action:
        answer_callback(callback_id, "Unblock request expired or already used", True)
        log("TELEGRAM UNBLOCK EXPIRED: callback token expired or already used")
        return True

    result = handle_unblock_action(action)
    answer_callback(callback_id, result.text, result.alert)
    if result.success:
        send_system_notification(result.text, "UNBLOCK")
    return True


__all__ = [
    "RetryableTelegramDeliveryError",
    "process_callback_update",
    "process_message_command",
]
