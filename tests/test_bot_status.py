from unittest import TestCase

from mikroclear.bot.modules.status import StatusSnapshot, format_status
from mikroclear.bot.settings import BotSettings


class BotStatusTests(TestCase):
    def test_format_status_contains_operational_fields(self):
        snapshot = StatusSnapshot(
            uptime_seconds=3661,
            routeros_connected=True,
            routeros_connected_seconds=61,
            eve_path="/var/log/eve.json",
            block_list_name="Suricata",
            monitor_only=False,
            telegram_unblock_enabled=True,
            state_dir="/var/lib/mikroclear",
            bot_settings=BotSettings(dry_run=True, modules=("status", "asset_resolver")),
        )

        text = format_status(snapshot)

        self.assertIn("Mikro-Clear status", text)
        self.assertIn("uptime: 1h 1m 1s", text)
        self.assertIn("routeros: connected for 1m 1s", text)
        self.assertIn("eve: /var/log/eve.json", text)
        self.assertIn("address-list: Suricata", text)
        self.assertIn("monitor-only: off", text)
        self.assertIn("bot dry-run: on", text)
        self.assertIn("modules: status, asset_resolver", text)

    def test_format_status_masks_secret_like_values(self):
        snapshot = StatusSnapshot(
            uptime_seconds=0,
            routeros_connected=False,
            routeros_connected_seconds=0,
            eve_path="/tmp/bot123456:ABC_def-123/eve.json",
            block_list_name="token=abc123",
            monitor_only=True,
            telegram_unblock_enabled=False,
            state_dir="/var/lib/mikroclear",
            bot_settings=BotSettings(),
        )

        text = format_status(snapshot)

        self.assertNotIn("ABC_def-123", text)
        self.assertIn("/bot***MASKED***/", text)
        self.assertIn("token=abc123", text)
