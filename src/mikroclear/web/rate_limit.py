"""Bounded in-process rate limiter for Web authentication and write requests."""

from collections import deque
from threading import Lock
from time import monotonic
from typing import Callable


class SlidingWindowLimiter:
    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        max_keys: int = 4096,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._entries: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        with self._lock:
            now = self._clock()
            cutoff = now - self._window
            bucket = self._entries.get(key)
            if bucket is None:
                if len(self._entries) >= self._max_keys:
                    self._entries = {
                        existing_key: existing_bucket
                        for existing_key, existing_bucket in self._entries.items()
                        if existing_bucket[-1] > cutoff
                    }
                if len(self._entries) >= self._max_keys:
                    return False
                bucket = deque()
                self._entries[key] = bucket
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self._limit:
                return False
            bucket.append(now)
            return True
