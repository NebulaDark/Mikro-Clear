"""Bounded active sessions for the single-worker Web MVP."""

from collections import OrderedDict
import secrets
import threading
import time


class SessionStore:
    def __init__(self, *, ttl_seconds: int = 8 * 3600, max_sessions: int = 4096):
        if ttl_seconds <= 0 or max_sessions <= 0:
            raise ValueError("Session lifetime and capacity must be positive")
        self._ttl = ttl_seconds
        self._maximum = max_sessions
        self._sessions: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._lock = threading.Lock()

    def _expire(self, now: float) -> None:
        while self._sessions:
            session_id, (_, expires) = next(iter(self._sessions.items()))
            if expires > now:
                break
            del self._sessions[session_id]

    def create(self, username: str) -> str:
        with self._lock:
            now = time.monotonic()
            self._expire(now)
            while len(self._sessions) >= self._maximum:
                self._sessions.popitem(last=False)
            session_id = secrets.token_urlsafe(32)
            self._sessions[session_id] = (username, now + self._ttl)
            return session_id

    def active(self, session_id: str, username: str) -> bool:
        with self._lock:
            self._expire(time.monotonic())
            session = self._sessions.get(session_id)
            return session is not None and session[0] == username

    def revoke(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
