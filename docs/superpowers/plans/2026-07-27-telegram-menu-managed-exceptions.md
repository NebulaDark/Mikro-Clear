# Telegram Hierarchical Menu And Managed Exceptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать единое кнопочное Telegram-меню Mikro-Clear, исправить обычный Unblock и добавить постоянные управляемые исключения только для RFC1918 IPv4 с немедленным удалением текущей блокировки RouterOS.

**Architecture:** Единственный существующий `TelegramUpdatePoller` маршрутизирует launcher, навигационные, Mangle, whitelist и обычные Unblock callbacks в отдельные handlers. Системный whitelist остаётся неизменяемым env-источником, управляемые исключения атомарно хранятся в `<state-dir>/dynamic-whitelist.json`, а alert pipeline получает их объединённый актуальный snapshot перед каждой обработкой. Все Telegram/RouterOS тесты используют локальные doubles.

**Tech Stack:** Python 3.11+, standard library (`dataclasses`, `ipaddress`, `json`, `os`, `pathlib`, `tempfile`, `threading`), `requests`, `librouteros`, `unittest`, Telegram Bot API HTTP boundary.

## Global Constraints

- Не создавать второй Telegram poller, второй service lifecycle или второй RouterOS client lifecycle.
- Сохранить команды `/status` и `/mangle` как fallback.
- Сохранить текст alert, ссылки `AbuseIPDB`/`VirusTotal`, точную кнопку `🔓 Unblock <IP>` и двухшаговый Unblock.
- Добавлять из Telegram только точные IPv4 из `10.0.0.0/8`, `172.16.0.0/12` и `192.168.0.0/16`; публичные IP, IPv6 и CIDR запрещены.
- Системный `MIKROCLEAR_WHITELIST_IPS` доступен из бота только для чтения.
- `MIKROCLEAR_TELEGRAM_WHITELIST_CONTROL_ENABLE=false` и `MIKROCLEAR_BOT_DRY_RUN=true` остаются безопасными значениями по умолчанию.
- Dry-run не изменяет RouterOS и state-файлы, но пишет audit result.
- Callback повторно проверяет admin authorization, feature flags, target scope, TTL и requester binding.
- После мутации UI показывает только повторно прочитанное фактическое состояние; optimistic icon changes запрещены.
- Установка и воспроизведение выполняются из Git и `scripts/install-selks.sh`; production deploy/restart/live mutation остаются отдельным approval-gated этапом.
- Не добавлять runtime-зависимости; MCP остаётся вне runtime и installation path.
- После каждого task: focused tests, отдельный коммит, отчёт «сделано / осталось».

---

## File Map

### New production files

- `src/mikroclear/state/dynamic_whitelist.py` — валидируемое атомарное persistent-хранилище управляемых IP.
- `src/mikroclear/suricata/whitelist_policy.py` — объединение системного и управляемого whitelist.
- `src/mikroclear/bot/audit.py` — приватный JSONL audit writer для write-capable bot actions.
- `src/mikroclear/bot/menu.py` — чистые menu models, registry, launcher и route parsing.
- `src/mikroclear/bot/modules/exceptions.py` — чистое форматирование и пагинация экрана исключений.
- `src/mikroclear/telegram/menu_handler.py` — `/start`, `/menu`, launcher и `menu:v1:*`.
- `src/mikroclear/telegram/whitelist_actions.py` — persistent single-use whitelist action tokens.
- `src/mikroclear/telegram/whitelist_handler.py` — add/unblock, retry, list и remove workflows.

### New tests

- `tests/test_dynamic_whitelist.py`
- `tests/test_whitelist_policy.py`
- `tests/test_bot_audit.py`
- `tests/test_bot_menu.py`
- `tests/test_telegram_menu.py`
- `tests/test_telegram_whitelist.py`

### Existing files to modify

- `src/mikroclear/telegram/unblock_handler.py`
- `src/mikroclear/settings.py`
- `src/mikroclear/bot/settings.py`
- `src/mikroclear/alert_processor.py`
- `src/mikroclear/runtime/providers.py`
- `src/mikroclear/runtime/status_snapshot.py`
- `src/mikroclear/bot/modules/status.py`
- `src/mikroclear/bot/mangle_control.py`
- `src/mikroclear/telegram/mangle_handler.py`
- `src/mikroclear/telegram/notify.py`
- `src/mikroclear/telegram/polling.py`
- `config/mikroclear.env.example`
- `docs/ru/env-reference.md`
- `docs/ru/install-from-github.md`
- `docs/ru/install-test-reproduction.md`
- соответствующие существующие `tests/test_*.py`.

---

### Task 1: Исправить подтверждённую перестановку аргументов Unblock

**Files:**
- Modify: `src/mikroclear/telegram/unblock_handler.py:28-55`
- Modify: `tests/test_telegram_unblock.py:226-245`

**Interfaces:**
- Consumes: `remove_from_address_list(address_list: Any, list_name: str, address: str) -> int`.
- Produces: обычный `TelegramUnblockHandler.handle_unblock_action()` удаляет точный IP только из указанного списка.

- [ ] **Step 1: Write the failing regression test**

Добавить fake client и проверку контракта:

```python
def test_unblock_passes_list_name_before_address(self):
    address_list = object()

    class Client:
        def paths(self):
            return address_list, None, object()

        def run_with_reconnect(self, _name, operation):
            return operation()

    with patch(
        "mikroclear.telegram.unblock_handler.remove_from_address_list",
        return_value=1,
    ) as remove:
        handler = TelegramUnblockHandler(
            Settings(whitelist_ips=()),
            get_router_client=lambda: Client(),
            log=Mock(),
        )
        result = handler.handle_unblock_action(
            {
                "wanted_ip": "192.168.98.200",
                "list_name": "Suricata",
                "sid": "2025701",
            }
        )

    remove.assert_called_once_with(address_list, "Suricata", "192.168.98.200")
    self.assertTrue(result.success)
```

- [ ] **Step 2: Run the regression test and prove the current failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_telegram_unblock.TelegramUnblockFlowTests.test_unblock_passes_list_name_before_address
```

Expected: `FAIL`; actual call contains `("192.168.98.200", "Suricata")` in the wrong order.

- [ ] **Step 3: Apply the minimal fix**

Replace the call inside `remove_batch()` with:

```python
return remove_from_address_list(target_list, list_name, wanted_ip) > 0
```

- [ ] **Step 4: Run focused Unblock and RouterOS helper tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_telegram_unblock tests.test_routeros_client
```

Expected: all tests pass; the new regression test proves exact argument order.

- [ ] **Step 5: Commit and report**

```bash
git add src/mikroclear/telegram/unblock_handler.py tests/test_telegram_unblock.py
git commit -m "Fix Telegram unblock address-list lookup"
```

Report: исправление, test command/result, remaining Task 2-10.

---

### Task 2: Добавить настройки и атомарное managed-whitelist хранилище

**Files:**
- Create: `src/mikroclear/state/dynamic_whitelist.py`
- Create: `tests/test_dynamic_whitelist.py`
- Modify: `src/mikroclear/settings.py:24-56,120-169`
- Modify: `src/mikroclear/bot/settings.py:12-34`
- Modify: `tests/test_settings.py:42-66,91-117`
- Modify: `tests/test_bot_settings.py:8-45`

**Interfaces:**
- Produces: `is_managed_private_ipv4(value: Any) -> bool`.
- Produces: `DynamicWhitelistStore(path: Path)` with `snapshot() -> tuple[str, ...]`, `contains(address: str) -> bool`, `add(address: str) -> bool`, `remove(address: str) -> bool`.
- Produces settings: `telegram_whitelist_control_enable: bool`, `dynamic_whitelist_file: str`, `telegram_whitelist_state_file: str`.
- Produces module id: `whitelist_control`.

- [ ] **Step 1: Write failing settings and store tests**

Create tests with these exact cases:

```python
class ManagedPrivateIpv4Tests(TestCase):
    def test_accepts_only_rfc1918_exact_ipv4(self):
        for value in ("10.0.0.1", "172.16.0.1", "172.31.255.254", "192.168.98.200"):
            self.assertTrue(is_managed_private_ipv4(value), value)
        for value in (
            "172.32.0.1",
            "8.8.8.8",
            "127.0.0.1",
            "169.254.1.1",
            "192.168.1.0/24",
            "fe80::1",
            "",
        ):
            self.assertFalse(is_managed_private_ipv4(value), value)


class DynamicWhitelistStoreTests(TestCase):
    def test_add_remove_are_sorted_persistent_and_idempotent(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "dynamic-whitelist.json")
            store = DynamicWhitelistStore(path)
            self.assertTrue(store.add("192.168.98.200"))
            self.assertFalse(store.add("192.168.98.200"))
            self.assertTrue(store.add("10.0.0.9"))
            self.assertEqual(store.snapshot(), ("10.0.0.9", "192.168.98.200"))
            self.assertEqual(DynamicWhitelistStore(path).snapshot(), store.snapshot())
            self.assertTrue(store.remove("192.168.98.200"))
            self.assertFalse(store.remove("192.168.98.200"))

    def test_invalid_existing_document_fails_closed(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "dynamic-whitelist.json")
            path.write_text('{"version":1,"addresses":["8.8.8.8"]}', encoding="utf-8")
            with self.assertRaises(DynamicWhitelistError):
                DynamicWhitelistStore(path)

    def test_write_is_private_and_leaves_no_temp_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "dynamic-whitelist.json")
            DynamicWhitelistStore(path).add("10.0.0.8")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*")), [])

    def test_concurrent_adds_do_not_lose_entries(self):
        with TemporaryDirectory() as tmp:
            store = DynamicWhitelistStore(Path(tmp, "dynamic-whitelist.json"))
            addresses = tuple(f"10.0.0.{index}" for index in range(1, 17))
            threads = [
                threading.Thread(target=store.add, args=(address,))
                for address in addresses
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(store.snapshot(), tuple(sorted(addresses)))
```

Extend settings assertions:

```python
self.assertFalse(settings.telegram_whitelist_control_enable)
self.assertEqual(
    settings.dynamic_whitelist_file,
    str(Path("/tmp/mikroclear-state/dynamic-whitelist.json").resolve()),
)
self.assertEqual(
    settings.telegram_whitelist_state_file,
    str(Path("/tmp/mikroclear-state/telegram-whitelist-actions.json").resolve()),
)
self.assertIn("whitelist_control", BotSettings.from_env().modules)
```

- [ ] **Step 2: Run tests and verify missing interfaces**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_dynamic_whitelist tests.test_settings tests.test_bot_settings
```

Expected: import/attribute failures for the new store and settings.

- [ ] **Step 3: Implement validation and atomic storage**

Implement this public structure; `_persist()` must use `mkstemp`, `fchmod(0o600)`, `flush`, `fsync` and `os.replace`:

```python
RFC1918_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


class DynamicWhitelistError(RuntimeError):
    pass


def is_managed_private_ipv4(value: Any) -> bool:
    try:
        address = ipaddress.ip_address(str(value))
    except ValueError:
        return False
    return isinstance(address, ipaddress.IPv4Address) and any(
        address in network for network in RFC1918_NETWORKS
    )


class DynamicWhitelistStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._addresses = self._load()

    def snapshot(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._addresses))

    def contains(self, address: str) -> bool:
        return str(address) in self.snapshot()

    def add(self, address: str) -> bool:
        if not is_managed_private_ipv4(address):
            raise ValueError("managed whitelist accepts only exact RFC1918 IPv4")
        with self._lock:
            if address in self._addresses:
                return False
            updated = set(self._addresses)
            updated.add(address)
            self._persist(updated)
            self._addresses = updated
            return True

    def remove(self, address: str) -> bool:
        with self._lock:
            if address not in self._addresses:
                return False
            updated = set(self._addresses)
            updated.remove(address)
            self._persist(updated)
            self._addresses = updated
            return True

    def _load(self) -> set[str]:
        if not self.path.exists():
            return set()
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DynamicWhitelistError(
                f"cannot read managed whitelist: {type(exc).__name__}"
            ) from exc
        if not isinstance(document, dict) or set(document) != {"version", "addresses"}:
            raise DynamicWhitelistError("managed whitelist schema is invalid")
        if document["version"] != 1 or not isinstance(document["addresses"], list):
            raise DynamicWhitelistError("managed whitelist version or addresses is invalid")
        values = document["addresses"]
        if any(not isinstance(value, str) or not is_managed_private_ipv4(value) for value in values):
            raise DynamicWhitelistError("managed whitelist contains an invalid address")
        if len(values) != len(set(values)):
            raise DynamicWhitelistError("managed whitelist contains duplicates")
        return set(values)

    def _persist(self, addresses: set[str]) -> None:
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
                    {"version": 1, "addresses": sorted(addresses)},
                    handle,
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
```

Imports are `ipaddress`, `json`, `os`, `tempfile`, `threading`, `Path` and
`Any`. The implementation above treats a missing file as empty and rejects
malformed JSON, unknown fields/version, duplicates, non-strings or invalid
addresses.

Add settings:

```python
telegram_whitelist_control_enable: bool = False
dynamic_whitelist_file: str = "/var/lib/mikroclear/dynamic-whitelist.json"
telegram_whitelist_state_file: str = "/var/lib/mikroclear/telegram-whitelist-actions.json"
```

Derive both paths from `MIKROCLEAR_STATE_DIR`; load the flag from
`MIKROCLEAR_TELEGRAM_WHITELIST_CONTROL_ENABLE`. Add `whitelist_control` to the
safe module registry default while leaving the feature flag off.

- [ ] **Step 4: Run tests twice to prove persistence determinism**

Run twice:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_dynamic_whitelist tests.test_settings tests.test_bot_settings
```

Expected: both runs pass and no temp artifacts remain.

- [ ] **Step 5: Commit and report**

```bash
git add \
  src/mikroclear/state/dynamic_whitelist.py src/mikroclear/settings.py \
  src/mikroclear/bot/settings.py tests/test_dynamic_whitelist.py \
  tests/test_settings.py tests/test_bot_settings.py
git commit -m "Add persistent managed whitelist store"
```

---

### Task 3: Подключить effective whitelist к alert и restore paths

**Files:**
- Create: `src/mikroclear/suricata/whitelist_policy.py`
- Create: `tests/test_whitelist_policy.py`
- Modify: `src/mikroclear/alert_processor.py:24-33,69-149,152-207`
- Modify: `src/mikroclear/runtime/providers.py:44-99,158-183`
- Modify: `tests/test_alert_processor.py`
- Modify: `tests/test_state_store.py`

**Interfaces:**
- Consumes: `DynamicWhitelistStore.snapshot()`.
- Produces: `WhitelistPolicy(system_entries, managed_store).snapshot()` and `.contains(address)`.
- Extends: `AlertProcessorConfig.whitelist_provider: Callable[[], tuple[str, ...]] | None`.

- [ ] **Step 1: Write failing policy, alert-suppression and restore tests**

```python
def test_policy_merges_system_cidr_and_current_managed_snapshot(self):
    store = Mock()
    store.snapshot.side_effect = [
        ("192.168.98.200",),
        ("192.168.98.200", "10.0.0.9"),
    ]
    policy = WhitelistPolicy(("172.16.0.0/12",), store)
    self.assertEqual(policy.snapshot(), ("172.16.0.0/12", "192.168.98.200"))
    self.assertTrue(policy.contains("10.0.0.9"))


def test_dynamic_whitelist_suppresses_routeros_and_blocked_notification(self):
    effective = {"values": ()}
    config = AlertProcessorConfig(
        severities=("2",),
        listen_interfaces=("tzsp0",),
        whitelist_ips=(),
        whitelist_provider=lambda: tuple(effective["values"]),
        block_list_name="Suricata",
        timeout="1d",
    )
    effective["values"] = ("192.168.98.200",)
    address_list = FakeAddressList()
    send = Mock()
    process_single_alert(
        sample_event(src_ip="192.168.98.200"),
        address_list,
        None,
        config=config,
        ignore_predicate=lambda _event: False,
        send_telegram=send,
        log=Mock(),
        debug_log=Mock(),
    )
    self.assertEqual(address_list.added, [])
    send.assert_not_called()
```

Extend `tests/test_state_store.py` so `RuntimeProviders.state_store_config()`
contains a newly added managed IP and `add_saved_lists()` skips it.

- [ ] **Step 2: Run tests and verify the dynamic value is currently ignored**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_whitelist_policy tests.test_alert_processor tests.test_state_store
```

Expected: missing policy/provider failures; suppression assertion fails before implementation.

- [ ] **Step 3: Implement a per-batch effective snapshot**

Implement:

```python
@dataclass(frozen=True)
class WhitelistPolicy:
    system_entries: tuple[str, ...]
    managed_store: DynamicWhitelistStore

    def snapshot(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.system_entries, *self.managed_store.snapshot())))

    def contains(self, address: Any) -> bool:
        return is_ip_in_whitelist(address, self.snapshot())
