"""Telegram message dispatcher for Mikro-Clear bot commands."""

from dataclasses import dataclass
from typing import Any, Callable

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.modules.status import StatusSnapshot, format_status


@dataclass(frozen=True)
class BotCommandResult:
    text: str
    handled: bool = True
    alert: bool = False


def _command_name(text: Any) -> str:
    value = str(text or "").strip()
    if not value.startswith("/"):
        return ""
    return value.split()[0].split("@", 1)[0].lower()


def dispatch_message(
    text: Any,
    chat_id: Any,
    auth: BotAuth,
    status_snapshot: Callable[[], StatusSnapshot],
) -> BotCommandResult | None:
    command = _command_name(text)
    if command != "/status":
        return None
    if not auth.can_read(chat_id):
        return BotCommandResult("Unauthorized", alert=True)
    return BotCommandResult(format_status(status_snapshot()))


__all__ = ["BotCommandResult", "dispatch_message"]
