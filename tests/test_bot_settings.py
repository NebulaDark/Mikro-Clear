import os
from unittest import TestCase
from unittest.mock import patch

from mikroclear.bot.settings import BotSettings, parse_chat_ids


class BotSettingsTests(TestCase):
    def test_parse_chat_ids_trims_and_drops_empty_values(self):
        self.assertEqual(parse_chat_ids(" 10,20,, 30 "), ("10", "20", "30"))

    def test_defaults_are_safe(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = BotSettings.from_env()

        self.assertFalse(settings.enable)
        self.assertTrue(settings.dry_run)
        self.assertEqual(settings.allowed_chat_ids, ())
        self.assertEqual(settings.admin_chat_ids, ())
        self.assertEqual(settings.modules, ("status", "asset_resolver", "mangle_control", "parental_control"))

    def test_env_overrides(self):
        env = {
            "MIKROCLEAR_BOT_ENABLE": "true",
            "MIKROCLEAR_BOT_DRY_RUN": "false",
            "MIKROCLEAR_BOT_ALLOWED_CHAT_IDS": "chat-1,chat-2",
            "MIKROCLEAR_BOT_ADMIN_CHAT_IDS": "admin-1",
            "MIKROCLEAR_BOT_MODULES": "status,asset_resolver",
            "MIKROCLEAR_BOT_AUDIT_LOG": "/tmp/mikroclear-bot-audit.log",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = BotSettings.from_env()

        self.assertTrue(settings.enable)
        self.assertFalse(settings.dry_run)
        self.assertEqual(settings.allowed_chat_ids, ("chat-1", "chat-2"))
        self.assertEqual(settings.admin_chat_ids, ("admin-1",))
        self.assertEqual(settings.modules, ("status", "asset_resolver"))
        self.assertEqual(settings.audit_log, "/tmp/mikroclear-bot-audit.log")