```

Extend config:

```python
whitelist_provider: Callable[[], tuple[str, ...]] | None = None


def effective_whitelist(config: AlertProcessorConfig) -> tuple[str, ...]:
    if config.whitelist_provider is None:
        return config.whitelist_ips
    return tuple(config.whitelist_provider())
```

Capture `whitelist_ips = effective_whitelist(config)` once at the start of
`process_single_alert()` and once before batch deduplication. Use that local
snapshot for every whitelist decision in the respective operation.

In `RuntimeProviders.__post_init__()` construct:

```python
self.dynamic_whitelist = DynamicWhitelistStore(
    Path(self.settings.dynamic_whitelist_file)
)
self.whitelist_policy = WhitelistPolicy(
    self.settings.whitelist_ips,
    self.dynamic_whitelist,
)
```

Pass `self.whitelist_policy.snapshot` to `AlertProcessorConfig`. Build
`StateStoreConfig.whitelist_ips` from `self.whitelist_policy.snapshot()` so a
router reboot cannot restore a dynamically excluded address.

- [ ] **Step 4: Run focused pipeline and runtime tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_whitelist_policy tests.test_alert_processor \
  tests.test_state_store tests.test_app
```

Expected: all pass; a managed alert produces neither RouterOS add nor Telegram
`BLOCKED`.

- [ ] **Step 5: Commit and report**

```bash
git add \
  src/mikroclear/suricata/whitelist_policy.py src/mikroclear/alert_processor.py \
  src/mikroclear/runtime/providers.py tests/test_whitelist_policy.py \
  tests/test_alert_processor.py tests/test_state_store.py tests/test_app.py
git commit -m "Apply managed whitelist to alert processing"
```

---

### Task 4: Добавить audit writer и Telegram edit boundaries

**Files:**
- Create: `src/mikroclear/bot/audit.py`
- Create: `tests/test_bot_audit.py`
- Modify: `src/mikroclear/telegram/notify.py:1-58`
- Modify: `tests/test_telegram_notify.py:120-182`

**Interfaces:**
- Produces: `BotAuditLog(path: Path).record(action: str, outcome: str, chat_id: str, user_id: str, target: str, detail: str = "") -> None`.
- Produces: `edit_telegram_message(token: str, chat_id: str, message_id: int, text: str, reply_markup: Any, timeout: int = 10) -> TelegramSendResult`.
- Produces: `edit_telegram_reply_markup(token: str, chat_id: str, message_id: int, reply_markup: Any, timeout: int = 10) -> TelegramSendResult`.

- [ ] **Step 1: Write failing audit and transport tests**

```python
def test_audit_appends_private_json_without_secret_fields(self):
    with TemporaryDirectory() as tmp:
        path = Path(tmp, "bot-audit.log")
        audit = BotAuditLog(path)
        audit.record(
            action="whitelist.add",
            outcome="success",
            chat_id="chat-1",
            user_id="user-1",
            target="192.168.98.200",
            detail="removed=1",
        )
        row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(row["action"], "whitelist.add")
        self.assertNotIn("token", row)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


def test_edit_message_posts_text_and_inline_markup(self):
    response = Mock(status_code=200, text="ok")
    with patch("mikroclear.telegram.notify.requests.post", return_value=response) as post:
        result = edit_telegram_message(
            "token", "chat", 42, "Статус",
            {"inline_keyboard": []}, timeout=7,
        )
    self.assertTrue(result.ok)
    self.assertTrue(post.call_args.args[0].endswith("/editMessageText"))
    self.assertEqual(post.call_args.kwargs["data"]["message_id"], 42)


def test_edit_reply_markup_does_not_resend_alert_text(self):
    response = Mock(status_code=200, text="ok")
    with patch("mikroclear.telegram.notify.requests.post", return_value=response) as post:
        edit_telegram_reply_markup(
            "token", "chat", 42,
            {"inline_keyboard": [[{"text": "✅", "callback_data": "noop"}]]},
            timeout=7,
        )
    self.assertTrue(post.call_args.args[0].endswith("/editMessageReplyMarkup"))
    self.assertNotIn("text", post.call_args.kwargs["data"])
```

- [ ] **Step 2: Run and prove missing boundaries**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest tests.test_bot_audit tests.test_telegram_notify
```

Expected: import failures for audit/edit functions.

- [ ] **Step 3: Implement private JSONL audit and shared Telegram result parsing**

Implement `BotAuditLog` as:

```python
class BotAuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def record(
        self,
        action: str,
        outcome: str,
        chat_id: str,
        user_id: str,
        target: str,
        detail: str = "",
    ) -> None:
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": sanitize_text(action, 80),
            "outcome": sanitize_text(outcome, 40),
            "chat_id": sanitize_text(str(chat_id), 80),
            "user_id": sanitize_text(str(user_id), 80),
            "target": sanitize_text(str(target), 80),
            "detail": sanitize_text(str(detail), 240),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            os.fchmod(descriptor, 0o600)
            line = (json.dumps(row, sort_keys=True) + "\n").encode("utf-8")
            os.write(descriptor, line)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
```

The fixed signature prevents arbitrary extra fields from entering the audit
record.

Both edit helpers use the same error masking, retry-after and retryable
classification as `send_telegram_message()`. `edit_telegram_message()` calls
`editMessageText`; `edit_telegram_reply_markup()` calls
`editMessageReplyMarkup`. Extract and use this shared helper for send and edit:

```python
def _post_telegram_method(
    token: str,
    method: str,
    payload: dict[str, Any],
    timeout: int,
) -> TelegramSendResult:
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/{method}",
            data=payload,
            timeout=timeout,
        )
    except Exception as exc:
        return TelegramSendResult(
            ok=False,
            response_text=sanitize_exception_text(exc, token),
            retryable=True,
        )
    retry_after = 0
    if response.status_code == 429:
        try:
            retry_after = int(response.json().get("parameters", {}).get("retry_after", 0))
        except Exception:
            retry_after = 0
    return TelegramSendResult(
        ok=response.status_code == 200,
        status_code=response.status_code,
        response_text=mask_known_secret(response.text, token),
        retry_after=retry_after,
        retryable=response.status_code == 429 or response.status_code >= 500,
    )


def edit_telegram_message(token, chat_id, message_id, text, reply_markup, timeout=10):
    return _post_telegram_method(
        token,
        "editMessageText",
        {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": json.dumps(reply_markup),
        },
        timeout,
    )


def edit_telegram_reply_markup(token, chat_id, message_id, reply_markup, timeout=10):
    return _post_telegram_method(
        token,
        "editMessageReplyMarkup",
        {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "reply_markup": json.dumps(reply_markup),
        },
        timeout,
    )
```

- [ ] **Step 4: Run focused tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest tests.test_bot_audit tests.test_telegram_notify
```

Expected: all pass, including token masking and HTTP 429/5xx classification.

- [ ] **Step 5: Commit and report**

```bash
git add \
  src/mikroclear/bot/audit.py src/mikroclear/telegram/notify.py \
  tests/test_bot_audit.py tests/test_telegram_notify.py
git commit -m "Add bot audit and Telegram edit transport"
```

---

### Task 5: Реализовать launcher, registry и status navigation

**Files:**
- Create: `src/mikroclear/bot/menu.py`
- Create: `src/mikroclear/telegram/menu_handler.py`
- Create: `tests/test_bot_menu.py`
- Create: `tests/test_telegram_menu.py`
- Modify: `src/mikroclear/telegram/polling.py:38-82,170-286`
- Modify: `tests/test_telegram_commands.py`

**Interfaces:**
- Produces: `MenuView(text: str, reply_markup: dict[str, Any])`.
- Produces: `MenuItem(item_id, label, order, permission, module, enabled)`.
- Produces: `MenuRegistry.visible(chat_id: str, auth: BotAuth, settings: Settings, bot_settings: BotSettings) -> tuple[MenuItem, ...]`.
- Produces: `build_launcher_markup()`, `parse_menu_callback(data)`.
- Produces: `TelegramMenuHandler.handle_message(text: Any, chat_id: str, user_id: str, auth: BotAuth, send_message: Callable[..., Any], token: str, timeout: int, update_id: str = "") -> bool`.
- Produces: `TelegramMenuHandler.handle_callback(callback: dict[str, Any], auth: BotAuth, answer_callback: Callable[[str, str, bool], Any], send_message: Callable[..., Any], edit_message: Callable[..., Any], telegram_token: str, timeout: int, now: int) -> bool`.

- [ ] **Step 1: Write failing pure menu and poller routing tests**

