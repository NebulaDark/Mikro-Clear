"""Long-poll network worker with main-thread update handling."""

from dataclasses import dataclass, field
from queue import Empty, Full, Queue
from threading import Event, Thread
from typing import Any, Callable

from mikroclear.security import sanitize_exception_text


@dataclass
class PendingTelegramUpdate:
    update: dict[str, Any]
    completed: Event = field(default_factory=Event)
    succeeded: bool = False
    error_text: str = ""


class TelegramPollingWorker:
    RETRY_DELAYS = (5, 10, 20, 40)

    def __init__(
        self,
        poller: Any,
        *,
        long_poll_seconds: int,
        log: Callable[[str], None],
        retry_delays: tuple[int, ...] | None = None,
    ) -> None:
        self.poller = poller
        self.long_poll_seconds = long_poll_seconds
        self.log = log
        self.retry_delays = retry_delays or self.RETRY_DELAYS
        self._queue: Queue[PendingTelegramUpdate] = Queue(maxsize=1)
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(
            target=self._run,
            name="telegram-long-poll",
            daemon=True,
        )
        self._thread.start()

    def drain_ready(self) -> bool:
        try:
            pending = self._queue.get_nowait()
        except Empty:
            return False

        try:
            self.poller.process_update(pending.update)
        except Exception as exc:
            pending.error_text = sanitize_exception_text(
                exc,
                self.poller.settings.telegram_token,
            )
        else:
            pending.succeeded = True
        finally:
            pending.completed.set()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is None:
            return
        self._thread.join(timeout=self.long_poll_seconds + 5)
        if self._thread.is_alive():
            self.log("Telegram polling worker did not stop before timeout")

    def _publish(self, pending: PendingTelegramUpdate) -> bool:
        while not self._stop.is_set():
            try:
                self._queue.put(pending, timeout=0.25)
                return True
            except Full:
                continue
        return False

    def _run(self) -> None:
        while not self._stop.is_set():
            updates = self.poller.fetch_updates(
                long_poll_seconds=self.long_poll_seconds,
            )
            if updates is None:
                self._stop.wait(1)
                continue
            if not updates:
                self._stop.wait(0.01)
                continue

            for update in updates:
                if not self._process_with_retries(update):
                    return

    def _process_with_retries(self, update: dict[str, Any]) -> bool:
        attempts = len(self.retry_delays) + 1
        for attempt in range(attempts):
            pending = PendingTelegramUpdate(update=update)
            if not self._publish(pending):
                return False

            while not pending.completed.wait(0.25):
                if self._stop.is_set():
                    return False

            if pending.succeeded:
                self.poller.acknowledge_update(update)
                return True

            if attempt == attempts - 1:
                update_id = update.get("update_id", "unknown")
                self.log(
                    f"Abandoned Telegram update {update_id} after {attempts} attempts: "
                    f"{pending.error_text}"
                )
                self.poller.acknowledge_update(update)
                return True

            if self._stop.wait(self.retry_delays[attempt]):
                return False

        return False


__all__ = ["TelegramPollingWorker"]
