# Mikro-Clear Bot Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first `mikroclear-bot` control-plane slice: reusable bot settings/auth/dispatcher modules and a read-only Telegram `/status` command.

**Architecture:** Keep bot code inside the existing `mikroclear` package under `mikroclear.bot`. Build small pure modules first, then wire `/status` into the current legacy Telegram polling loop so production behavior changes only when Telegram polling receives a message update. Keep write-capable modules out of this plan.

**Tech Stack:** Python 3.11+, unittest, existing `requests` Telegram calls, existing Mikro-Clear settings and RouterOS runtime state.

## Global Constraints

- Do not deploy to production SELKS as part of this plan.
- Do not create or change MikroTik firewall filter rules.
- Do not manage NAT, routes, system users, RouterOS services, or global firewall rules.
- Do not add production credentials to the repository.
- `/status` must not include Telegram tokens, RouterOS passwords, cookies, authorization headers, or raw environment content.
- Unknown chats must receive no privileged status data.
- Bot dry-run mode must default to enabled and appear in `/status`.

---

## File Structure

- `src/mikroclear/bot/__init__.py`: bot package marker and exported names.
- `src/mikroclear/bot/settings.py`: bot-specific settings loaded from environment variables.
- `src/mikroclear/bot/auth.py`: read/write authorization decisions for Telegram chat IDs.
- `src/mikroclear/bot/modules/status.py`: pure `/status` response formatter.
- `src/mikroclear/bot/dispatcher.py`: Telegram message command dispatch.
- `src/mikroclear/legacy.py`: minimal integration with current `process_telegram_updates()`.
- `tests/test_bot_settings.py`: bot settings tests.
- `tests/test_bot_auth.py`: authorization tests.
- `tests/test_bot_status.py`: status formatter tests.
- `tests/test_bot_dispatcher.py`: dispatcher tests.
- `tests/test_telegram_commands.py`: legacy polling integration tests.
- `tests/test_project_structure.py`: import-path coverage for new package.

## Task 1: Add Bot Settings

**Files:**
- Create: `src/mikroclear/bot/__init__.py`
- Create: `src/mikroclear/bot/settings.py`
- Test: `tests/test_bot_settings.py`
- Modify: `tests/test_project_structure.py`

**Interfaces:**
- Produces: `BotSettings`
- Produces: `BotSettings.from_env() -> BotSettings`
- Produces: `parse_chat_ids(value: str) -> tuple[str, ...]`

- [ ] **Step 1: Write failing tests**

Create `tests/test_bot_settings.py`:

```python
import os
from unittest import TestCase
from unittest.mock import patch

from mikroclear.bot.settings import BotSettings, parse_chat_ids


class BotSettingsTests(TestCase):
    def test_parse_chat_ids_trims_and_drops_empty_values(self):
        self.assertEqual(parse_chat_ids(" 10,20,, 30 "), ("10", "20", "30"))

    def test_defaults_are_safe(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = BotSettings.from_env()

        self.assertFalse(settings.enable)
        self.assertTrue(settings.dry_run)
        self.assertEqual(settings.allowed_chat_ids, ())
        self.assertEqual(settings.admin_chat_ids, ())
        self.assertEqual(settings.modules, ("status", "asset_resolver", "mangle_control", "parental_control"))

    def test_env_overrides(self):
        env = {
            "MIKROCLEAR_BOT_ENABLE": "true",
            "MIKROCLEAR_BOT_DRY_RUN": "false",
            "MIKROCLEAR_BOT_ALLOWED_CHAT_IDS": "chat-1,chat-2",
            "MIKROCLEAR_BOT_ADMIN_CHAT_IDS": "admin-1",
            "MIKROCLEAR_BOT_MODULES": "status,asset_resolver",
            "MIKROCLEAR_BOT_AUDIT_LOG": "/tmp/mikroclear-bot-audit.log",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = BotSettings.from_env()

        self.assertTrue(settings.enable)
        self.assertFalse(settings.dry_run)
        self.assertEqual(settings.allowed_chat_ids, ("chat-1", "chat-2"))
        self.assertEqual(settings.admin_chat_ids, ("admin-1",))
        self.assertEqual(settings.modules, ("status", "asset_resolver"))
        self.assertEqual(settings.audit_log, "/tmp/mikroclear-bot-audit.log")
```