```python
def test_launcher_is_single_persistent_reply_button(self):
    self.assertEqual(
        build_launcher_markup(),
        {
            "keyboard": [[{"text": "🛡 Mikro-Clear"}]],
            "is_persistent": True,
            "resize_keyboard": True,
        },
    )


def test_registry_filters_by_permission_module_and_feature(self):
    auth = BotAuth(
        BotSettings(
            admin_chat_ids=("admin",),
            allowed_chat_ids=("reader",),
            modules=("status", "mangle_control", "whitelist_control"),
        )
    )
    self.assertEqual(
        [item.item_id for item in default_menu_registry().visible(
            chat_id="reader",
            auth=auth,
            settings=Settings(
                mangle_control_enable=True,
                telegram_whitelist_control_enable=True,
            ),
            bot_settings=auth.settings,
        )],
        ["status"],
    )
    self.assertEqual(
        [item.item_id for item in default_menu_registry().visible(
            chat_id="admin",
            auth=auth,
            settings=Settings(
                mangle_control_enable=True,
                telegram_whitelist_control_enable=True,
            ),
            bot_settings=auth.settings,
        )],
        ["status", "mangle_control", "whitelist_control"],
    )


def test_start_sends_launcher_and_launcher_opens_inline_root(self):
    handler, send, _edit = make_handler()
    self.assertTrue(handler.handle_message(text="/start", chat_id="reader", user_id="u"))
    self.assertEqual(send.call_args.kwargs["reply_markup"], build_launcher_markup())
    self.assertTrue(handler.handle_message(text="🛡 Mikro-Clear", chat_id="reader", user_id="u"))
    self.assertIn("menu:v1:status", json.dumps(send.call_args.kwargs["reply_markup"]))
```

Add this poller ordering test:

```python
def test_poller_routes_start_to_menu_before_mangle_and_legacy(self):
    menu = Mock()
    menu.handle_message.return_value = True
    mangle = Mock()
    poller = TelegramUpdatePoller(
        Settings(enable_telegram=True, telegram_token="token", telegram_chatid="reader"),
        bot_settings=BotSettings(allowed_chat_ids=("reader",)),
        status_snapshot_factory=Mock(),
        handle_unblock_action=Mock(),
        answer_callback=Mock(),
        send_system_notification=Mock(),
        log=Mock(),
        now=Mock(return_value=100.0),
        menu_handler=menu,
        mangle_handler=mangle,
    )
    poller.process_update({
        "update_id": 1,
        "message": {
            "chat": {"id": "reader"},
            "from": {"id": "user-1"},
            "text": "/start",
        },
    })
    menu.handle_message.assert_called_once()
    mangle.handle_message.assert_not_called()
```

The existing `/status` command test remains unchanged and proves fallback
routing.

- [ ] **Step 2: Run and prove menu interfaces are absent**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_bot_menu tests.test_telegram_menu tests.test_telegram_commands
```

Expected: import failures, then routing assertion failure until poller order is wired.

- [ ] **Step 3: Implement pure registry and handler routes**

Use exact routes:

```python
MENU_PREFIX = "menu:v1:"
LAUNCHER_LABEL = "🛡 Mikro-Clear"


@dataclass(frozen=True)
class MenuView:
    text: str
    reply_markup: dict[str, Any]


@dataclass(frozen=True)
class MenuItem:
    item_id: str
    label: str
    order: int
    permission: str
    module: str
    enabled: Callable[[Settings], bool]


@dataclass(frozen=True)
class MenuRegistry:
    items: tuple[MenuItem, ...]

    def visible(self, *, chat_id, auth, settings, bot_settings):
        visible = []
        for item in self.items:
            permitted = auth.can_read(chat_id) if item.permission == "read" else auth.can_write(chat_id)
            if permitted and item.module in bot_settings.modules and item.enabled(settings):
                visible.append(item)
        return tuple(sorted(visible, key=lambda item: (item.order, item.item_id)))


def parse_menu_callback(data: Any) -> str | None:
    value = str(data or "")
    if not value.startswith(MENU_PREFIX):
        return None
    route = value[len(MENU_PREFIX):]
    if route in {
        "root", "status", "status:general", "status:mangle",
        "mangle", "exceptions",
    }:
        return route
    return route if re.fullmatch(r"exceptions:[0-9]+", route) else None


def default_menu_registry() -> MenuRegistry:
    return MenuRegistry((
        MenuItem("status", "📊 Статус", 10, "read", "status", lambda settings: True),
        MenuItem(
            "mangle_control",
            "🔀 Mangle",
            20,
            "admin",
            "mangle_control",
            lambda settings: settings.mangle_control_enable,
        ),
        MenuItem(
            "whitelist_control",
            "🛡 Исключения",
            30,
            "admin",
            "whitelist_control",
            lambda settings: settings.telegram_whitelist_control_enable,
        ),
    ))


def build_root_view(items: tuple[MenuItem, ...]) -> MenuView:
    routes = {
        "status": "status",
        "mangle_control": "mangle",
        "whitelist_control": "exceptions",
    }
    buttons = [
        {
            "text": item.label,
            "callback_data": f"menu:v1:{routes[item.item_id]}",
        }
        for item in items
    ]
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    return MenuView("<b>Mikro-Clear</b>", {"inline_keyboard": rows})


def build_status_menu_view(*, show_mangle: bool) -> MenuView:
    rows = [
        [{"text": "🛡 Общий статус", "callback_data": "menu:v1:status:general"}],
    ]
    if show_mangle:
        rows.append([{"text": "🔀 Mangle", "callback_data": "menu:v1:status:mangle"}])
    rows.append([{"text": "⬅️ Назад", "callback_data": "menu:v1:root"}])
    return MenuView(
        "<b>Статус</b>",
        {"inline_keyboard": rows},
    )
```

`TelegramMenuHandler` must:

- authorize `/start`, `/menu`, launcher and every callback;
- send the persistent launcher only after authorized `/start` or `/menu`;
- render `root`, `status`, `status:general`;
- delegate `status:mangle` and `mangle` to the Mangle handler interfaces
  introduced in Task 6;
- delegate `exceptions:*` to Task 8;
- answer callback before rendering;
- edit the current menu message and fall back to `sendMessage` only for
  non-retryable edit failure.

Define adapters at this boundary so Task 5 does not depend on concrete future
classes:

```python
class MangleMenuAdapter(Protocol):
    def status_view(self) -> MenuView:
        raise NotImplementedError

    def control_view(self, *, chat_id: str, user_id: str, update_id: str = "") -> MenuView:
        raise NotImplementedError


class WhitelistMenuAdapter(Protocol):
    def menu_view(self, *, page: int, chat_id: str, user_id: str, now: int) -> MenuView:
        raise NotImplementedError
```

Task 5 tests inject fakes implementing these exact methods. If an optional
adapter is absent, its registry item is filtered out and an old callback returns
`Функция недоступна`.

Wire poller order:

```python
if self.menu_handler is not None and self.menu_handler.handle_message(
    text=text,
    chat_id=chat_id,
    user_id=user_id,
    auth=auth,
    send_message=self._send_message,
    token=self.settings.telegram_token,
    timeout=self.settings.telegram_timeout,
    update_id=str(update.get("update_id", "")),
):
    return True
if self.mangle_handler is not None and self.mangle_handler.handle_message(
    text=text,
    chat_id=chat_id,
    user_id=user_id,
    auth=auth,
    send_message=self._send_message,
    token=self.settings.telegram_token,
    timeout=self.settings.telegram_timeout,
    update_id=str(update.get("update_id", "")),
):
    return True
return process_message_command(
    text=text,
    chat_id=chat_id,
    auth=auth,
    status_snapshot_factory=self.status_snapshot_factory,
    dispatch_message=dispatch_message,
    send_message=self._send_message,
    token=self.settings.telegram_token,
    timeout=self.settings.telegram_timeout,
    log=self.log,
)
```

Callbacks use menu, Mangle, whitelist, then ordinary Unblock order.

- [ ] **Step 4: Run menu and compatibility tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_bot_menu tests.test_telegram_menu \
  tests.test_telegram_commands tests.test_bot_dispatcher tests.test_bot_status
```

Expected: launcher/navigation pass and `/status` fallback remains unchanged.

- [ ] **Step 5: Commit and report**

```bash
git add \
  src/mikroclear/bot/menu.py src/mikroclear/telegram/menu_handler.py \
  src/mikroclear/telegram/polling.py tests/test_bot_menu.py \
  tests/test_telegram_menu.py tests/test_telegram_commands.py
git commit -m "Add Telegram launcher and menu navigation"
```

