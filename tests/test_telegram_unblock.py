import tempfile
import time
import unittest
from pathlib import Path

from mikroclear.telegram_unblock import (
    build_unblock_keyboard,
    consume_unblock_token,
    create_unblock_token,
    parse_unblock_callback,
)


class TelegramUnblockTests(unittest.TestCase):
    def test_create_token_persists_unblock_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unblock.json"

            token = create_unblock_token(
                path,
                wanted_ip="9.9.9.9",
                list_name="Suricata",
                sid="2402000",
                now=100,
                ttl_seconds=3600,
                token_factory=lambda: "tok123",
            )

            self.assertEqual(token, "tok123")
            action = consume_unblock_token(path, "tok123", now=200)
            self.assertEqual(action["wanted_ip"], "9.9.9.9")
            self.assertEqual(action["list_name"], "Suricata")
            self.assertEqual(action["sid"], "2402000")
            self.assertIsNone(consume_unblock_token(path, "tok123", now=201))

    def test_expired_token_is_rejected_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unblock.json"
            create_unblock_token(
                path,
                wanted_ip="9.9.9.9",
                list_name="Suricata",
                sid="2402000",
                now=100,
                ttl_seconds=10,
                token_factory=lambda: "tok123",
            )

            self.assertIsNone(consume_unblock_token(path, "tok123", now=111))

    def test_parse_unblock_callback(self):
        self.assertEqual(parse_unblock_callback("unblock:abc123"), "abc123")
        self.assertIsNone(parse_unblock_callback("noop:abc123"))
        self.assertIsNone(parse_unblock_callback("unblock:bad token"))

    def test_keyboard_contains_unblock_callback(self):
        keyboard = build_unblock_keyboard("9.9.9.9", "tok123")

        buttons = keyboard["inline_keyboard"]
        self.assertEqual(buttons[0][0]["callback_data"], "unblock:tok123")
        self.assertIn("Unblock 9.9.9.9", buttons[0][0]["text"])


if __name__ == "__main__":
    unittest.main()
