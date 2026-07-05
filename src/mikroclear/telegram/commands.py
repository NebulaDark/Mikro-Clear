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


__all__ = ["process_message_command"]
