"""Telegram unblock callback state helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import re
import secrets
from typing import Any, Callable, Optional


TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


@dataclass(frozen=True)
class UnblockCallbackResult:
    text: str
    success: bool
    alert: bool = False


def ensure_private_state_path(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("{}")
    os.chmod(path, 0o600)


def _read_state(path: Path) -> dict[str, dict[str, Any]]:
    ensure_private_state_path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(key): value for key, value in data.items() if isinstance(value, dict)}
    except Exception:
        pass
    return {}


def _write_state(path: Path, state: dict[str, dict[str, Any]]) -> None:
    ensure_private_state_path(path)
    path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.chmod(path, 0o600)


def create_unblock_token(
    path: Path,
    *,
    wanted_ip: str,
    list_name: str,
    sid: str,
    now: int,
    ttl_seconds: int,
    token_factory: Callable[[], str] | None = None,
) -> str:
    token_factory = token_factory or (lambda: secrets.token_urlsafe(12))
    token = token_factory()
    state = _read_state(path)
    state[token] = {
        "wanted_ip": wanted_ip,
        "list_name": list_name,
        "sid": sid,
        "expires_at": int(now) + max(1, int(ttl_seconds)),
    }
    _write_state(path, state)
    return token


def consume_unblock_token(path: Path, token: str, *, now: int) -> Optional[dict[str, Any]]:
    if not TOKEN_RE.match(token):
        return None

    state = _read_state(path)
    action = state.pop(token, None)
    changed = action is not None

    for key, value in list(state.items()):
        if int(value.get("expires_at", 0)) <= int(now):
            state.pop(key, None)
            changed = True

    if changed:
        _write_state(path, state)

    if not action or int(action.get("expires_at", 0)) <= int(now):
        return None
    return action


def peek_unblock_token(path: Path, token: str, *, now: int) -> Optional[dict[str, Any]]:
    if not TOKEN_RE.match(token):
        return None

    state = _read_state(path)
    action = state.get(token)
    changed = False

    for key, value in list(state.items()):
        if int(value.get("expires_at", 0)) <= int(now):
            state.pop(key, None)
            changed = True

    if changed:
        _write_state(path, state)

    if not action or int(action.get("expires_at", 0)) <= int(now):
        return None
    return dict(action)


def cancel_unblock_token(path: Path, token: str, *, now: int) -> bool:
    if not TOKEN_RE.match(token):
        return False

    state = _read_state(path)
    action = state.pop(token, None)
    changed = action is not None

    for key, value in list(state.items()):
        if int(value.get("expires_at", 0)) <= int(now):
            state.pop(key, None)
            changed = True

    if changed:
        _write_state(path, state)

    return bool(action and int(action.get("expires_at", 0)) > int(now))


def parse_unblock_callback(data: Any) -> Optional[tuple[str, str]]:
    if not isinstance(data, str):
        return None

    action_map = {
        "unblock": "confirm",
        "unblock_confirm": "confirm",
        "unblock_execute": "execute",
        "unblock_cancel": "cancel",
    }
    prefix, separator, token = data.partition(":")
    if separator != ":" or prefix not in action_map or not TOKEN_RE.match(token):
        return None
    return action_map[prefix], token


def build_unblock_keyboard(wanted_ip: str, token: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": f"🔓 Unblock {wanted_ip}",
                    "callback_data": f"unblock_confirm:{token}",
                }
            ],
            [
                {"text": "AbuseIPDB", "url": f"https://www.abuseipdb.com/check/{wanted_ip}"},
                {"text": "VirusTotal", "url": f"https://www.virustotal.com/gui/ip-address/{wanted_ip}"},
            ],
        ]
    }


def build_unblock_confirm_keyboard(token: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Confirm unblock", "callback_data": f"unblock_execute:{token}"},
                {"text": "❌ Cancel", "callback_data": f"unblock_cancel:{token}"},
            ]
        ]
    }
