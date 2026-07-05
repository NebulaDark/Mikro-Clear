from unittest import TestCase

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.dispatcher import dispatch_message
from mikroclear.bot.modules.status import StatusSnapshot
from mikroclear.bot.settings import BotSettings


def snapshot() -> StatusSnapshot:
    return StatusSnapshot(
        uptime_seconds=1,
        routeros_connected=False,
        routeros_connected_seconds=0,
        eve_path="/var/log/eve.json",
        block_list_name="Suricata",
        monitor_only=True,
        telegram_unblock_enabled=False,
        state_dir="/var/lib/mikroclear",
        bot_settings=BotSettings(modules=("status",)),
    )


class BotDispatcherTests(TestCase):
    def test_dispatches_status_for_allowed_chat(self):
        auth = BotAuth(BotSettings(allowed_chat_ids=("chat-1",)))

        result = dispatch_message("/status", "chat-1", auth, snapshot)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertFalse(result.alert)
        self.assertIn("Mikro-Clear status", result.text)

    def test_rejects_status_for_unknown_chat_without_privileged_data(self):
        auth = BotAuth(BotSettings(allowed_chat_ids=("chat-1",)))

        result = dispatch_message("/status", "unknown", auth, snapshot)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertTrue(result.alert)
        self.assertEqual(result.text, "Unauthorized")

    def test_ignores_unknown_command(self):
        auth = BotAuth(BotSettings(allowed_chat_ids=("chat-1",)))

        self.assertIsNone(dispatch_message("/unknown", "chat-1", auth, snapshot))
