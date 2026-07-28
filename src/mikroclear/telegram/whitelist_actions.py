"""Persistent, requester-bound Telegram managed-whitelist actions."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
from typing import Any, Callable

from mikroclear.state.dynamic_whitelist import is_managed_private_ipv4


TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,24}$")
ACTION_KINDS = frozenset(
    {
        "add_request",
        "add_confirm",
        "remove_confirm",
        "retry_unblock",
    }
)
CALLBACK_ACTIONS = frozenset(
    {
        "add-request",
        "add-confirm",
        "remove-request",
        "remove-confirm",
        "retry-unblock",
        "cancel",
    }
)
PAYLOAD_FIELDS = frozenset(
    {
        "kind",
        "address",
        "list_name",
        "sid",
        "chat_id",
        "user_id",
        "created_at",
        "expires_at",
        "source_chat_id",
        "source_message_id",
        "source_reply_markup",
    }
)


class WhitelistActionStoreError(RuntimeError):
    """Raised when persisted whitelist action state cannot be read safely."""


class WhitelistActionStore:
    def __init__(
        self,
        path: Path,
        *,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.path = Path(path)
        self.token_factory = token_factory or (lambda: secrets.token_urlsafe(12))
        self._lock = threading.RLock()

    def create(
        self,
        *,
        kind: str,
        address: str,
        list_name: str,
        chat_id: str,
        user_id: str,
        now: int,
        ttl_seconds: int,
        sid: str = "N/A",
        source_chat_id: str = "",
        source_message_id: int | None = None,
        source_reply_markup: Any = None,
    ) -> str:
        self._validate_action(
            kind=kind,
            address=address,
            list_name=list_name,
            chat_id=chat_id,
            user_id=user_id,
            ttl_seconds=ttl_seconds,
        )
        token = self.token_factory()
        if not isinstance(token, str) or TOKEN_RE.fullmatch(token) is None:
            raise ValueError("whitelist action token is invalid")

        created_at = int(now)
        payload = {
            "kind": kind,
            "address": address,
            "list_name": list_name,
            "sid": str(sid),
            "chat_id": chat_id,
            "user_id": user_id,
            "created_at": created_at,
            "expires_at": created_at + int(ttl_seconds),
            "source_chat_id": source_chat_id,
            "source_message_id": source_message_id,
            "source_reply_markup": source_reply_markup,
        }
        with self._lock:
            state = self._read_state()
            self._remove_expired(state, created_at)
            if token in state:
                raise ValueError("whitelist action token collision")
            state[token] = payload
            self._write_state(state)
        return token

    def peek(
        self,
        token: str,
        *,
        now: int,
        chat_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        if not isinstance(token, str) or TOKEN_RE.fullmatch(token) is None:
            return None
        with self._lock:
            state = self._read_state()
            changed = self._remove_expired(state, int(now))
            payload = state.get(token)
            if changed:
                self._write_state(state)
            if payload is None or not self._matches_requester(
                payload,
                chat_id=chat_id,
                user_id=user_id,
            ):
                return None
            return dict(payload)

    def consume(
        self,
        token: str,
        *,
        now: int,
        chat_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        if not isinstance(token, str) or TOKEN_RE.fullmatch(token) is None:
            return None
        with self._lock:
            state = self._read_state()
            changed = self._remove_expired(state, int(now))
            payload = state.get(token)
            if payload is None or not self._matches_requester(
                payload,
                chat_id=chat_id,
                user_id=user_id,
            ):
                if changed:
                    self._write_state(state)
                return None
            state.pop(token)
            self._write_state(state)
            return dict(payload)

    def cancel(
        self,
        token: str,
        *,
        now: int,
        chat_id: str,
        user_id: str,
    ) -> bool:
        return (
            self.consume(
                token,
                now=now,
                chat_id=chat_id,
                user_id=user_id,
            )
            is not None
        )

    @staticmethod
    def _validate_action(
        *,
        kind: str,
        address: str,
        list_name: str,
        chat_id: str,
        user_id: str,
        ttl_seconds: int,
    ) -> None:
        if kind not in ACTION_KINDS:
            raise ValueError("whitelist action kind is invalid")
        if not isinstance(address, str) or not is_managed_private_ipv4(address):
            raise ValueError("whitelist action accepts only exact RFC1918 IPv4")
        if not isinstance(list_name, str) or not list_name:
            raise ValueError("whitelist action list name is required")
        if not isinstance(chat_id, str) or not chat_id:
            raise ValueError("whitelist action chat id is required")
        if not isinstance(user_id, str):
            raise ValueError("whitelist action user id must be a string")
        if kind != "add_request" and not user_id:
            raise ValueError("whitelist confirmation actions require a user id")
        if type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise ValueError("whitelist action ttl must be positive")

    @staticmethod
    def _matches_requester(
        payload: dict[str, Any],
        *,
        chat_id: str,
        user_id: str,
    ) -> bool:
        if payload["chat_id"] != chat_id:
            return False
        stored_user_id = payload["user_id"]
        if stored_user_id:
            return bool(user_id) and stored_user_id == user_id
        return payload["kind"] == "add_request"

    @staticmethod
    def _remove_expired(
        state: dict[str, dict[str, Any]],
        now: int,
    ) -> bool:
        expired = [
            token
            for token, payload in state.items()
            if payload["expires_at"] <= now
        ]
        for token in expired:
            state.pop(token)
        return bool(expired)

    def _read_state(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            os.chmod(self.path, 0o600)
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WhitelistActionStoreError(
                f"cannot read whitelist actions: {type(exc).__name__}"
            ) from exc
        if not isinstance(document, dict):
            raise WhitelistActionStoreError("whitelist action state must be an object")

        state: dict[str, dict[str, Any]] = {}
        for token, payload in document.items():
            if (
                not isinstance(token, str)
                or TOKEN_RE.fullmatch(token) is None
                or not isinstance(payload, dict)
                or set(payload) != PAYLOAD_FIELDS
                or not self._valid_persisted_payload(payload)
            ):
                raise WhitelistActionStoreError(
                    "whitelist action state contains an invalid action"
                )
            state[token] = dict(payload)
        return state

    @staticmethod
    def _valid_persisted_payload(payload: dict[str, Any]) -> bool:
        kind = payload.get("kind")
        user_id = payload.get("user_id")
        return (
            kind in ACTION_KINDS
            and isinstance(payload.get("address"), str)
            and is_managed_private_ipv4(payload["address"])
            and isinstance(payload.get("list_name"), str)
            and bool(payload["list_name"])
            and isinstance(payload.get("sid"), str)
            and isinstance(payload.get("chat_id"), str)
            and bool(payload["chat_id"])
            and isinstance(user_id, str)
            and (kind == "add_request" or bool(user_id))
            and type(payload.get("created_at")) is int
            and type(payload.get("expires_at")) is int
            and payload["expires_at"] > payload["created_at"]
            and isinstance(payload.get("source_chat_id"), str)
            and (
                payload.get("source_message_id") is None
                or type(payload["source_message_id"]) is int
            )
        )

    def _write_state(self, state: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=self.path.parent,
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    state,
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary.exists():
                temporary.unlink()


def parse_whitelist_callback(data: Any) -> tuple[str, str] | None:
    if not isinstance(data, str):
        return None
    parts = data.split(":")
    if (
        len(parts) != 4
        or parts[0:2] != ["whitelist", "v1"]
        or parts[2] not in CALLBACK_ACTIONS
        or TOKEN_RE.fullmatch(parts[3]) is None
    ):
        return None
    return parts[2], parts[3]


def append_managed_exception_button(
    reply_markup: dict[str, Any],
    *,
    address: str,
    token: str,
) -> dict[str, Any]:
    rows = [list(row) for row in reply_markup.get("inline_keyboard", [])]
    rows.append(
        [
            {
                "text": f"🛡 Добавить в исключения {address}",
                "callback_data": f"whitelist:v1:add-request:{token}",
            }
        ]
    )
    return {"inline_keyboard": rows}


def build_whitelist_confirm_keyboard(token: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Добавить и разблокировать",
                    "callback_data": f"whitelist:v1:add-confirm:{token}",
                }
            ],
            [
                {
                    "text": "❌ Отмена",
                    "callback_data": f"whitelist:v1:cancel:{token}",
                }
            ],
        ]
    }


__all__ = [
    "TOKEN_RE",
    "WhitelistActionStore",
    "WhitelistActionStoreError",
    "append_managed_exception_button",
    "build_whitelist_confirm_keyboard",
    "parse_whitelist_callback",
]