Add to `tests/test_project_structure.py` inside `test_runtime_skeleton_modules_are_importable`:

```python
        import mikroclear.bot.auth
        import mikroclear.bot.dispatcher
        import mikroclear.bot.modules.status
        import mikroclear.bot.settings
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/python -m unittest tests.test_bot_settings tests.test_project_structure
```

Expected: fail because `mikroclear.bot` modules do not exist.

- [ ] **Step 3: Implement settings**

Create `src/mikroclear/bot/__init__.py`:

```python
"""Telegram control-plane modules for Mikro-Clear."""

__all__ = ["auth", "dispatcher", "settings"]
```

Create `src/mikroclear/bot/settings.py`:

```python
"""Settings for the Mikro-Clear Telegram control plane."""

from dataclasses import dataclass

from mikroclear.config import env_bool, env_csv, env_str


def parse_chat_ids(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class BotSettings:
    enable: bool = False
    dry_run: bool = True
    admin_chat_ids: tuple[str, ...] = ()
    allowed_chat_ids: tuple[str, ...] = ()
    modules: tuple[str, ...] = ("status", "asset_resolver", "mangle_control", "parental_control")
    audit_log: str = "/var/lib/mikroclear/bot-audit.log"

    @classmethod
    def from_env(cls) -> "BotSettings":
        return cls(
            enable=env_bool("MIKROCLEAR_BOT_ENABLE", False),
            dry_run=env_bool("MIKROCLEAR_BOT_DRY_RUN", True),
            admin_chat_ids=parse_chat_ids(env_str("MIKROCLEAR_BOT_ADMIN_CHAT_IDS", "")),
            allowed_chat_ids=parse_chat_ids(env_str("MIKROCLEAR_BOT_ALLOWED_CHAT_IDS", "")),
            modules=env_csv(
                "MIKROCLEAR_BOT_MODULES",
                ("status", "asset_resolver", "mangle_control", "parental_control"),
            ),
            audit_log=env_str("MIKROCLEAR_BOT_AUDIT_LOG", "/var/lib/mikroclear/bot-audit.log"),
        )


__all__ = ["BotSettings", "parse_chat_ids"]
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_bot_settings tests.test_project_structure
```

Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add src/mikroclear/bot/__init__.py src/mikroclear/bot/settings.py tests/test_bot_settings.py tests/test_project_structure.py
git commit -m "Add Mikro-Clear bot settings"
```

## Task 2: Add Bot Authorization

**Files:**
- Create: `src/mikroclear/bot/auth.py`
- Test: `tests/test_bot_auth.py`

**Interfaces:**
- Consumes: `BotSettings`
- Produces: `BotAuth`
- Produces: `BotAuth.can_read(chat_id: object) -> bool`
- Produces: `BotAuth.can_write(chat_id: object) -> bool`

- [ ] **Step 1: Write failing tests**

Create `tests/test_bot_auth.py`:

```python
from unittest import TestCase

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.settings import BotSettings


class BotAuthTests(TestCase):
    def test_admin_can_read_and_write(self):
        auth = BotAuth(BotSettings(admin_chat_ids=("admin",), allowed_chat_ids=("reader",)))

        self.assertTrue(auth.can_read("admin"))
        self.assertTrue(auth.can_write("admin"))

    def test_allowed_chat_can_read_but_not_write(self):
        auth = BotAuth(BotSettings(admin_chat_ids=("admin",), allowed_chat_ids=("reader",)))

        self.assertTrue(auth.can_read("reader"))
        self.assertFalse(auth.can_write("reader"))

    def test_unknown_chat_cannot_read_or_write(self):
        auth = BotAuth(BotSettings(admin_chat_ids=("admin",), allowed_chat_ids=("reader",)))

        self.assertFalse(auth.can_read("unknown"))
        self.assertFalse(auth.can_write("unknown"))

    def test_legacy_telegram_chat_is_allowed_for_read(self):
        auth = BotAuth(BotSettings(), legacy_chat_id="legacy-chat")

        self.assertTrue(auth.can_read("legacy-chat"))
        self.assertFalse(auth.can_write("legacy-chat"))
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/python -m unittest tests.test_bot_auth
```

Expected: fail because `mikroclear.bot.auth` does not exist.

- [ ] **Step 3: Implement auth**

Create `src/mikroclear/bot/auth.py`:

```python
"""Authorization helpers for Telegram bot actions."""

