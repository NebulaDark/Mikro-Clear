import unittest
from unittest.mock import patch

from mikroclear.web.sessions import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_expiry_is_absolute_and_bound_evicts_oldest(self):
        with patch("mikroclear.web.sessions.time.monotonic", return_value=100) as clock:
            store = SessionStore(ttl_seconds=10, max_sessions=2)
            first = store.create("admin")
            second = store.create("admin")
            self.assertFalse(store.active(first, "other"))
            clock.return_value = 105
            self.assertTrue(store.active(first, "admin"))
            third = store.create("admin")
            self.assertFalse(store.active(first, "admin"))
            self.assertTrue(store.active(second, "admin"))
            clock.return_value = 110
            self.assertFalse(store.active(second, "admin"))
            self.assertTrue(store.active(third, "admin"))
            store.revoke(third)
            self.assertFalse(store.active(third, "admin"))
