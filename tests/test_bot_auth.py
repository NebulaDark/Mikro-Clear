from unittest import TestCase

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.settings import BotSettings


class BotAuthTests(TestCase):
    def test_admin_can_read_and_write(self):
        auth = BotAuth(BotSettings(admin_chat_ids=("admin",), allowed_chat_ids=("reader",)))

        self.assertTrue(auth.can_read("admin"))
        self.assertTrue(auth.can_write("admin"))

    def test_allowed_chat_can_read_but_not_write(self):
        auth = BotAuth(BotSettings(admin_chat_ids=("admin",), allowed_chat_ids=("reader",)))

        self.assertTrue(auth.can_read("reader"))
        self.assertFalse(auth.can_write("reader"))

    def test_unknown_chat_cannot_read_or_write(self):
        auth = BotAuth(BotSettings(admin_chat_ids=("admin",), allowed_chat_ids=("reader",)))

        self.assertFalse(auth.can_read("unknown"))
        self.assertFalse(auth.can_write("unknown"))

    def test_legacy_telegram_chat_is_allowed_for_read(self):
        auth = BotAuth(BotSettings(), legacy_chat_id="legacy-chat")

        self.assertTrue(auth.can_read("legacy-chat"))
        self.assertFalse(auth.can_write("legacy-chat"))
