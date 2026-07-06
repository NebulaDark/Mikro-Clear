import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from mikroclear.settings import Settings
from mikroclear.telegram.formatting import format_alert_message, format_system_message, strip_asset_source_suffix
from mikroclear.telegram.notify import TelegramNotifier, TelegramSendResult, send_telegram_message


class TelegramNotifyFormattingTests(TestCase):
    def sample_event(self):
        return {
            "timestamp": "2026-07-02T12:00:00.000000+0300",
            "proto": "TCP",
            "in_iface": "tzsp0",
            "alert": {
                "signature_id": 2402000,
                "gid": 1,
                "severity": 2,
                "category": "Attempted Admin",
                "signature": "ET <DROP> test",
            },
        }

    def test_format_alert_message_uses_mikro_clear_branding_and_escapes_html(self):
        event = self.sample_event()

        text = format_alert_message(event, "9.9.9.9", "8.8.4.4", 443, "BLOCKED")

        self.assertIn("Mikro-Clear Alert - BLOCKED", text)
        self.assertIn("#mikroclear #security #alert", text)
        self.assertIn("ET &lt;DROP&gt; test", text)
        self.assertIn("<code>9.9.9.9</code>", text)
        self.assertNotIn("Mikrocata", text)

    def test_strip_asset_source_suffix_removes_only_trailing_source_labels(self):
        self.assertEqual(strip_asset_source_suffix("192.168.10.9 - i5 dhcp"), "192.168.10.9 - i5")
        self.assertEqual(strip_asset_source_suffix("192.168.10.9 - i5 ptr"), "192.168.10.9 - i5")
        self.assertEqual(strip_asset_source_suffix("192.168.10.9 - i5 static"), "192.168.10.9 - i5")
        self.assertEqual(strip_asset_source_suffix("192.168.10.9 dhcp"), "192.168.10.9")
        self.assertEqual(strip_asset_source_suffix("192.168.10.9 - dhcp-printer"), "192.168.10.9 - dhcp-printer")
        self.assertEqual(strip_asset_source_suffix("192.168.10.9 - i5-dhcp-host"), "192.168.10.9 - i5-dhcp-host")

    def test_strip_asset_source_suffix_removes_html_source_label(self):
        text = "<code>192.168.10.9</code> - <b>i5</b> <code>dhcp</code>"

        self.assertEqual(strip_asset_source_suffix(text), "<code>192.168.10.9</code> - <b>i5</b>")

    def test_format_alert_message_removes_asset_source_suffix_from_source_peer(self):
        text = format_alert_message(
            self.sample_event(),
            "9.9.9.9",
            "192.168.10.9",
            443,
            "BLOCKED",
            peer_formatter=lambda ip: f"{ip} - i5 dhcp",
        )

        self.assertIn("- Source/peer: 192.168.10.9 - i5", text)
        self.assertNotIn("i5 dhcp", text)

    def test_format_system_message_uses_mikro_clear_branding(self):
        text = format_system_message("Router reboot detected", "RESTORE")

        self.assertIn("Mikro-Clear System Notification", text)
        self.assertIn("<code>RESTORE</code>", text)
        self.assertIn("Router reboot detected", text)
        self.assertIn("#mikroclear #system", text)


class TelegramNotifyDeliveryTests(TestCase):
    def sample_event(self):
        return {
            "timestamp": "2026-07-02T12:00:00.000000+0300",
            "proto": "TCP",
            "in_iface": "tzsp0",
            "alert": {
                "signature_id": 2402000,
                "gid": 1,
                "severity": 2,
                "category": "Attempted Admin",
                "signature": "ET DROP test",
            },
        }

    def test_alert_keyboard_uses_confirm_callback_without_routeros_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "telegram-unblock-actions.json"
            send_message = Mock(return_value=TelegramSendResult(ok=True))
            notifier = TelegramNotifier(
                Settings(
                    enable_telegram=True,
                    telegram_token="token",
                    telegram_chatid="chat-1",
                    telegram_unblock_state_file=str(state_file),
                ),
                peer_formatter=None,
                log=Mock(),
                debug_log=Mock(),
                sanitize_exception_text=lambda exc, token: str(exc),
                now=Mock(return_value=100.0),
                send_message=send_message,
            )

            sent = notifier.send_alert(
                event=self.sample_event(),
                wanted_ip="48.209.138.168",
                src_ip="192.168.10.9",
                wanted_port=443,
                action_type="BLOCKED",
            )

        self.assertTrue(sent)
        reply_markup = send_message.call_args.kwargs["reply_markup"]
        button = reply_markup["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "🔓 Unblock 48.209.138.168")
        self.assertTrue(button["callback_data"].startswith("unblock_confirm:"))

    def test_send_telegram_message_posts_expected_payload(self):
        response = Mock(status_code=200, text="ok")
        with patch("mikroclear.telegram.notify.requests.post", return_value=response) as post:
            result = send_telegram_message("token", "chat", "<b>hello</b>", timeout=7)

        self.assertTrue(result.ok)
        self.assertEqual(result.retry_after, 0)
        post.assert_called_once_with(
            "https://api.telegram.org/bottoken/sendMessage",
            data={
                "chat_id": "chat",
                "text": "<b>hello</b>",
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=7,
        )

    def test_send_telegram_message_returns_retry_after_for_flood_control(self):
        response = Mock(status_code=429, text="too many")
        response.json.return_value = {"parameters": {"retry_after": 12}}

        with patch("mikroclear.telegram.notify.requests.post", return_value=response):
            result = send_telegram_message("token", "chat", "hello", timeout=7)

        self.assertFalse(result.ok)
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result.retry_after, 12)
        self.assertEqual(result.response_text, "too many")

    def test_send_telegram_message_masks_token_in_response_text(self):
        response = Mock(status_code=500, text="failed /bot123456:ABC_def-123/sendMessage")
        response.json.return_value = {}

        with patch("mikroclear.telegram.notify.requests.post", return_value=response):
            result = send_telegram_message("123456:ABC_def-123", "chat", "hello", timeout=7)

        self.assertFalse(result.ok)
        self.assertEqual(result.response_text, "failed /bot***MASKED***/sendMessage")
