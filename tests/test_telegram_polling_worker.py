import time
import types
from threading import Event
from unittest import TestCase

from mikroclear.telegram.polling_worker import (
    TelegramPollingWorker,
    TelegramWorkerFatalError,
)


def wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


class FakePoller:
    def __init__(self, updates, failures=0):
        self.settings = types.SimpleNamespace(
            telegram_token="token",
            telegram_timeout=10,
        )
        self.updates = list(updates)
        self.failures = failures
        self.fetch_calls = 0
        self.fetched = Event()
        self.processed = []
        self.acked = []

    def fetch_updates(self, *, long_poll_seconds):
        self.fetch_calls += 1
        self.fetched.set()
        if self.fetch_calls == 1:
            return list(self.updates)
        return []

    def process_update(self, update):
        self.processed.append(update["update_id"])
        if len(self.processed) <= self.failures:
            raise RuntimeError("temporary")

    def acknowledge_update(self, update):
        self.acked.append(update["update_id"])


class TelegramPollingWorkerTests(TestCase):
    def drain_until(self, worker, predicate, timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            worker.drain_ready()
            if predicate():
                return True
            time.sleep(0.005)
        return False

    def test_worker_waits_for_main_thread_and_preserves_batch_order(self):
        poller = FakePoller([{"update_id": 10}, {"update_id": 11}])
        worker = TelegramPollingWorker(
            poller,
            long_poll_seconds=25,
            log=lambda message: None,
            retry_delays=(0, 0, 0, 0),
        )
        self.addCleanup(worker.stop)

        worker.start()
        self.assertTrue(poller.fetched.wait(1.0))
        self.assertEqual(poller.processed, [])
        self.assertEqual(poller.acked, [])
        self.assertEqual(poller.fetch_calls, 1)

        self.assertTrue(wait_until(worker.drain_ready))
        self.assertTrue(wait_until(lambda: poller.acked == [10]))
        self.assertEqual(poller.processed, [10])
        self.assertEqual(poller.fetch_calls, 1)

        self.assertTrue(wait_until(worker.drain_ready))
        self.assertTrue(wait_until(lambda: poller.acked == [10, 11]))
        self.assertEqual(poller.processed, [10, 11])

    def test_retryable_update_gets_five_attempts_before_success(self):
        poller = FakePoller([{"update_id": 20}], failures=4)
        worker = TelegramPollingWorker(
            poller,
            long_poll_seconds=25,
            log=lambda message: None,
            retry_delays=(0, 0, 0, 0),
        )
        self.addCleanup(worker.stop)

        worker.start()

        self.assertTrue(self.drain_until(worker, lambda: poller.acked == [20]))
        self.assertEqual(poller.processed, [20, 20, 20, 20, 20])

    def test_poison_update_is_logged_and_acknowledged_after_five_attempts(self):
        logs = []
        poller = FakePoller([{"update_id": 30}], failures=5)
        worker = TelegramPollingWorker(
            poller,
            long_poll_seconds=25,
            log=logs.append,
            retry_delays=(0, 0, 0, 0),
        )
        self.addCleanup(worker.stop)

        worker.start()

        self.assertTrue(self.drain_until(worker, lambda: poller.acked == [30]))
        self.assertEqual(poller.processed, [30, 30, 30, 30, 30])
        abandoned_logs = [
            message
            for message in logs
            if "Abandoned Telegram update 30 after 5 attempts" in message
        ]
        self.assertEqual(len(abandoned_logs), 1)

    def test_stop_prevents_additional_fetches(self):
        poller = FakePoller([])
        worker = TelegramPollingWorker(
            poller,
            long_poll_seconds=25,
            log=lambda message: None,
            retry_delays=(0, 0, 0, 0),
        )

        worker.start()
        self.assertTrue(poller.fetched.wait(1.0))
        worker.stop()
        fetch_calls = poller.fetch_calls
        time.sleep(0.02)

        self.assertEqual(poller.fetch_calls, fetch_calls)

    def test_stop_waits_longer_than_configured_request_timeout(self):
        class FakeThread:
            def __init__(self):
                self.join_timeouts = []

            def join(self, timeout):
                self.join_timeouts.append(timeout)

            def is_alive(self):
                return False

        poller = FakePoller([])
        poller.settings.telegram_timeout = 10
        worker = TelegramPollingWorker(
            poller,
            long_poll_seconds=1,
            log=lambda message: None,
        )
        thread = FakeThread()
        worker._thread = thread

        worker.stop()

        self.assertGreater(thread.join_timeouts[0], 10)

    def test_fatal_worker_error_does_not_expose_update_payload(self):
        class CrashingPoller(FakePoller):
            def fetch_updates(self, *, long_poll_seconds):
                raise RuntimeError(
                    "token=token message text=hello from Telegram "
                    "callback_data=unblock:42 update_body={'update_id': 99}"
                )

        logs = []
        poller = CrashingPoller([])
        worker = TelegramPollingWorker(poller, long_poll_seconds=25, log=logs.append)
        worker.start()

        self.assertTrue(
            wait_until(lambda: worker._thread is not None and not worker._thread.is_alive())
        )
        with self.assertRaises(TelegramWorkerFatalError) as raised:
            worker.check_health()

        diagnostics = " ".join([*logs, str(raised.exception)])
        for payload in (
            "token",
            "message text",
            "hello from Telegram",
            "callback_data",
            "unblock:42",
            "update_body",
            "update_id",
        ):
            self.assertNotIn(payload, diagnostics)
        self.assertIn("RuntimeError", diagnostics)

    def test_health_check_succeeds_before_start(self):
        worker = TelegramPollingWorker(
            FakePoller([]),
            long_poll_seconds=25,
            log=lambda message: None,
        )

        worker.check_health()

    def test_health_check_succeeds_while_empty_worker_is_alive(self):
        poller = FakePoller([])
        worker = TelegramPollingWorker(
            poller,
            long_poll_seconds=25,
            log=lambda message: None,
        )
        self.addCleanup(worker.stop)

        worker.start()
        self.assertTrue(poller.fetched.wait(1.0))

        worker.check_health()

    def test_health_check_succeeds_after_stop(self):
        poller = FakePoller([])
        worker = TelegramPollingWorker(
            poller,
            long_poll_seconds=25,
            log=lambda message: None,
        )

        worker.start()
        self.assertTrue(poller.fetched.wait(1.0))
        worker.stop()

        worker.check_health()
