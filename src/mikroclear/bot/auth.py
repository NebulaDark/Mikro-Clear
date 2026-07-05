"""Authorization helpers for Telegram bot actions."""

from dataclasses import dataclass
from typing import Any

from mikroclear.bot.settings import BotSettings


@dataclass(frozen=True)
class BotAuth:
    settings: BotSettings
    legacy_chat_id: str = ""

    def _chat_id(self, chat_id: Any) -> str:
        return str(chat_id).strip()

    def can_read(self, chat_id: Any) -> bool:
        value = self._chat_id(chat_id)
        if not value:
            return False
        if value in self.settings.admin_chat_ids:
            return True
        if value in self.settings.allowed_chat_ids:
            return True
        return bool(self.legacy_chat_id and value == str(self.legacy_chat_id))

    def can_write(self, chat_id: Any) -> bool:
        value = self._chat_id(chat_id)
        return bool(value and value in self.settings.admin_chat_ids)


__all__ = ["BotAuth"]
