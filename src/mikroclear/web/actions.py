"""Short-lived one-time confirmation tokens for Web write actions."""

from threading import Lock
from typing import Any
import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


class ConfirmationError(ValueError):
    """Raised when a confirmation token is invalid, stale, or already consumed."""


class ConfirmationStore:
    def __init__(self, secret: str, *, ttl_seconds: int = 120) -> None:
        self._serializer = URLSafeTimedSerializer(secret, salt="mikroclear-web-action-v1")
        self._ttl_seconds = max(30, int(ttl_seconds))
        self._used: set[str] = set()
        self._lock = Lock()

    def create(self, kind: str, payload: dict[str, Any]) -> str:
        body = {"kind": str(kind), "nonce": secrets.token_urlsafe(18), "payload": dict(payload)}
        return self._serializer.dumps(body)

    def consume(self, token: str, *, kind: str) -> dict[str, Any]:
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
            if nonce in self._used:
                raise ConfirmationError("Confirmation already used")
            self._used.add(nonce)
            if len(self._used) > 4096:
                self._used.clear()
        return payload


__all__ = ["ConfirmationError", "ConfirmationStore"]
