from unittest import TestCase
from unittest.mock import Mock, patch

from mikroclear.telegram_notify import (
    format_alert_message,
    format_system_message,
    send_telegram_message,
)


class TelegramNotifyFormattingTests(TestCase):
    def test_format_alert_message_uses_mikro_clear_branding_and_escapes_html(self):
        event = {
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

        text = format_alert_message(event, "9.9.9.9", "8.8.4.4", 443, "BLOCKED")

        self.assertIn("Mikro-Clear Alert - BLOCKED", text)
        self.assertIn("#mikroclear #security #alert", text)
        self.assertIn("ET &lt;DROP&gt; test", text)
        self.assertIn("<code>9.9.9.9</code>", text)
        self.assertNotIn("Mikrocata", text)

    def test_format_system_message_uses_mikro_clear_branding(self):
        text = format_system_message("Router reboot detected", "RESTORE")

        self.assertIn("Mikro-Clear System Notification", text)
        self.assertIn("<code>RESTORE</code>", text)
        self.assertIn("Router reboot detected", text)
        self.assertIn("#mikroclear #system", text)


class TelegramNotifyDeliveryTests(TestCase):
    def test_send_telegram_message_posts_expected_payload(self):
        response = Mock(status_code=200, text="ok")
        with patch("mikroclear.telegram_notify.requests.post", return_value=response) as post:
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

        with patch("mikroclear.telegram_notify.requests.post", return_value=response):
            result = send_telegram_message("token", "chat", "hello", timeout=7)

        self.assertFalse(result.ok)
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result.retry_after, 12)
        self.assertEqual(result.response_text, "too many")
