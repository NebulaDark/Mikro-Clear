import unittest

from mikroclear.web.rate_limit import SlidingWindowLimiter


class WebRateLimitTests(unittest.TestCase):
    def test_window_expires_and_allows_new_attempt(self):
        now = [100.0]
        limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
        self.assertTrue(limiter.allow("client-a"))
        self.assertTrue(limiter.allow("client-a"))
        self.assertFalse(limiter.allow("client-a"))
        now[0] = 160.0
        self.assertTrue(limiter.allow("client-a"))

    def test_key_capacity_fails_closed_until_old_window_expires(self):
        now = [100.0]
        limiter = SlidingWindowLimiter(
            limit=2, window_seconds=60, max_keys=1, clock=lambda: now[0]
        )
        self.assertTrue(limiter.allow("client-a"))
        self.assertFalse(limiter.allow("client-b"))
        now[0] = 161.0
        self.assertTrue(limiter.allow("client-b"))


if __name__ == "__main__":
    unittest.main()
