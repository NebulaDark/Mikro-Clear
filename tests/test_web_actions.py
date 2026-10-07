import unittest
from unittest.mock import patch

from mikroclear.web.actions import ConfirmationError, ConfirmationStore


class ConfirmationStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = ConfirmationStore("test-only-signing-secret", ttl_seconds=30)

    def test_confirmation_is_one_shot(self):
        token = self.store.create("mangle", {"rule_id": "*1"}, owner="session-a")
        self.assertEqual(
            self.store.consume(token, kind="mangle", owner="session-a"),
            {"rule_id": "*1"},
        )
        with self.assertRaises(ConfirmationError):
            self.store.consume(token, kind="mangle", owner="session-a")

    def test_confirmation_is_bound_to_requesting_session(self):
        token = self.store.create("unblock", {"address": "192.0.2.4"}, owner="session-a")
        with self.assertRaises(ConfirmationError):
            self.store.consume(token, kind="unblock", owner="session-b")
        self.assertEqual(
            self.store.consume(token, kind="unblock", owner="session-a"),
            {"address": "192.0.2.4"},
        )

    def test_wrong_action_and_tampering_are_rejected(self):
        token = self.store.create("mangle", {"rule_id": "*1"}, owner="session-a")
        with self.assertRaises(ConfirmationError):
            self.store.consume(token, kind="unblock", owner="session-a")
        with self.assertRaises(ConfirmationError):
            self.store.consume(token + "x", kind="mangle", owner="session-a")
        self.assertEqual(self.store.consume(token, kind="mangle", owner="session-a"), {"rule_id": "*1"})

    def test_expired_token_is_rejected(self):
        with patch("itsdangerous.timed.time.time", return_value=100):
            token = self.store.create("mangle", {"rule_id": "*1"}, owner="session-a")
        with patch("itsdangerous.timed.time.time", return_value=131):
            with self.assertRaises(ConfirmationError):
                self.store.consume(token, kind="mangle", owner="session-a")

    def test_old_token_cannot_be_replayed_after_many_actions(self):
        token = self.store.create("mangle", {"rule_id": "*1"}, owner="session-a")
        self.store.consume(token, kind="mangle", owner="session-a")
        for index in range(4096):
            other = self.store.create("mangle", {"rule_id": str(index)}, owner="session-a")
            self.store.consume(other, kind="mangle", owner="session-a")
        with self.assertRaises(ConfirmationError):
            self.store.consume(token, kind="mangle", owner="session-a")


if __name__ == "__main__":
    unittest.main()