---

### Task 6: Перевести Mangle на compact menu, actual-state refresh, dry-run и audit

**Files:**
- Modify: `src/mikroclear/bot/mangle_control.py`
- Modify: `src/mikroclear/telegram/mangle_handler.py`
- Modify: `tests/test_telegram_mangle_control.py`
- Modify: `tests/test_telegram_menu.py`

**Interfaces:**
- Consumes: `MenuView`, `BotAuditLog`, injected `edit_message`.
- Produces: `TelegramMangleHandler.control_view(chat_id: str, user_id: str, update_id: str = "") -> MenuView`.
- Produces: `TelegramMangleHandler.status_view() -> MenuView`.
- Preserves: `/mangle`, `mangle:request|confirm|cancel|refresh`.

- [ ] **Step 1: Replace presentation expectations with failing compact/status tests**

```python
def test_control_keyboard_uses_actual_state_icons(self):
    keyboard = build_mangle_control_keyboard(
        [
            MangleRule("*1", "Site", "MC:Site", "prerouting", "mark-routing", False),
            MangleRule("*2", "Backup", "MC:Backup", "prerouting", "mark-routing", True),
        ],
        token_factory=lambda rule, action: f"{rule.rule_id}-{action}",
    )
    self.assertEqual(keyboard["inline_keyboard"][0][0]["text"], "✅ Site")
    self.assertEqual(keyboard["inline_keyboard"][1][0]["text"], "❌ Backup")


def test_status_view_is_detailed_and_read_only(self):
    view = handler.status_view()
    self.assertIn("Chain: prerouting", view.text)
    self.assertIn("Packets:", view.text)
    callbacks = json.dumps(view.reply_markup)
    self.assertNotIn("mangle:request:", callbacks)
    self.assertIn("menu:v1:status", callbacks)


def test_dry_run_does_not_update_routeros_and_keeps_icon(self):
    handler = make_handler(bot_settings=BotSettings(dry_run=True), rows=rows("false"))
    token = handler.create_action_token("*1", "disable", "chat-1", "user-1", now=100)
    handler.handle_callback(
        callback=confirm_callback(token),
        auth=admin_auth(),
        answer_callback=Mock(),
        send_message=Mock(),
        edit_message=handler.edit_message,
        telegram_token="token",
        timeout=7,
        now=101,
    )
    self.assertEqual(handler.client.api.mangle.updated, [])
    self.assertEqual(last_rule_button(handler.edit_message)["text"], "✅ AI-Tunnel")
    self.assertIn("dry-run", read_audit()["outcome"])
```

Add tests for `MIKROCLEAR_MANGLE_REQUIRE_CONFIRMATION=false`, successful reread,
RouterOS failure, stale token, unauthorized callback and edit fallback.

- [ ] **Step 2: Run focused tests and observe old English labels/current write**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest tests.test_telegram_mangle_control
```

Expected: failures for `✅/❌`, views, dry-run and confirmation-disabled path.

- [ ] **Step 3: Implement view APIs and mutation policy**

Presentation contract:

```python
def build_mangle_control_keyboard(rules, *, token_factory):
    rows = []
    for rule in rules:
        action = "enable" if rule.disabled else "disable"
        token = token_factory(rule, action)
        icon = "❌" if rule.disabled else "✅"
        rows.append([{
            "text": f"{icon} {rule.name}",
            "callback_data": f"mangle:request:{token}",
        }])
    rows.extend([
        [{"text": "🔄 Обновить", "callback_data": "mangle:refresh"}],
        [{"text": "⬅️ Назад", "callback_data": "menu:v1:root"}],
    ])
    return {"inline_keyboard": rows}
```

`status_view()` uses existing `format_mangle_status()` plus only refresh/back.
`control_view()` rereads RouterOS and creates compact action tokens.

On request:

- confirmation on: send/edit confirm view without write;
- confirmation off: consume token and call the same mutation method.

On confirm:

```python
if self.bot_settings.dry_run:
    self.audit.record("mangle.change", "dry-run", chat_id, user_id, rule.rule_id, action)
else:
    client.run_with_reconnect(
        "telegram mangle control",
        lambda: set_mangle_rule_disabled(
            client.ensure_connected(), rule.rule_id, action == "disable", self.settings
        ),
    )
view = self.control_view(chat_id=chat_id, user_id=user_id)
```

Edit the same message from the fresh view. Never invert the icon locally.
Record attempted/result audit without comments, credentials or full RouterOS
payloads.

- [ ] **Step 4: Run Mangle plus menu regressions**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_telegram_mangle_control tests.test_telegram_menu \
  tests.test_routeros_mangle tests.test_telegram_commands
```

Expected: all pass; actual RouterOS state controls every icon.

- [ ] **Step 5: Commit and report**

```bash
git add \
  src/mikroclear/bot/mangle_control.py \
  src/mikroclear/telegram/mangle_handler.py \
  tests/test_telegram_mangle_control.py tests/test_telegram_menu.py
git commit -m "Integrate Mangle control with Telegram menu"
```

---

### Task 7: Добавить whitelist tokens и alert-кнопку без регрессии существующих кнопок

**Files:**
- Create: `src/mikroclear/telegram/whitelist_actions.py`
- Create: `tests/test_telegram_whitelist.py`
- Modify: `src/mikroclear/telegram/notify.py:60-214`
- Modify: `tests/test_telegram_notify.py:72-182`

**Interfaces:**
- Produces: `WhitelistActionStore.create/peek/consume/cancel`.
- Produces: `build_whitelist_confirm_keyboard(token)`.
- Extends: `TelegramNotifier.__init__(settings, *, peer_formatter, log, debug_log, sanitize_exception_text, now, send_message=send_telegram_message, whitelist_keyboard_factory=None)`.

- [ ] **Step 1: Write failing token and non-regression keyboard tests**

```python
def test_action_token_is_single_use_expiring_and_requester_bound(self):
    with TemporaryDirectory() as tmp:
        actions = WhitelistActionStore(Path(tmp, "actions.json"), token_factory=lambda: "token123")
        token = actions.create(
            kind="add_confirm",
            address="192.168.98.200",
            list_name="Suricata",
            chat_id="chat-1",
            user_id="user-1",
            now=100,
            ttl_seconds=300,
            source_chat_id="chat-1",
            source_message_id=77,
            source_reply_markup={"inline_keyboard": []},
        )
        self.assertEqual(token, "token123")
        self.assertIsNone(actions.consume(token, now=101, chat_id="chat-1", user_id="other"))
        self.assertIsNotNone(actions.consume(token, now=101, chat_id="chat-1", user_id="user-1"))
        self.assertIsNone(actions.consume(token, now=102, chat_id="chat-1", user_id="user-1"))


def test_append_exception_action_keeps_existing_rows(self):
    existing = build_unblock_keyboard("192.168.98.200", "unblock-token")
    markup = append_managed_exception_button(
        existing,
        address="192.168.98.200",
        token="whitelist-token",
    )
    rows = markup["inline_keyboard"]
    self.assertEqual(rows[0][0]["text"], "🔓 Unblock 192.168.98.200")
    self.assertEqual([button["text"] for button in rows[1]], ["AbuseIPDB", "VirusTotal"])
    self.assertEqual(rows[2][0]["text"], "🛡 Добавить в исключения 192.168.98.200")
    self.assertEqual(rows[2][0]["callback_data"], "whitelist:v1:add-request:whitelist-token")


def test_notifier_passes_existing_markup_to_extension_factory(self):
    extension = Mock(side_effect=lambda markup, **_context: append_managed_exception_button(
        markup,
        address="192.168.98.200",
        token="whitelist-token",
    ))
    notifier = make_notifier(whitelist_keyboard_factory=extension)
    notifier.send_alert(
        event=sample_event(),
        wanted_ip="192.168.98.200",
        src_ip="192.168.10.10",
        wanted_port=445,
        action_type="BLOCKED",
    )
    extension.assert_called_once()
    original = extension.call_args.args[0]
    self.assertEqual(original["inline_keyboard"][0][0]["text"], "🔓 Unblock 192.168.98.200")
```

The existing notifier tests without an extension factory must continue to assert
exactly two original rows.

- [ ] **Step 2: Run and verify only the two existing rows are present**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_telegram_whitelist tests.test_telegram_notify \
  tests.test_telegram_unblock
