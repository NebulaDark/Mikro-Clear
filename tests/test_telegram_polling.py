from unittest import TestCase

from mikroclear.telegram.polling import TelegramPollingBackoff


class TelegramPollingBackoffTests(TestCase):
    def test_failure_increases_backoff_to_maximum(self):
        backoff = TelegramPollingBackoff(base_seconds=30, max_seconds=300, log_every_seconds=120)

        self.assertEqual(backoff.record_failure(100.0, "ConnectionError"), (True, 30))
        self.assertEqual(backoff.record_failure(130.0, "ConnectionError"), (False, 60))
        self.assertEqual(backoff.record_failure(190.0, "ConnectionError"), (False, 120))
        self.assertEqual(backoff.record_failure(310.0, "ConnectionError"), (True, 240))
        self.assertEqual(backoff.record_failure(550.0, "ConnectionError"), (True, 300))

    def test_success_resets_backoff(self):
        backoff = TelegramPollingBackoff(base_seconds=30, max_seconds=300, log_every_seconds=120)

        backoff.record_failure(100.0, "ReadTimeout")
        backoff.record_success(130.0)

        self.assertTrue(backoff.should_poll(131.0))
        self.assertEqual(backoff.record_failure(131.0, "ReadTimeout"), (True, 30))