from dataclasses import dataclass
from typing import Any

from mikroclear.bot.settings import BotSettings


@dataclass(frozen=True)
class BotAuth:
    settings: BotSettings
    legacy_chat_id: str = ""

    def _chat_id(self, chat_id: Any) -> str:
        return str(chat_id).strip()

    def can_read(self, chat_id: Any) -> bool:
        value = self._chat_id(chat_id)
        if not value:
            return False
        if value in self.settings.admin_chat_ids:
            return True
        if value in self.settings.allowed_chat_ids:
            return True
        return bool(self.legacy_chat_id and value == str(self.legacy_chat_id))

    def can_write(self, chat_id: Any) -> bool:
        value = self._chat_id(chat_id)
        return bool(value and value in self.settings.admin_chat_ids)


__all__ = ["BotAuth"]
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_bot_auth
```

Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add src/mikroclear/bot/auth.py tests/test_bot_auth.py
git commit -m "Add Mikro-Clear bot authorization"
```

## Task 3: Add Status Formatter

**Files:**
- Create: `src/mikroclear/bot/modules/__init__.py`
- Create: `src/mikroclear/bot/modules/status.py`
- Test: `tests/test_bot_status.py`

**Interfaces:**
- Consumes: `BotSettings`
- Produces: `StatusSnapshot`
- Produces: `format_status(snapshot: StatusSnapshot) -> str`

- [ ] **Step 1: Write failing tests**

Create `tests/test_bot_status.py`:

```python
from unittest import TestCase

from mikroclear.bot.modules.status import StatusSnapshot, format_status
from mikroclear.bot.settings import BotSettings


class BotStatusTests(TestCase):
    def test_format_status_contains_operational_fields(self):
        snapshot = StatusSnapshot(
            uptime_seconds=3661,
            routeros_connected=True,
            routeros_connected_seconds=61,
            eve_path="/var/log/eve.json",
            block_list_name="Suricata",
            monitor_only=False,
            telegram_unblock_enabled=True,
            state_dir="/var/lib/mikroclear",
            bot_settings=BotSettings(dry_run=True, modules=("status", "asset_resolver")),
        )

        text = format_status(snapshot)

        self.assertIn("Mikro-Clear status", text)
        self.assertIn("uptime: 1h 1m 1s", text)
        self.assertIn("routeros: connected for 1m 1s", text)
        self.assertIn("eve: /var/log/eve.json", text)
        self.assertIn("address-list: Suricata", text)
        self.assertIn("monitor-only: off", text)
        self.assertIn("bot dry-run: on", text)
        self.assertIn("modules: status, asset_resolver", text)

    def test_format_status_masks_secret_like_values(self):
        snapshot = StatusSnapshot(
            uptime_seconds=0,
            routeros_connected=False,
            routeros_connected_seconds=0,
            eve_path="/tmp/bot123456:ABC_def-123/eve.json",
            block_list_name="token=abc123",
            monitor_only=True,
            telegram_unblock_enabled=False,
            state_dir="/var/lib/mikroclear",
            bot_settings=BotSettings(),
        )

        text = format_status(snapshot)

        self.assertNotIn("ABC_def-123", text)
        self.assertIn("/bot***MASKED***/", text)
        self.assertIn("token=abc123", text)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/python -m unittest tests.test_bot_status
```

Expected: fail because `mikroclear.bot.modules.status` does not exist.

- [ ] **Step 3: Implement status formatter**

Create `src/mikroclear/bot/modules/__init__.py`:

```python
"""Bot feature modules."""
```

Create `src/mikroclear/bot/modules/status.py`:

```python
"""Read-only Mikro-Clear status command."""

from dataclasses import dataclass

from mikroclear.bot.settings import BotSettings
from mikroclear.security import mask_telegram_bot_token


@dataclass(frozen=True)
class StatusSnapshot:
    uptime_seconds: int
    routeros_connected: bool
    routeros_connected_seconds: int
    eve_path: str
    block_list_name: str
    monitor_only: bool
    telegram_unblock_enabled: bool
    state_dir: str
    bot_settings: BotSettings


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def on_off(value: bool) -> str:
    return "on" if value else "off"


def format_status(snapshot: StatusSnapshot) -> str:
    if snapshot.routeros_connected:
        routeros = f"connected for {format_duration(snapshot.routeros_connected_seconds)}"
    else:
        routeros = "disconnected"

    lines = [
        "Mikro-Clear status",
        f"uptime: {format_duration(snapshot.uptime_seconds)}",
        f"routeros: {routeros}",
        f"eve: {snapshot.eve_path}",
        f"address-list: {snapshot.block_list_name}",
        f"monitor-only: {on_off(snapshot.monitor_only)}",
        f"telegram unblock: {on_off(snapshot.telegram_unblock_enabled)}",
        f"bot dry-run: {on_off(snapshot.bot_settings.dry_run)}",
        f"modules: {', '.join(snapshot.bot_settings.modules)}",
        f"state-dir: {snapshot.state_dir}",
    ]
    return mask_telegram_bot_token("\n".join(lines))


__all__ = ["StatusSnapshot", "format_duration", "format_status"]
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_bot_status
```

Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add src/mikroclear/bot/modules/__init__.py src/mikroclear/bot/modules/status.py tests/test_bot_status.py
git commit -m "Add Mikro-Clear bot status formatter"
```

## Task 4: Add Dispatcher

**Files:**
- Create: `src/mikroclear/bot/dispatcher.py`
- Test: `tests/test_bot_dispatcher.py`

**Interfaces:**
- Consumes: `BotAuth`
- Consumes: `StatusSnapshot`
- Consumes: `format_status(snapshot: StatusSnapshot) -> str`
- Produces: `BotCommandResult`
- Produces: `dispatch_message(text: object, chat_id: object, auth: BotAuth, status_snapshot: Callable[[], StatusSnapshot]) -> BotCommandResult | None`

- [ ] **Step 1: Write failing tests**

Create `tests/test_bot_dispatcher.py`:

```python
from unittest import TestCase

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.dispatcher import dispatch_message
from mikroclear.bot.modules.status import StatusSnapshot
from mikroclear.bot.settings import BotSettings


def snapshot() -> StatusSnapshot:
    return StatusSnapshot(
        uptime_seconds=1,
        routeros_connected=False,
        routeros_connected_seconds=0,
        eve_path="/var/log/eve.json",
        block_list_name="Suricata",
        monitor_only=True,
        telegram_unblock_enabled=False,
        state_dir="/var/lib/mikroclear",
        bot_settings=BotSettings(modules=("status",)),
    )


class BotDispatcherTests(TestCase):
    def test_dispatches_status_for_allowed_chat(self):
        auth = BotAuth(BotSettings(allowed_chat_ids=("chat-1",)))

        result = dispatch_message("/status", "chat-1", auth, snapshot)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertFalse(result.alert)
        self.assertIn("Mikro-Clear status", result.text)

    def test_rejects_status_for_unknown_chat_without_privileged_data(self):
        auth = BotAuth(BotSettings(allowed_chat_ids=("chat-1",)))

        result = dispatch_message("/status", "unknown", auth, snapshot)

        self.assertIsNotNone(result)
        self.assertTrue(result.handled)
        self.assertTrue(result.alert)
        self.assertEqual(result.text, "Unauthorized")

    def test_ignores_unknown_command(self):
        auth = BotAuth(BotSettings(allowed_chat_ids=("chat-1",)))

        self.assertIsNone(dispatch_message("/unknown", "chat-1", auth, snapshot))
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/python -m unittest tests.test_bot_dispatcher
```

Expected: fail because `mikroclear.bot.dispatcher` does not exist.

- [ ] **Step 3: Implement dispatcher**

Create `src/mikroclear/bot/dispatcher.py`:

```python
"""Telegram message dispatcher for Mikro-Clear bot commands."""

from dataclasses import dataclass
from typing import Any, Callable

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.modules.status import StatusSnapshot, format_status


@dataclass(frozen=True)
class BotCommandResult:
    text: str
    handled: bool = True
    alert: bool = False


def _command_name(text: Any) -> str:
    value = str(text or "").strip()
    if not value.startswith("/"):
        return ""
    return value.split()[0].split("@", 1)[0].lower()