```

Expected: missing action store and missing third row; existing Unblock tests stay green.

- [ ] **Step 3: Implement action store and append-only keyboard extension**

Action payload contains exactly:

```python
{
    "kind": kind,
    "address": address,
    "list_name": list_name,
    "sid": sid,
    "chat_id": chat_id,
    "user_id": user_id,
    "created_at": now,
    "expires_at": now + ttl_seconds,
    "source_chat_id": source_chat_id,
    "source_message_id": source_message_id,
    "source_reply_markup": source_reply_markup,
}
```

Use `TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,24}$")` and
`secrets.token_urlsafe(12)`, keeping the longest callback below Telegram's
64-byte limit. Validate kind allowlist
`add_request|add_confirm|remove_confirm|retry_unblock`, exact RFC1918 IP and
requester binding. Store file mode is `0600`.

Parse only these callbacks:

```text
whitelist:v1:add-request:<token>
whitelist:v1:add-confirm:<token>
whitelist:v1:remove-request:<token>
whitelist:v1:remove-confirm:<token>
whitelist:v1:retry-unblock:<token>
whitelist:v1:cancel:<token>
```

`add-request` consumes the chat-bound alert token, captures the clicking admin
user and source message metadata, creates a new user-bound `add_confirm` token,
and sends the approved confirmation view. `remove-request` peeks the
user-bound `remove_confirm` token and displays its confirmation; confirm or
cancel consumes it.

Requester matching is exact for `chat_id`. An empty stored `user_id` is accepted
only for `kind="add_request"`; all confirm, remove and retry payloads require an
exact non-empty `user_id`.

Implement:

```python
def append_managed_exception_button(reply_markup, *, address, token):
    rows = [list(row) for row in reply_markup.get("inline_keyboard", [])]
    rows.append([{
        "text": f"🛡 Добавить в исключения {address}",
        "callback_data": f"whitelist:v1:add-request:{token}",
    }])
    return {"inline_keyboard": rows}
```

`TelegramNotifier` first builds its existing keyboard. Only then it calls the
injected extension factory with the markup plus `event`, `wanted_ip`,
`action_type` and `now`. With no factory it returns the original markup
unchanged.

- [ ] **Step 4: Run notifier/token regressions**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_telegram_whitelist tests.test_telegram_notify \
  tests.test_telegram_unblock tests.test_rebrand
```

Expected: exact old alert text/buttons pass plus conditional third row.

- [ ] **Step 5: Commit and report**

```bash
git add \
  src/mikroclear/telegram/whitelist_actions.py \
  src/mikroclear/telegram/notify.py \
  tests/test_telegram_whitelist.py tests/test_telegram_notify.py
git commit -m "Add managed exception action to alerts"
```

---

### Task 8: Реализовать add-and-unblock, partial retry и exceptions menu

**Files:**
- Create: `src/mikroclear/bot/modules/exceptions.py`
- Create: `src/mikroclear/telegram/whitelist_handler.py`
- Modify: `tests/test_telegram_whitelist.py`
- Modify: `tests/test_telegram_menu.py`

**Interfaces:**
- Consumes: `DynamicWhitelistStore`, `WhitelistPolicy`, `WhitelistActionStore`,
  `BotAuditLog`, `remove_from_address_list`.
- Produces: `TelegramWhitelistHandler.extend_alert_keyboard(reply_markup: dict[str, Any], event: dict[str, Any], wanted_ip: str, action_type: str, now: int) -> dict[str, Any]`.
- Produces: `TelegramWhitelistHandler.menu_view(*, page: int, chat_id: str, user_id: str, now: int) -> MenuView`.
- Produces: `TelegramWhitelistHandler.handle_callback(callback: dict[str, Any], auth: BotAuth, answer_callback: Callable[[str, str, bool], Any], send_message: Callable[..., Any], edit_message: Callable[..., Any], edit_reply_markup: Callable[..., Any], telegram_token: str, timeout: int, now: int) -> bool`.

- [ ] **Step 1: Write failing workflow tests for every mutation outcome**

Add exact assertions:

```python
def dispatch_whitelist_callback(handler, callback, *, now=101):
    return handler.handle_callback(
        callback=callback,
        auth=admin_auth(),
        answer_callback=handler.answer_callback,
        send_message=handler.send_message,
        edit_message=handler.edit_message,
        edit_reply_markup=handler.edit_markup,
        telegram_token="token",
        timeout=7,
        now=now,
    )


def test_add_persists_before_routeros_remove_and_updates_only_markup(self):
    events = []
    store = RecordingStore(events)
    router = RecordingRouter(events, removed=1)
    handler = make_handler(store=store, router=router, dry_run=False)
    token = handler.actions.create_confirm_for_test("192.168.98.200")
    handled = dispatch_whitelist_callback(handler, execute_callback(token))
    self.assertTrue(handled)
    self.assertEqual(events[:2], ["store:add:192.168.98.200", "router:remove:192.168.98.200"])
    self.assertTrue(store.contains("192.168.98.200"))
    self.assertIn("✅ В исключениях 192.168.98.200", json.dumps(handler.edit_markup.call_args.kwargs, ensure_ascii=False))


def test_persistence_failure_never_calls_routeros(self):
    handler = make_handler(store=FailingStore(), router=Mock())
    dispatch_whitelist_callback(handler, execute_callback(valid_token(handler)))
    handler.router.assert_not_called()
    self.assertEqual(last_answer(handler), ("Не удалось сохранить исключение", True))


def test_routeros_failure_keeps_exception_and_offers_removal_only_retry(self):
    store = real_store()
    handler = make_handler(store=store, router=FailingRouter())
    dispatch_whitelist_callback(handler, execute_callback(valid_token(handler)))
    self.assertTrue(store.contains("192.168.98.200"))
    markup = handler.edit_markup.call_args.kwargs["reply_markup"]
    text = json.dumps(markup, ensure_ascii=False)
    self.assertIn("✅ В исключениях 192.168.98.200", text)
    self.assertIn("🔄 Повторить разблокировку", text)


def test_dry_run_changes_neither_store_nor_routeros(self):
    handler = make_handler(dry_run=True)
    dispatch_whitelist_callback(handler, execute_callback(valid_token(handler)))
    self.assertEqual(handler.store.snapshot(), ())
    handler.router.assert_not_called()
    self.assertEqual(read_audit(handler)["outcome"], "dry-run")


def test_remove_only_changes_managed_store(self):
    handler = make_handler_with_managed("192.168.98.200")
    dispatch_whitelist_callback(handler, remove_confirm_callback(handler))
    self.assertFalse(handler.store.contains("192.168.98.200"))
    handler.router.assert_not_called()


def test_alert_extension_requires_private_ip_admin_and_both_features(self):
    cases = (
        ("192.168.98.200", True, True, ("chat-1",), "BLOCKED", True),
        ("8.8.8.8", True, True, ("chat-1",), "BLOCKED", False),
        ("192.168.98.200", False, True, ("chat-1",), "BLOCKED", False),
        ("192.168.98.200", True, False, ("chat-1",), "BLOCKED", False),
        ("192.168.98.200", True, True, ("other",), "BLOCKED", False),
        ("192.168.98.200", True, True, ("chat-1",), "MONITOR", False),
    )
    for address, control, unblock, admins, action_type, expected in cases:
        with self.subTest(address=address, control=control, action_type=action_type):
            handler = make_handler(
                control_enabled=control,
                unblock_enabled=unblock,
                admin_chat_ids=admins,
            )
            markup = handler.extend_alert_keyboard(
                build_unblock_keyboard(address, "unblock-token"),
                event=sample_event(),
                wanted_ip=address,
                action_type=action_type,
                now=100,
            )
            self.assertEqual(
                "Добавить в исключения" in json.dumps(markup, ensure_ascii=False),
                expected,
            )
```

Add concrete tests named:

```text
test_execute_rechecks_admin_and_feature_flags_before_consume
test_execute_rejects_public_address_from_forged_token
test_expired_and_replayed_tokens_do_not_mutate
test_cancel_consumes_token_without_mutation
test_add_existing_address_is_idempotent
test_remove_missing_address_is_idempotent
test_retry_unblock_never_rewrites_or_removes_store
test_post_mutation_edit_failure_sends_result_without_second_mutation
```

Each test asserts `store.snapshot()`, RouterOS call count, audit outcome and
callback answer text; the forged/stale/cancel cases assert zero store and
RouterOS calls.

- [ ] **Step 2: Write failing pure menu pagination tests**

```python
def test_exceptions_view_separates_system_and_managed_entries(self):
    view = build_exceptions_view(
        system_entries=("10.0.0.0/8", "1.1.1.1"),
        managed_entries=("192.168.98.200",),
        page=0,
        page_size=8,
        remove_token_factory=lambda _address: "remove1234",
    )
    self.assertIn("Системные — только просмотр", view.text)
    self.assertIn("🔒 10.0.0.0/8", view.text)
    self.assertIn("Добавлены через Telegram", view.text)
    self.assertIn("🛡 192.168.98.200", view.text)
    self.assertIn("whitelist:v1:remove-request:", json.dumps(view.reply_markup))


