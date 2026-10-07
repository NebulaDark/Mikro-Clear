"""Short-lived one-time confirmation tokens for Web write actions."""

from threading import Lock
from time import time
from typing import Any
import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


class ConfirmationError(ValueError):
    """Raised when a confirmation token is invalid, stale, or already consumed."""


class ConfirmationStore:
    def __init__(self, secret: str, *, ttl_seconds: int = 120) -> None:
        self._serializer = URLSafeTimedSerializer(secret, salt="mikroclear-web-action-v1")
        self._ttl_seconds = max(30, int(ttl_seconds))
        self._pending: dict[str, tuple[str, float]] = {}
        self._lock = Lock()

    def create(self, kind: str, payload: dict[str, Any], *, owner: str) -> str:
        if not owner:
            raise ConfirmationError("Confirmation owner is required")
        nonce = secrets.token_urlsafe(18)
        body = {"kind": str(kind), "nonce": nonce, "payload": dict(payload)}
        with self._lock:
            now = time()
            self._pending = {
                key: entry for key, entry in self._pending.items() if entry[1] > now
            }
            if len(self._pending) >= 4096:
                raise ConfirmationError("Too many pending confirmations")
            token = self._serializer.dumps(body)
            self._pending[nonce] = (owner, now + self._ttl_seconds)
            return token

    def consume(self, token: str, *, kind: str, owner: str) -> dict[str, Any]:
        try:
            body = self._serializer.loads(token, max_age=self._ttl_seconds)
        except SignatureExpired as exc:
            raise ConfirmationError("Confirmation expired") from exc
        except BadSignature as exc:
            raise ConfirmationError("Invalid confirmation token") from exc
        if not isinstance(body, dict) or body.get("kind") != kind:
            raise ConfirmationError("Confirmation action mismatch")
        nonce = str(body.get("nonce", ""))
        payload = body.get("payload")
        if not nonce or not isinstance(payload, dict):
            raise ConfirmationError("Malformed confirmation token")
        with self._lock:
            pending = self._pending.get(nonce)
            if pending is None or pending[1] <= time():
                raise ConfirmationError("Confirmation expired or already used")
            if pending[0] != owner:
                raise ConfirmationError("Confirmation owner mismatch")
            del self._pending[nonce]
        return payload


__all__ = ["ConfirmationError", "ConfirmationStore"]