def dispatch_message(
    text: Any,
    chat_id: Any,
    auth: BotAuth,
    status_snapshot: Callable[[], StatusSnapshot],
) -> BotCommandResult | None:
    command = _command_name(text)
    if command != "/status":
        return None
    if not auth.can_read(chat_id):
        return BotCommandResult("Unauthorized", alert=True)
    return BotCommandResult(format_status(status_snapshot()))


__all__ = ["BotCommandResult", "dispatch_message"]
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_bot_dispatcher
```

Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add src/mikroclear/bot/dispatcher.py tests/test_bot_dispatcher.py
git commit -m "Add Mikro-Clear bot dispatcher"
```

## Task 5: Wire `/status` Into Telegram Polling

**Files:**
- Modify: `src/mikroclear/legacy.py`
- Test: `tests/test_telegram_commands.py`

**Interfaces:**
- Consumes: `BotSettings.from_env() -> BotSettings`
- Consumes: `BotAuth`
- Consumes: `StatusSnapshot`
- Consumes: `dispatch_message(...) -> BotCommandResult | None`
- Produces: `build_status_snapshot() -> StatusSnapshot`
- Updates: `process_telegram_updates()` handles Telegram `message` updates.

- [ ] **Step 1: Write failing integration tests**

Create `tests/test_telegram_commands.py`:

```python
import types
import unittest
from unittest.mock import patch


def fake_pyinotify_module() -> types.SimpleNamespace:
    return types.SimpleNamespace(ProcessEvent=object)


class FakeMessageResponse:
    status_code = 200
    text = "{}"

    def __init__(self, chat_id="chat-1", text="/status"):
        self.chat_id = chat_id
        self.message_text = text

    def json(self):
        return {
            "ok": True,
            "result": [
                {
                    "update_id": 99,
                    "message": {
                        "text": self.message_text,
                        "chat": {"id": self.chat_id},
                    },
                }
            ],
        }


class LegacyTelegramCommandTests(unittest.TestCase):
    def import_legacy(self):
        with patch.dict("sys.modules", {"pyinotify": fake_pyinotify_module()}):
            from mikroclear import legacy

        return legacy

    def test_process_updates_sends_status_to_allowed_chat(self):
        legacy = self.import_legacy()

        with (
            patch.object(legacy, "ENABLE_TELEGRAM", True),
            patch.object(legacy, "TELEGRAM_UNBLOCK_ENABLE", True),
            patch.object(legacy, "TELEGRAM_TOKEN", "token"),
            patch.object(legacy, "TELEGRAM_CHATID", "chat-1"),
            patch.object(legacy, "telegram_update_offset", 0),
            patch.object(legacy.requests, "get", return_value=FakeMessageResponse()),
            patch.object(legacy, "send_telegram_message", return_value=types.SimpleNamespace(ok=True, response_text="ok")) as send,
        ):
            legacy.process_telegram_updates()

        self.assertEqual(send.call_args.kwargs["chat_id"], "chat-1")
        self.assertIn("Mikro-Clear status", send.call_args.kwargs["text"])

    def test_process_updates_rejects_status_from_unknown_chat(self):
        legacy = self.import_legacy()

        with (
            patch.object(legacy, "ENABLE_TELEGRAM", True),
            patch.object(legacy, "TELEGRAM_UNBLOCK_ENABLE", True),
            patch.object(legacy, "TELEGRAM_TOKEN", "token"),
            patch.object(legacy, "TELEGRAM_CHATID", "chat-1"),
            patch.object(legacy, "telegram_update_offset", 0),
            patch.object(legacy.requests, "get", return_value=FakeMessageResponse(chat_id="unknown")),
            patch.object(legacy, "send_telegram_message", return_value=types.SimpleNamespace(ok=True, response_text="ok")) as send,
            patch.object(legacy, "log") as log,
        ):
            legacy.process_telegram_updates()

        send.assert_not_called()
        self.assertIn("Rejected Telegram command from unauthorized chat unknown", log.call_args[0][0])
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/bin/python -m unittest tests.test_telegram_commands
```

Expected: fail because `process_telegram_updates()` ignores message updates.

- [ ] **Step 3: Import bot modules in `legacy.py`**

Add near existing Telegram imports in `src/mikroclear/legacy.py`:

