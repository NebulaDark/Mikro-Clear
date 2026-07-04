from unittest import TestCase


class ProjectStructureTests(TestCase):
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
