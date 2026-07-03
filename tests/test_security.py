from unittest import TestCase

from mikroclear.security import mask_known_secret, mask_telegram_bot_token, sanitize_exception_text


class SecurityMaskingTests(TestCase):
    def test_masks_telegram_bot_token_in_url(self):
        text = "https://api.telegram.org/bot123456:ABC_def-123/getUpdates"

        self.assertEqual(
            mask_telegram_bot_token(text),
            "https://api.telegram.org/bot***MASKED***/getUpdates",
        )

    def test_masks_known_secret_value(self):
        self.assertEqual(mask_known_secret("token=abc123", "abc123", "TOKEN"), "token=***MASKED***")

    def test_sanitize_exception_text_masks_known_secret_and_bot_url(self):
        exc = RuntimeError("failed https://api.telegram.org/bot123456:ABC_def-123/getUpdates token=abc123")
        sanitized = sanitize_exception_text(exc, "abc123")

        self.assertNotIn("ABC_def-123", sanitized)
        self.assertNotIn("abc123", sanitized)
        self.assertIn("/bot***MASKED***/getUpdates", sanitized)