def test_exceptions_view_paginates_managed_entries(self):
    managed = tuple(f"10.0.0.{index}" for index in range(1, 18))
    view = build_exceptions_view((), managed, page=1, page_size=8, remove_token_factory=lambda value: value)
    callbacks = json.dumps(view.reply_markup)
    self.assertIn("menu:v1:exceptions:0", callbacks)
    self.assertIn("menu:v1:exceptions:2", callbacks)


def test_pagination_counts_system_and_managed_rows_together(self):
    system = tuple(f"10.{index}.0.0/16" for index in range(9))
    view = build_exceptions_view(
        system,
        ("192.168.98.200",),
        page=1,
        page_size=8,
        remove_token_factory=lambda value: value,
    )
    self.assertIn("🔒 10.8.0.0/16", view.text)
    self.assertIn("🛡 192.168.98.200", view.text)
```

- [ ] **Step 3: Run and prove workflow/menu failures**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_telegram_whitelist tests.test_telegram_menu
```

Expected: missing handler/view failures.

- [ ] **Step 4: Implement handler with explicit transaction boundary**

The add execution method follows:

```python
def _execute_add(self, payload, *, chat_id, user_id):
    address = payload["address"]
    if self.bot_settings.dry_run:
        self.audit.record("whitelist.add", "dry-run", chat_id, user_id, address)
        return WhitelistMutationResult("dry-run", managed=False, removed=False)

    self.store.add(address)
    self.audit.record("whitelist.add", "persisted", chat_id, user_id, address)
    try:
        removed = self._remove_from_routeros(payload["list_name"], address)
    except Exception as exc:
        self.audit.record(
            "whitelist.add", "partial", chat_id, user_id, address,
            type(exc).__name__,
        )
        return WhitelistMutationResult("partial", managed=True, removed=False)

    self.audit.record(
        "whitelist.add", "success", chat_id, user_id, address,
        f"removed={int(removed)}",
    )
    return WhitelistMutationResult("success", managed=True, removed=removed)
```

`_remove_from_routeros()` uses:

```python
client = self.get_router_client()

def remove_batch():
    address_list, _address_list_v6, _resources = client.paths()
    return remove_from_address_list(address_list, list_name, address) > 0

return client.run_with_reconnect("telegram managed whitelist unblock", remove_batch)
```

On success/partial use `edit_telegram_reply_markup()` against the original alert
message. Preserve every pre-existing row and replace only the managed-exception
row. Partial result creates a new `retry_unblock` token and button. A failed
post-mutation edit is logged and followed by a result `sendMessage`; it must not
raise into a replayable mutation path.

Removal consumes `remove_confirm`, checks `store.contains()`, respects dry-run,
calls only `store.remove()`, audits, and edits the exceptions menu. It never
adds to RouterOS.

- [ ] **Step 5: Run all whitelist/menu tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_dynamic_whitelist tests.test_whitelist_policy \
  tests.test_telegram_whitelist tests.test_telegram_menu \
  tests.test_telegram_notify tests.test_telegram_unblock
```

Expected: all success, partial, retry, dry-run and removal boundaries pass.

- [ ] **Step 6: Commit and report**

```bash
git add \
  src/mikroclear/bot/modules/exceptions.py \
  src/mikroclear/telegram/whitelist_handler.py \
  tests/test_telegram_whitelist.py tests/test_telegram_menu.py
git commit -m "Implement managed exception workflows"
```

---

### Task 9: Завершить runtime wiring, status и single-poller contract

**Files:**
- Modify: `src/mikroclear/runtime/providers.py`
- Modify: `src/mikroclear/runtime/status_snapshot.py`
- Modify: `src/mikroclear/bot/modules/status.py`
- Modify: `src/mikroclear/telegram/polling.py`
- Modify: `tests/test_app.py`
- Modify: `tests/test_bot_status.py`
- Modify: `tests/test_telegram_commands.py`
- Modify: `tests/test_telegram_polling_worker.py`

**Interfaces:**
- Consumes all handlers/stores from Tasks 2-8.
- Produces one fully wired `RuntimeProviders` object.
- Extends `StatusSnapshot` with `telegram_whitelist_control_enabled`,
  `dynamic_whitelist_file`, `managed_whitelist_count`.

- [ ] **Step 1: Write failing same-instance and status tests**

```python
def test_runtime_wires_one_store_policy_and_handlers(self):
    service = app.build_service()
    providers = service.deps.get_router_client.__self__
    self.assertIs(providers.whitelist_policy.managed_store, providers.dynamic_whitelist)
    self.assertIs(providers.whitelist_handler.store, providers.dynamic_whitelist)
    self.assertIs(providers.menu_handler.whitelist_handler, providers.whitelist_handler)
    self.assertIs(providers.poller.menu_handler, providers.menu_handler)
    self.assertIs(providers.poller.whitelist_handler, providers.whitelist_handler)
    self.assertIs(providers.polling_worker.poller, providers.poller)


def test_status_reports_control_store_and_count_without_listing_ips(self):
    text = format_status(StatusSnapshot(
        uptime_seconds=60,
        routeros_connected=True,
        routeros_connected_seconds=30,
        eve_path="/var/log/suricata/eve.json",
        block_list_name="Suricata",
        monitor_only=False,
        telegram_unblock_enabled=True,
        state_dir="/var/lib/mikroclear",
        bot_settings=BotSettings(modules=("status", "whitelist_control")),
        telegram_whitelist_control_enabled=True,
        dynamic_whitelist_file="/var/lib/mikroclear/dynamic-whitelist.json",
        managed_whitelist_count=2,
    ))
    self.assertIn("telegram whitelist control: on", text)
    self.assertIn("managed whitelist: 2", text)
    self.assertIn("whitelist store: /var/lib/mikroclear/dynamic-whitelist.json", text)
    self.assertNotIn("192.168.", text)
```

Add callback-order assertions with handlers that record their invocation:

```python
consumed_order = []
menu.handle_callback.side_effect = lambda **_kwargs: consumed_order.append("menu") or False
mangle.handle_callback.side_effect = lambda **_kwargs: consumed_order.append("mangle") or False
whitelist.handle_callback.side_effect = lambda **_kwargs: consumed_order.append("whitelist") or True
poller.process_update({
    "update_id": 2,
    "callback_query": {
        "id": "cb-2",
        "data": "whitelist:v1:add-request:token",
        "message": {"message_id": 77, "chat": {"id": "admin"}},
        "from": {"id": "user-1"},
    },
})
self.assertEqual(
    consumed_order,
    ["menu", "mangle", "whitelist"],
)
process_callback_update.assert_not_called()
```

Keep the existing same-instance `TelegramPollingWorker` lifecycle assertions to
prove only that worker starts, drains, health-checks and stops.

- [ ] **Step 2: Run and verify missing wiring/status**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_app tests.test_bot_status \
  tests.test_telegram_commands tests.test_telegram_polling_worker
```

Expected: attribute/signature failures before wiring.

- [ ] **Step 3: Wire dependency construction in safe order**

In `RuntimeProviders.__post_init__()` use this ownership order:

```python
self.bot_settings = BotSettings.from_env()
self.dynamic_whitelist = DynamicWhitelistStore(Path(self.settings.dynamic_whitelist_file))
self.whitelist_policy = WhitelistPolicy(self.settings.whitelist_ips, self.dynamic_whitelist)
self.audit = BotAuditLog(Path(self.bot_settings.audit_log))
self.whitelist_actions = WhitelistActionStore(Path(self.settings.telegram_whitelist_state_file))
self.whitelist_handler = TelegramWhitelistHandler(
    self.settings,
    bot_settings=self.bot_settings,
    store=self.dynamic_whitelist,
    policy=self.whitelist_policy,
    actions=self.whitelist_actions,
    audit=self.audit,
    get_router_client=self.get_router_client,
    log=log,
)
self.notifier = TelegramNotifier(
    self.settings,
    peer_formatter=self.format_peer_with_asset,
    log=log,
    debug_log=self.debug_log,
    sanitize_exception_text=sanitize_exception_text,
    now=time,
    whitelist_keyboard_factory=self.whitelist_handler.extend_alert_keyboard,
)
self.mangle_handler = TelegramMangleHandler(
    self.settings,
    bot_settings=self.bot_settings,
    audit=self.audit,
    get_router_client=self.get_router_client,
    log=log,
)
self.menu_handler = TelegramMenuHandler(
    self.settings,
    bot_settings=self.bot_settings,
    status_snapshot_factory=self.build_status_snapshot,
    mangle_handler=self.mangle_handler,
    whitelist_handler=self.whitelist_handler,
    log=log,
)
```

