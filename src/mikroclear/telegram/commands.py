"""Telegram command boundary helpers."""

from __future__ import annotations

from typing import Any, Callable


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

    send_message(
        token=token,
        chat_id=chat_id,
        text=result.text,
        timeout=timeout,
    )
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
) -> bool:
    callback_id = str(callback.get("id", ""))
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    if chat_id != str(allowed_chat_id):
        answer_callback(callback_id, "Unauthorized chat", True)
        log(f"Rejected Telegram callback from unauthorized chat {chat_id}")
        return True

    token = parse_unblock_callback(callback.get("data"))
    if not token:
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


__all__ = ["process_callback_update", "process_message_command"]
