from dataclasses import dataclass


@dataclass
class TelegramPollingBackoff:
    base_seconds: int = 30
    max_seconds: int = 300
    log_every_seconds: int = 120
    failure_count: int = 0
    next_poll_at: float = 0.0
    last_logged_at: float = 0.0
    last_error_key: str = ""

    def should_poll(self, now: float) -> bool:
        return now >= self.next_poll_at

    def record_success(self, now: float) -> None:
        self.failure_count = 0
        self.next_poll_at = now
        self.last_logged_at = 0.0
        self.last_error_key = ""

    def record_failure(self, now: float, error_key: str) -> tuple[bool, int]:
        delay = min(self.max_seconds, self.base_seconds * (2 ** self.failure_count))
        self.failure_count += 1
        self.next_poll_at = now + delay

        should_log = error_key != self.last_error_key or now - self.last_logged_at >= self.log_every_seconds
        if should_log:
            self.last_logged_at = now
            self.last_error_key = error_key

        return should_log, delay
