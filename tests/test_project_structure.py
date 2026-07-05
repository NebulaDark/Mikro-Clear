from unittest import TestCase
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectStructureTests(TestCase):
    def test_runtime_skeleton_modules_are_importable(self):
        import mikroclear.alert_processor
        import mikroclear.app
        import mikroclear.asset_resolver
        import mikroclear.bot.auth
        import mikroclear.bot.dispatcher
        import mikroclear.bot.modules.status
        import mikroclear.bot.settings
        import mikroclear.eve_watcher
        import mikroclear.logging
        import mikroclear.runtime
        import mikroclear.settings
        import mikroclear.state_store

        self.assertEqual(mikroclear.app.__all__, ["build_service", "main"])
        self.assertEqual(mikroclear.settings.__all__, ["Settings", "load_settings"])

    def test_suricata_import_paths_preserve_alert_logic_identity(self):
        from mikroclear import alert_logic as legacy_alert_logic
        from mikroclear.suricata import alert_logic

        self.assertIs(alert_logic.AlertDecision, legacy_alert_logic.AlertDecision)
        self.assertIs(alert_logic.is_ip_in_whitelist, legacy_alert_logic.is_ip_in_whitelist)

    def test_suricata_import_paths_preserve_events_identity(self):
        from mikroclear import events as legacy_events
        from mikroclear.suricata import events

        self.assertIs(events.EventFilterDecision, legacy_events.EventFilterDecision)
        self.assertIs(events.validate_event, legacy_events.validate_event)

    def test_routeros_import_paths_preserve_client_identity(self):
        from mikroclear import routeros_client as legacy_client
        from mikroclear.routeros import client
        from mikroclear.routeros import address_list

        self.assertIs(client.RouterOsConnectionManager, legacy_client.RouterOsConnectionManager)
        self.assertIs(address_list.add_to_address_list, legacy_client.add_to_address_list)
        self.assertIs(address_list.remove_from_address_list, legacy_client.remove_from_address_list)

    def test_routeros_import_paths_preserve_tls_identity(self):
        from mikroclear import routeros_tls as legacy_tls
        from mikroclear.routeros import tls

        self.assertIs(tls.build_routeros_ssl_context, legacy_tls.build_routeros_ssl_context)
        self.assertIs(tls.make_routeros_ssl_wrapper, legacy_tls.make_routeros_ssl_wrapper)

    def test_telegram_import_paths_preserve_identity(self):
        from mikroclear import telegram_notify as legacy_notify
        from mikroclear import telegram_polling as legacy_polling
        from mikroclear import telegram_unblock as legacy_unblock
        from mikroclear.telegram import notify
        from mikroclear.telegram import polling
        from mikroclear.telegram import unblock

        self.assertIs(notify.TelegramSendResult, legacy_notify.TelegramSendResult)
        self.assertIs(notify.format_system_message, legacy_notify.format_system_message)
        self.assertIs(polling.TelegramPollingBackoff, legacy_polling.TelegramPollingBackoff)
        self.assertIs(unblock.create_unblock_token, legacy_unblock.create_unblock_token)

    def test_canonical_modules_do_not_import_old_top_level_shims(self):
        forbidden = {
            "src/mikroclear/assets/resolver.py": ("mikroclear.asset_resolver",),
            "src/mikroclear/state/files.py": ("mikroclear.state_store",),
            "src/mikroclear/state/address_list_store.py": ("mikroclear.state_store",),
            "src/mikroclear/state/uptime.py": ("mikroclear.state_store",),
            "src/mikroclear/suricata/eve_tailer.py": ("mikroclear.eve_watcher",),
            "src/mikroclear/telegram/formatting.py": ("mikroclear.telegram.notify",),
            "src/mikroclear/routeros/address_list.py": ("mikroclear.routeros.client",),
        }

        failures = []
        for relative, forbidden_imports in forbidden.items():
            text = (ROOT / relative).read_text(encoding="utf-8")
            for forbidden_import in forbidden_imports:
                if forbidden_import in text:
                    failures.append(f"{relative} imports {forbidden_import}")

        self.assertEqual(failures, [])

    def test_top_level_modules_are_thin_compatibility_shims(self):
        shim_paths = [
            "src/mikroclear/asset_resolver.py",
            "src/mikroclear/state_store.py",
            "src/mikroclear/eve_watcher.py",
            "src/mikroclear/telegram_notify.py",
            "src/mikroclear/telegram_polling.py",
            "src/mikroclear/telegram_unblock.py",
            "src/mikroclear/routeros_client.py",
            "src/mikroclear/routeros_tls.py",
            "src/mikroclear/alert_logic.py",
            "src/mikroclear/events.py",
        ]

        oversized = []
        for relative in shim_paths:
            lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
            if len(lines) > 80:
                oversized.append(f"{relative}: {len(lines)} lines")

        self.assertEqual(oversized, [])