Inject `menu_handler`, `whitelist_handler`, `edit_telegram_message` and
`edit_telegram_reply_markup` into the existing poller. Do not instantiate
another poller.

`ensure_dirs()` includes parents of both whitelist state files. Store
construction performs startup validation before event consumption.

- [ ] **Step 4: Extend status snapshot and run wiring tests**

Append backward-compatible fields after `bot_settings`:

```python
telegram_whitelist_control_enabled: bool = False
dynamic_whitelist_file: str = ""
managed_whitelist_count: int = 0
```

Add formatter lines:

```python
f"telegram whitelist control: {on_off(snapshot.telegram_whitelist_control_enabled)}",
f"managed whitelist: {snapshot.managed_whitelist_count}",
f"whitelist store: {snapshot.dynamic_whitelist_file}",
```

Pass count from `self.dynamic_whitelist.snapshot()` without including addresses.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_app tests.test_bot_status tests.test_runtime \
  tests.test_telegram_commands tests.test_telegram_polling \
  tests.test_telegram_polling_worker
```

Expected: all pass; same-instance lifecycle assertions remain green.

- [ ] **Step 5: Commit and report**

```bash
git add \
  src/mikroclear/runtime/providers.py src/mikroclear/runtime/status_snapshot.py \
  src/mikroclear/bot/modules/status.py src/mikroclear/telegram/polling.py \
  tests/test_app.py tests/test_bot_status.py tests/test_telegram_commands.py \
  tests/test_telegram_polling_worker.py
git commit -m "Wire Telegram menu and managed whitelist runtime"
```

---

### Task 10: Обновить конфигурацию, русскую документацию и воспроизведение

**Files:**
- Modify: `config/mikroclear.env.example`
- Modify: `docs/ru/env-reference.md`
- Modify: `docs/ru/install-from-github.md`
- Modify: `docs/ru/install-test-reproduction.md`
- Modify: `tests/test_install_documentation.py`
- Modify: `tests/test_standalone_install_contract.py`

**Interfaces:**
- Documents exact flags, paths, menu workflow and approval-gated live procedure.
- Preserves Git/script-only installation contract.

- [ ] **Step 1: Write failing documentation contract assertions**

```python
def test_docs_cover_menu_and_managed_exception_reproduction(self):
    env_text = (ROOT / "docs/ru/env-reference.md").read_text(encoding="utf-8")
    repro = (ROOT / "docs/ru/install-test-reproduction.md").read_text(encoding="utf-8")
    example = (ROOT / "config/mikroclear.env.example").read_text(encoding="utf-8")
    for required in (
        "MIKROCLEAR_TELEGRAM_WHITELIST_CONTROL_ENABLE=false",
        "dynamic-whitelist.json",
        "whitelist_control",
    ):
        self.assertIn(required, example + env_text)
    for required in (
        "🛡 Mikro-Clear",
        "🛡 Добавить в исключения",
        "🔄 Повторить разблокировку",
        "удаление исключения",
        "повторно подать",
    ):
        self.assertIn(required, repro)
```

Keep the existing tests that forbid legacy certificate paths, local SSH paths
and external tooling references in the two installation documents.

- [ ] **Step 2: Run and prove docs are incomplete**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_install_documentation tests.test_standalone_install_contract
```

Expected: new required strings are absent.

- [ ] **Step 3: Update env example and reference**

Add:

```env
MIKROCLEAR_TELEGRAM_WHITELIST_CONTROL_ENABLE=false
MIKROCLEAR_BOT_MODULES=status,mangle_control,whitelist_control
```

Document:

- feature requires admin chat, bot enabled, Unblock enabled and dry-run off for
  real mutation;
- `dynamic-whitelist.json` and `telegram-whitelist-actions.json` live under
  `MIKROCLEAR_STATE_DIR`;
- system entries are read-only; managed entries are exact RFC1918 IPv4;
- corrupt managed JSON prevents startup;
- `/status` shows enable flag, path and count, never the address list.

Correct the existing description of `MIKROCLEAR_WHITELIST_IPS` to exact IP/CIDR
matching; remove any claim that raw string prefixes are accepted.

- [ ] **Step 4: Add the operator reproduction sequence**

In `docs/ru/install-test-reproduction.md`, after local tests, add a separately
approved live checklist:

```text
1. Install/update from an exact Git commit with scripts/install-selks.sh.
2. Confirm /status: dry-run off, whitelist control on, expected state-dir.
3. On an isolated test network, verify that 192.168.250.250 is unused and
   generate a controlled BLOCKED alert with that target.
4. Confirm “Добавить и разблокировать” for 192.168.250.250.
5. Check dynamic-whitelist.json ownership/mode and exact address.
6. Check that RouterOS Suricata no longer contains the address.
7. Reproduce the same controlled EVE event; expect no new block/alert.
8. Remove the address through Mikro-Clear → Исключения.
9. Confirm no immediate block.
10. Reproduce the controlled event; expect normal block and alert.
11. Recheck /status, /mangle and ordinary 🔓 Unblock.
```

The documented example uses a dedicated isolated test host
`192.168.250.250` and instructs the operator to verify that this address is
unused before generating the test alert. The install command records the actual
commit with `git rev-parse HEAD`; it does not use an unresolved commit
placeholder. Do not include live tokens, passwords or production IPs.

- [ ] **Step 5: Run documentation/install tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_install_documentation tests.test_standalone_install_contract \
  tests.test_selks_standalone_installer
```

Expected: all pass and installer behavior remains unchanged.

- [ ] **Step 6: Commit and report**

```bash
git add \
  config/mikroclear.env.example docs/ru/env-reference.md \
  docs/ru/install-from-github.md docs/ru/install-test-reproduction.md \
  tests/test_install_documentation.py tests/test_standalone_install_contract.py
git commit -m "Document Telegram menu and managed exceptions"
```

---

### Task 11: Полная локальная проверка и implementation handoff

**Files:**
- Verify only: all changed production, test, config and documentation files.

**Interfaces:**
- Produces evidence that the implementation is locally releasable.
- Does not authorize production deploy, restart or live RouterOS/Telegram writes.

- [ ] **Step 1: Run the complete focused set**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_telegram_unblock tests.test_routeros_client \
  tests.test_dynamic_whitelist tests.test_whitelist_policy \
  tests.test_alert_processor tests.test_state_store \
  tests.test_bot_audit tests.test_bot_menu tests.test_bot_status \
  tests.test_telegram_menu tests.test_telegram_mangle_control \
  tests.test_telegram_whitelist tests.test_telegram_notify \
  tests.test_telegram_commands tests.test_telegram_polling \
  tests.test_telegram_polling_worker tests.test_app tests.test_settings \
  tests.test_bot_settings tests.test_install_documentation \
  tests.test_standalone_install_contract
```

Expected: `OK`.

- [ ] **Step 2: Run the full suite**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest discover -s tests
```

Expected: `OK`, no real Telegram or RouterOS connection attempts.

- [ ] **Step 3: Compile and validate repository cleanliness**

```bash
PYTHONPYCACHEPREFIX=/tmp/mikroclear-menu-pycache \
  ./.venv/bin/python -m compileall -q src tests
git diff --check
git status --short
```

Expected: compilation exit `0`, no whitespace errors, only intentional
implementation changes before their final commit.

- [ ] **Step 4: Run secret and forbidden-path regressions**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ./.venv/bin/python -m unittest \
  tests.test_security tests.test_rebrand tests.test_install_documentation \
  tests.test_standalone_install_contract tests.test_wheel_artifact_validation
```

Expected: `OK`; no token leakage, legacy certificate path or installation
dependency regression.

- [ ] **Step 5: Review commit series and stop before production**

```bash
git log --oneline --decorate -12
git status --short
```

Expected: one reviewable commit per task and a clean tree. Report:

- focused/full/compile results with exact counts;
- commit list;
- any skipped command and reason;
- remaining approval-gated actions: push, SELKS update, service restart, live
  Telegram/RouterOS reproduction.

Do not create an empty verification commit. If verification required a real
fix, repeat that task's failing-test/minimal-fix cycle and commit only the fix.