```python
try:
    from mikroclear.bot.auth import BotAuth
    from mikroclear.bot.dispatcher import dispatch_message
    from mikroclear.bot.modules.status import StatusSnapshot
    from mikroclear.bot.settings import BotSettings
except Exception:  # pragma: no cover - production single-file fallback
    BotAuth = None  # type: ignore
    BotSettings = None  # type: ignore
    StatusSnapshot = None  # type: ignore
    dispatch_message = None  # type: ignore
```

- [ ] **Step 4: Add snapshot builder in `legacy.py`**

Add after `get_router_client()` or near Telegram update helpers:

```python
def build_status_snapshot() -> Any:
    bot_settings = BotSettings.from_env() if BotSettings is not None else None
    client = router_client
    connected_at = float(getattr(client, "connected_at", 0.0) or 0.0)
    connected = bool(getattr(client, "api", None))
    connected_seconds = int(time() - connected_at) if connected and connected_at else 0
    uptime_seconds = int(time() - START_TIME)
    return StatusSnapshot(
        uptime_seconds=uptime_seconds,
        routeros_connected=connected,
        routeros_connected_seconds=connected_seconds,
        eve_path=FILEPATH,
        block_list_name=BLOCK_LIST_NAME,
        monitor_only=MONITOR_ONLY,
        telegram_unblock_enabled=TELEGRAM_UNBLOCK_ENABLE,
        state_dir=STATE_DIR,
        bot_settings=bot_settings,
    )
```

- [ ] **Step 5: Handle message updates in `process_telegram_updates()`**

Change `allowed_updates`:

```python
"allowed_updates": ujson.dumps(["callback_query", "message"])
```

Inside the update loop, before callback handling:

```python
        message_update = update.get("message") or {}
        if message_update:
            chat = message_update.get("chat") or {}
            chat_id = str(chat.get("id", ""))
            auth = BotAuth(BotSettings.from_env(), legacy_chat_id=str(TELEGRAM_CHATID))
            result = dispatch_message(
                message_update.get("text", ""),
                chat_id,
                auth,
                build_status_snapshot,
            )
            if result is not None:
                if result.alert and result.text == "Unauthorized":
                    log(f"Rejected Telegram command from unauthorized chat {chat_id}")
                    continue
                send_telegram_message(
                    token=TELEGRAM_TOKEN,
                    chat_id=chat_id,
                    text=result.text,
                    timeout=TELEGRAM_TIMEOUT,
                )
                continue
```

If imports are unavailable, guard this block with:

```python
            if BotAuth is None or BotSettings is None or dispatch_message is None:
                continue
```

- [ ] **Step 6: Run focused tests**

```bash
.venv/bin/python -m unittest tests.test_telegram_commands tests.test_telegram_unblock tests.test_bot_dispatcher tests.test_bot_status
```

Expected: OK.

- [ ] **Step 7: Commit**

```bash
git add src/mikroclear/legacy.py tests/test_telegram_commands.py
git commit -m "Wire Telegram status command"
```

## Task 6: Full Verification

**Files:**
- Read: all files changed in Tasks 1-5.

**Interfaces:**
- Consumes: all previous task outputs.
- Produces: verified local working tree ready for review.

- [ ] **Step 1: Run full tests**

```bash
.venv/bin/python -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 2: Run compile check**

```bash
git ls-files '*.py' | xargs .venv/bin/python -m py_compile
```

Expected: exit 0 with no output.

- [ ] **Step 3: Run secret-pattern check**

```bash
git grep -n -I -E '(BEGIN (RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|[0-9]{6,}:[A-Za-z0-9_-]{30,})' -- .
```

Expected: exit 1 with no output.

- [ ] **Step 4: Check Git status**

```bash
git status --short
```

Expected: clean after commits.

## Self-Review

- Spec coverage: this plan covers the first implementation slice from the design: bot settings, auth, dispatcher, `/status`, safe unknown-chat handling, dry-run visibility, and no production deploy.
- Deferred by design: `asset_resolver`, `parental_control`, and `mangle_control` implementation are not in this plan because they are independent write-capable modules and need their own dry-run/audit tests.
- Placeholder scan: no unfinished markers or unspecified implementation steps are intentionally left.
- Type consistency: `BotSettings`, `BotAuth`, `StatusSnapshot`, `BotCommandResult`, and `dispatch_message` signatures are defined before use.
