# Telegram Polling Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Telegram update handling loss-aware, move network polling off the main runtime loop, and replace the mutating production probe with explicit read-only and confirmed-reset operations.

**Architecture:** `TelegramUpdatePoller` owns Telegram API parsing and sequential update handling, while a new `TelegramPollingWorker` performs only long-poll network I/O and exchanges one pending update at a time with the main runtime thread. Diagnostics are read-only by default, mutations require a stopped service and explicit MCP confirmation, and production artifact identity is verified by hash and diff.

**Tech Stack:** Python 3.11+, `unittest`, `requests`, `threading`, `queue`, systemd helper scripts, FastMCP.

## Global Constraints

- Existing deploy, restart, and sudo commands are not removed or narrowed.
- Production SELKS is not modified or restarted during local implementation.
- Tests do not access real Telegram API or RouterOS.
- Telegram command and callback handlers continue to run sequentially in the main runtime thread.
- Existing auth, admin allowlist, dry-run, and audit semantics remain unchanged.
- Telegram long-poll timeout defaults to 25 seconds and HTTP timeout is long-poll timeout plus 5 seconds.
- Retryable update processing gets at most 5 attempts with delays of 5, 10, 20, and 40 seconds.

---

### Task 1: Typed Delivery Failures and Ack-After-Processing

**Files:**
- Modify: `src/mikroclear/telegram/notify.py`
- Modify: `src/mikroclear/telegram/commands.py`
- Modify: `src/mikroclear/telegram/polling.py`
- Modify: `tests/test_telegram_notify.py`
- Modify: `tests/test_telegram_command_boundary.py`
- Modify: `tests/test_telegram_commands.py`

**Interfaces:**
- Produces: `TelegramSendResult.retryable: bool`.
- Produces: `RetryableTelegramDeliveryError` raised only for retryable response delivery failures.
- Produces: `TelegramUpdatePoller.process_update(update)`, `acknowledge_update(update)`, and `fetch_updates(long_poll_seconds=0)`.
- Preserves: `TelegramUpdatePoller.process_updates()` as a synchronous compatibility path.

- [ ] **Step 1: Write failing delivery classification tests**

Add tests that mock `requests.post` and assert network errors, HTTP 429, and HTTP 5xx return retryable results while HTTP 400 is permanent:

```python
def test_send_telegram_message_returns_retryable_result_for_network_error(self):
    with patch("mikroclear.telegram.notify.requests.post", side_effect=RuntimeError("token-secret")):
        result = send_telegram_message("token-secret", "chat-1", "status")

    self.assertFalse(result.ok)
    self.assertTrue(result.retryable)
    self.assertNotIn("token-secret", result.response_text)

def test_send_telegram_message_classifies_http_failures(self):
    response = Mock(status_code=503, text="unavailable")
    with patch("mikroclear.telegram.notify.requests.post", return_value=response):
        result = send_telegram_message("token", "chat-1", "status")
    self.assertTrue(result.retryable)
```

- [ ] **Step 2: Run delivery tests and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_telegram_notify.TelegramNotifyDeliveryTests -v
```

Expected: FAIL because `TelegramSendResult` has no `retryable` field and network exceptions escape.

- [ ] **Step 3: Implement typed delivery results**

Extend the result and contain exceptions inside `send_telegram_message`:

```python
@dataclass(frozen=True)
class TelegramSendResult:
    ok: bool
    status_code: int = 0
    response_text: str = ""
    retry_after: int = 0
    retryable: bool = False


def send_telegram_message(
    token: str,
    chat_id: str,
    text: str,
    reply_markup: Any = None,
    timeout: int = 10,
) -> TelegramSendResult:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup if isinstance(reply_markup, str) else json.dumps(reply_markup)
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
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
```

- [ ] **Step 4: Run delivery tests and verify GREEN**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 5: Write failing command and offset tests**

Add a retryable command response test and a two-update regression proving the failed update is not acknowledged:

```python
def test_process_message_command_raises_for_retryable_send_failure(self):
    with self.assertRaises(RetryableTelegramDeliveryError):
        process_message_command(
            text="/status",
            chat_id="chat-1",
            auth=FakeAuth(True),
            status_snapshot_factory=lambda: object(),
            dispatch_message=lambda *args: types.SimpleNamespace(text="status", alert=False),
            send_message=lambda **kwargs: types.SimpleNamespace(
                ok=False,
                retryable=True,
                response_text="temporary",
            ),
            token="token",
            timeout=5,
            log=lambda message: None,
        )

def test_retryable_handler_failure_does_not_advance_offset(self):
    poller = self.make_poller_with_updates([message_update(99, "/status")])
    poller.send_message = Mock(
        return_value=types.SimpleNamespace(ok=False, retryable=True, response_text="temporary")
    )

    poller.process_updates()

    self.assertEqual(poller.update_offset, 0)
```

- [ ] **Step 6: Run command tests and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_telegram_command_boundary tests.test_telegram_commands -v
```

Expected: FAIL because retryable delivery is only logged and offset advances before handler execution.

- [ ] **Step 7: Implement retry propagation and ack-after-processing**

Add the exception and split poller operations:

```python
class RetryableTelegramDeliveryError(RuntimeError):
    pass


def process_message_command(
    *,
    text: str,
    chat_id: str,
    auth: Any,
    status_snapshot_factory: Callable[[], Any],
    dispatch_message: Callable[[str, str, Any, Callable[[], Any]], Any],
    send_message: Callable[..., Any],
    token: str,
    timeout: int,
    log: Callable[[str], None],
) -> bool:
    result = dispatch_message(text, chat_id, auth, status_snapshot_factory)
    if result is None:
        return False
    if result.alert and result.text == "Unauthorized":
        log(f"Rejected Telegram command from unauthorized chat {chat_id}")
        return True
    response = send_message(
        token=token,
        chat_id=chat_id,
        text=result.text,
        timeout=timeout,
    )
    if getattr(response, "ok", True) is False:
        response_text = str(getattr(response, "response_text", "")).strip()
        if getattr(response, "retryable", False):
            raise RetryableTelegramDeliveryError(response_text or "temporary Telegram delivery failure")
        log(f"Failed to send Telegram command response to chat {chat_id}: {response_text}".rstrip(": "))
    return True
```

```python
def process_update(self, update: dict[str, Any]) -> None:
    if self._process_message(update):
        return
    self._process_callback(update)

def acknowledge_update(self, update: dict[str, Any]) -> None:
    update_id = int(update["update_id"])
    self.update_offset = max(self.update_offset, update_id + 1)

def process_updates(self) -> None:
    updates = self.fetch_updates(long_poll_seconds=0)
    if updates is None:
        return
    for update in updates:
        try:
            self.process_update(update)
        except Exception as exc:
            self._record_failure(sanitize_exception_text(exc, self.settings.telegram_token))
            break
        self.acknowledge_update(update)
```

Implement the network boundary with the exact return contract:

```python
def _enabled(self) -> bool:
    return bool(
        self.settings.enable_telegram
        and self.settings.telegram_token
        and self.settings.telegram_chatid
    )

def fetch_updates(self, *, long_poll_seconds: int = 0) -> list[dict[str, Any]] | None:
    if not self._enabled():
        return None
    current_time = self.now()
    if not self.backoff.should_poll(current_time):
        return None
    try:
        response = self.http_get(
            f"https://api.telegram.org/bot{self.settings.telegram_token}/getUpdates",
            params={
                "offset": self.update_offset,
                "timeout": long_poll_seconds,
                "allowed_updates": ujson.dumps(["callback_query", "message"]),
            },
            timeout=max(self.settings.telegram_timeout, long_poll_seconds + 5),
        )
        if response.status_code != 200:
            error_text = mask_known_secret(
                f"HTTP {response.status_code}: {response.text[:120]}",
                self.settings.telegram_token,
            )
            self._record_failure(error_text)
            return None
        body = response.json()
        if not body.get("ok"):
            self._record_failure(
                mask_known_secret(f"not ok: {str(body)[:120]}", self.settings.telegram_token)
            )
            return None
    except Exception as exc:
        self._record_failure(sanitize_exception_text(exc, self.settings.telegram_token))
        return None
    self.backoff.record_success(self.now())
    return list(body.get("result", []))
```

- [ ] **Step 8: Run focused and polling tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_telegram_notify tests.test_telegram_command_boundary tests.test_telegram_commands tests.test_telegram_polling -v
```

Expected: PASS.

- [ ] **Step 9: Commit Task 1**

```bash
git add src/mikroclear/telegram/notify.py src/mikroclear/telegram/commands.py src/mikroclear/telegram/polling.py tests/test_telegram_notify.py tests/test_telegram_command_boundary.py tests/test_telegram_commands.py
git commit -m "Fix Telegram update acknowledgement ordering"
```

### Task 2: Long-Poll Network Worker and Runtime Lifecycle

**Files:**
- Create: `src/mikroclear/telegram/polling_worker.py`
- Create: `tests/test_telegram_polling_worker.py`
- Modify: `src/mikroclear/settings.py`
- Modify: `src/mikroclear/runtime/__init__.py`
- Modify: `src/mikroclear/runtime/providers.py`
- Modify: `src/mikroclear/runtime/wiring.py`
- Modify: `tests/test_settings.py`
- Modify: `tests/test_runtime.py`
- Modify: `tests/test_app.py`
- Modify: `config/mikroclear.env.example`
- Modify: `docs/ru/env-reference.md`

**Interfaces:**
- Consumes: `TelegramUpdatePoller.fetch_updates()`, `process_update()`, and `acknowledge_update()` from Task 1.
- Produces: `TelegramPollingWorker.start()`, `drain_ready()`, and `stop()`.
- Produces: `Settings.telegram_long_poll_seconds: int = 25`.
- Produces: runtime lifecycle callbacks `start_telegram_worker`, `process_telegram_updates`, and `stop_telegram_worker`.

- [ ] **Step 1: Write failing worker ordering tests**

Create `tests/test_telegram_polling_worker.py` with a fake poller and deterministic events:

```python
class FakePoller:
    def __init__(self):
        self.fetch_calls = 0
        self.processed = []
        self.acked = []

    def fetch_updates(self, *, long_poll_seconds):
        self.fetch_calls += 1
        return [{"update_id": 10}, {"update_id": 11}] if self.fetch_calls == 1 else []

    def process_update(self, update):
        self.processed.append(update["update_id"])

    def acknowledge_update(self, update):
        self.acked.append(update["update_id"])


def test_worker_waits_for_main_thread_before_ack_and_next_update(self):
    poller = FakePoller()
    worker = TelegramPollingWorker(poller, long_poll_seconds=25, log=lambda message: None)
    worker.start()
    self.assertTrue(wait_until(worker.has_pending_update))
    self.assertEqual(poller.acked, [])

    worker.drain_ready()

    self.assertTrue(wait_until(lambda: poller.acked == [10]))
    self.assertEqual(poller.processed, [10])
    worker.stop()
```

Add tests for batch order, five attempts, abandoned logging, and no new fetch after stop.

- [ ] **Step 2: Run worker tests and verify RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_telegram_polling_worker -v
```

Expected: ERROR because `mikroclear.telegram.polling_worker` does not exist.

- [ ] **Step 3: Implement the worker**

Create a queue-size-one worker whose network thread waits for main-thread completion:

```python
@dataclass
class PendingTelegramUpdate:
    update: dict[str, Any]
    completed: Event = field(default_factory=Event)
    succeeded: bool = False
    error_text: str = ""


class TelegramPollingWorker:
    RETRY_DELAYS = (5, 10, 20, 40)

    def __init__(self, poller, *, long_poll_seconds, log, wait=None):
        self.poller = poller
        self.long_poll_seconds = long_poll_seconds
        self.log = log
        self._wait = wait or Event().wait
        self._queue = Queue(maxsize=1)
        self._stop = Event()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = Thread(target=self._run, name="telegram-long-poll", daemon=True)
        self._thread.start()

    def drain_ready(self):
        try:
            pending = self._queue.get_nowait()
        except Empty:
            return False
        try:
            self.poller.process_update(pending.update)
        except Exception as exc:
            pending.error_text = sanitize_exception_text(exc, self.poller.settings.telegram_token)
        else:
            pending.succeeded = True
        finally:
            pending.completed.set()
        return True

    def has_pending_update(self) -> bool:
        return not self._queue.empty()

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
            updates = self.poller.fetch_updates(long_poll_seconds=self.long_poll_seconds)
            if updates is None:
                self._stop.wait(1)
                continue
            if not updates:
                continue
            for update in updates:
                acknowledged = False
                for attempt in range(5):
                    pending = PendingTelegramUpdate(update=update)
                    if not self._publish(pending):
                        return
                    while not pending.completed.wait(0.25):
                        if self._stop.is_set():
                            return
                    if pending.succeeded:
                        self.poller.acknowledge_update(update)
                        acknowledged = True
                        break
                    if attempt == 4:
                        update_id = update.get("update_id", "unknown")
                        self.log(
                            f"Abandoned Telegram update {update_id} after 5 attempts: "
                            f"{pending.error_text}"
                        )
                        self.poller.acknowledge_update(update)
                        acknowledged = True
                        break
                    if self._stop.wait(self.RETRY_DELAYS[attempt]):
                        return
                if not acknowledged or self._stop.is_set():
                    return

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.long_poll_seconds + 5)
```

Import `Full`, `Empty`, and `Queue` from `queue`, and `Event` and `Thread` from `threading`. The worker never calls a handler from `_run()`; only `drain_ready()` calls `process_update()`.

- [ ] **Step 4: Run worker tests and verify GREEN**

Run Step 2. Expected: PASS.

- [ ] **Step 5: Write failing settings and runtime lifecycle tests**

Add:

```python
def test_telegram_long_poll_seconds_default_and_env(self):
    self.assertEqual(Settings().telegram_long_poll_seconds, 25)
    with patch.dict(os.environ, {"MIKROCLEAR_TELEGRAM_LONG_POLL_SECONDS": "40"}, clear=True):
        self.assertEqual(Settings.from_env().telegram_long_poll_seconds, 40)
```

Update runtime dependencies and assert startup/drain/shutdown ordering:

```python
self.assertLess(calls.index(("start_telegram_worker",)), calls.index(("process_telegram_updates",)))
self.assertLess(calls.index(("stop_telegram_worker",)), calls.index(("client_close",)))
```

- [ ] **Step 6: Run settings/runtime tests and verify RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_settings tests.test_runtime tests.test_app -v
```

Expected: FAIL because the setting and lifecycle callbacks do not exist.

- [ ] **Step 7: Wire worker lifecycle**

Add `telegram_long_poll_seconds` to `Settings`, instantiate `TelegramPollingWorker` in `RuntimeProviders`, and change runtime dependencies:

```python
telegram_updates_interval_seconds: int = 5
telegram_long_poll_seconds: int = 25

telegram_updates_interval_seconds=env_int("MIKROCLEAR_TELEGRAM_UPDATES_INTERVAL_SECONDS", 5),
telegram_long_poll_seconds=env_int("MIKROCLEAR_TELEGRAM_LONG_POLL_SECONDS", 25),
```

The two shown fields replace the current single `telegram_updates_interval_seconds` declaration at that location; no other `Settings` field changes.

```python
@dataclass(frozen=True)
class RuntimeDependencies:
    signal_module: Any
    pyinotify_module: Any
    event_handler_factory: Callable[[], Any]
    ensure_dirs: Callable[[], None]
    print_startup_config: Callable[[], None]
    send_system_notification: Callable[[str, str], Any]
    seek_to_end: Callable[[str], None]
    get_router_client: Callable[[], Any]
    read_ignore_list: Callable[[str], None]
    start_telegram_worker: Callable[[], None]
    process_telegram_updates: Callable[[], Any]
    stop_telegram_worker: Callable[[], None]
    log: Callable[[str], None]
    debug_traceback: Callable[[], str]
    sleep: Callable[[int], None]
    time: Callable[[], float]
```

```python
def startup(self) -> None:
    self.deps.ensure_dirs()
    self.deps.print_startup_config()
    self.deps.send_system_notification(f"Mikro-Clear v{self.config.version} started", "START")
    self.deps.seek_to_end(self.config.filepath)
    self.client = self.deps.get_router_client()
    self.client.connect()
    self.client.heartbeat(force=True)
    self.deps.read_ignore_list(self.config.ignore_list_path)
    self._start_file_watcher()
    self.deps.log(f"Monitoring {self.config.filepath} for Suricata alerts")
    self.deps.start_telegram_worker()

def run_once(self) -> None:
    if self.notifier is None or self.client is None:
        raise RuntimeError("MikroClearService.startup() must be called before run_once()")
    self.notifier.process_events()
    if self.notifier.check_events(timeout=1000):
        self.notifier.read_events()
    self.deps.process_telegram_updates()
    now = self.deps.time()
    if now - self.last_idle_heartbeat >= self.config.router_heartbeat_seconds:
        self.last_idle_heartbeat = now
        self.client.heartbeat()

def shutdown(self) -> None:
    self.deps.stop_telegram_worker()
    if self.notifier is not None:
        try:
            self.notifier.stop()
        except Exception:
            pass
    if self.client is not None:
        try:
            self.client.close()
        except Exception:
            pass
    self.deps.send_system_notification(f"Mikro-Clear v{self.config.version} stopped", "STOP")
    self.deps.log("Stopped")
```

`RuntimeProviders.polling_worker` receives the existing poller, the new setting, and `log`. `runtime/wiring.py` maps the three lifecycle callbacks.

- [ ] **Step 8: Document the setting and run focused tests**

Add `MIKROCLEAR_TELEGRAM_LONG_POLL_SECONDS=25` to `config/mikroclear.env.example` and document that the old interval remains compatibility-only. Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_telegram_polling_worker tests.test_settings tests.test_runtime tests.test_app -v
```

Expected: PASS.

- [ ] **Step 9: Commit Task 2**

```bash
git add src/mikroclear/telegram/polling_worker.py src/mikroclear/settings.py src/mikroclear/runtime/__init__.py src/mikroclear/runtime/providers.py src/mikroclear/runtime/wiring.py tests/test_telegram_polling_worker.py tests/test_settings.py tests/test_runtime.py tests/test_app.py config/mikroclear.env.example docs/ru/env-reference.md
git commit -m "Add Telegram long polling worker"
```

### Task 3: Read-Only Probe and Explicit Subscription Reset

**Files:**
- Modify: `deploy/bin/mikroclear-telegram-getupdates-probe`
- Create: `tests/test_telegram_getupdates_probe.py`
- Modify: `services/mcp-server/server.py`
- Modify: `tests/test_mcp_server.py`
- Modify: `deploy/sudoers.d/mikroclear-mcp-selks`
- Modify: `tests/test_sudoers.py`

**Interfaces:**
- Produces: helper default mode with no `getUpdates` call.
- Produces: helper `--reset-allowed-updates` mode that requires inactive service.
- Produces: MCP `reset_mikroclear_telegram_updates(confirm: bool = False) -> str`.
- Preserves: existing `probe_mikroclear_telegram_updates()` and all current sudo commands.

- [ ] **Step 1: Write failing standalone helper tests**

Load the extensionless helper with `SourceFileLoader`, inject HTTP/systemctl dependencies, and assert:

```python
def test_read_only_probe_never_calls_get_updates(self):
    calls = []
    result = probe.run_probe(
        ["probe"],
        env={"MIKROCLEAR_TELEGRAM_TOKEN": "token-a"},
        runtime_token="token-a",
        request=lambda method, token, params=None: calls.append(method) or fake_response(method),
        service_active=lambda: True,
    )
    self.assertEqual(calls, ["getMe", "getWebhookInfo"])
    self.assertNotIn("token-a", json.dumps(result))

def test_reset_refuses_while_service_is_active(self):
    with self.assertRaisesRegex(RuntimeError, "must be stopped"):
        probe.run_probe(
            ["probe", "--reset-allowed-updates"],
            env={"MIKROCLEAR_TELEGRAM_TOKEN": "token-a"},
            runtime_token=None,
            request=Mock(),
            service_active=lambda: True,
        )
```

Add a stopped-service test that checks call order `getWebhookInfo`, `getUpdates`, `getWebhookInfo` and verifies output contains only update IDs/types.

- [ ] **Step 2: Run helper tests and verify RED**

```bash
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m unittest tests.test_telegram_getupdates_probe -v
```

Expected: FAIL because the current script has no injectable `run_probe` and always calls `getUpdates`.

- [ ] **Step 3: Implement safe probe modes**

Refactor the helper around pure functions:

```python
def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]

def summarize_updates(body: dict[str, Any]) -> dict[str, Any]:
    updates = body.get("result", []) if body.get("ok") else []
    return {
        "ok": bool(body.get("ok")),
        "count": len(updates),
        "updates": [
            {
                "update_id": update.get("update_id"),
                "type": next((key for key in update if key != "update_id"), "unknown"),
            }
            for update in updates
        ],
    }

def summarize_get_me(body: dict[str, Any]) -> dict[str, Any]:
    user = body.get("result", {}) if body.get("ok") else {}
    return {
        "ok": bool(body.get("ok")),
        "id": user.get("id"),
        "username": user.get("username"),
    }

def summarize_webhook(body: dict[str, Any]) -> dict[str, Any]:
    webhook = body.get("result", {}) if body.get("ok") else {}
    return {
        "ok": bool(body.get("ok")),
        "url": webhook.get("url", ""),
        "pending_update_count": webhook.get("pending_update_count", 0),
        "allowed_updates": webhook.get("allowed_updates", []),
    }

def run_probe(
    argv: list[str],
    *,
    env: dict[str, str],
    runtime_token: str | None,
    request: Callable[[str, str, dict[str, Any] | None], dict[str, Any]],
    service_active: Callable[[], bool],
) -> dict[str, Any]:
    config_token = env.get("MIKROCLEAR_TELEGRAM_TOKEN", "")
    if not config_token:
        raise RuntimeError("MIKROCLEAR_TELEGRAM_TOKEN is empty")
    reset = "--reset-allowed-updates" in argv[1:]
    result: dict[str, Any] = {
        "mode": "reset-allowed-updates" if reset else "read-only",
        "config_token_fingerprint": token_fingerprint(config_token),
        "runtime_token_fingerprint": token_fingerprint(runtime_token) if runtime_token else None,
        "tokens_match": bool(runtime_token and runtime_token == config_token),
    }
    if reset:
        if service_active():
            raise RuntimeError("mikroclear.service must be stopped before allowed_updates reset")
        result["webhook_before"] = summarize_webhook(
            request("getWebhookInfo", config_token, None)
        )
        result["updates"] = summarize_updates(
            request(
                "getUpdates",
                config_token,
                {
                    "offset": 0,
                    "timeout": 0,
                    "allowed_updates": json.dumps(ALLOWED_UPDATES),
                },
            )
        )
        result["webhook_after"] = summarize_webhook(
            request("getWebhookInfo", config_token, None)
        )
        return result
    identities = {
        "config": {
            "get_me": summarize_get_me(request("getMe", config_token, None)),
            "webhook": summarize_webhook(request("getWebhookInfo", config_token, None)),
        }
    }
    if runtime_token and runtime_token != config_token:
        identities["runtime"] = {
            "get_me": summarize_get_me(request("getMe", runtime_token, None)),
            "webhook": summarize_webhook(request("getWebhookInfo", runtime_token, None)),
        }
    result["identities"] = identities
    return result
```

Implement `read_runtime_token()` by reading `MainPID` from `/usr/bin/systemctl show -p MainPID --value mikroclear.service`, then parsing `/proc/<pid>/environ`. Implement `request()` as a wrapper around `requests.get` that returns `response.json()` and replaces the token with `***MASKED***` in any exception. `main()` loads config and runtime tokens, calls `run_probe`, and prints the returned dict with `json.dumps(result, ensure_ascii=False, indent=2)`.

- [ ] **Step 4: Run helper tests and verify GREEN**

Run Step 2. Expected: PASS.

- [ ] **Step 5: Write failing MCP and sudoers tests**

Add:

```python
def test_reset_telegram_updates_requires_confirmation(self):
    server = load_server()
    with patch.object(server, "run_ssh") as run_ssh:
        output = server.reset_mikroclear_telegram_updates()
    self.assertIn("confirm=True", output)
    run_ssh.assert_not_called()

def test_reset_telegram_updates_uses_exact_helper_argument(self):
    server = load_server()
    with patch.object(server, "run_ssh") as run_ssh:
        server.reset_mikroclear_telegram_updates(confirm=True)
    self.assertEqual(
        run_ssh.call_args.args[0],
        "sudo -n /usr/local/sbin/mikroclear-telegram-getupdates-probe --reset-allowed-updates",
    )
```

Assert the sudoers file contains the exact argument form in addition to the existing no-argument form.

- [ ] **Step 6: Run MCP/sudoers tests and verify RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_mcp_server tests.test_sudoers -v
```

Expected: FAIL because the reset tool and exact sudo rule do not exist.

- [ ] **Step 7: Add confirmed MCP reset and exact sudo rule**

Add:

```python
@mcp.tool()
def reset_mikroclear_telegram_updates(confirm: bool = False) -> str:
    if not confirm:
        return "Refusing to reset Telegram allowed_updates without confirm=True."
    return run_ssh(f"sudo -n {TELEGRAM_UPDATES_PROBE} --reset-allowed-updates", 30)
```

Add `/usr/local/sbin/mikroclear-telegram-getupdates-probe --reset-allowed-updates` as a separate exact sudoers command. Do not remove or modify any existing command.

- [ ] **Step 8: Run all diagnostic tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_telegram_getupdates_probe tests.test_mcp_server tests.test_sudoers tests.test_selks_codex_sudoers_installer -v
```

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

```bash
git add deploy/bin/mikroclear-telegram-getupdates-probe tests/test_telegram_getupdates_probe.py services/mcp-server/server.py tests/test_mcp_server.py deploy/sudoers.d/mikroclear-mcp-selks tests/test_sudoers.py
git commit -m "Make Telegram diagnostics read only by default"
```

### Task 4: Production Polling Artifact Comparison

**Files:**
- Modify: `services/mcp-server/server.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Produces: `compare_production_polling() -> dict[str, Any]`.
- Preserves: all existing MCP tool names and deploy operations.

- [ ] **Step 1: Write failing match and mismatch tests**

Mock `run_ssh` with three lines: remote path, SHA-256, and base64 content:

```python
def test_compare_production_polling_reports_match(self):
    server = load_server()
    local_bytes = server.LOCAL_POLLING.read_bytes()
    remote = "\n".join([
        "/opt/mikroclear-venv/lib/python3.11/site-packages/mikroclear/telegram/polling.py",
        hashlib.sha256(local_bytes).hexdigest(),
        base64.b64encode(local_bytes).decode("ascii"),
    ])
    with patch.object(server, "run_ssh", return_value=remote):
        result = server.compare_production_polling()
    self.assertTrue(result["matches"])
    self.assertEqual(result["diff"], "")
```

The mismatch test returns different content and asserts a non-empty unified diff.

- [ ] **Step 2: Run MCP tests and verify RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_mcp_server.McpServerSshTests.test_compare_production_polling_reports_match -v
```

Expected: ERROR because `LOCAL_POLLING` and `compare_production_polling` do not exist.

- [ ] **Step 3: Implement production comparison**

Add `LOCAL_POLLING` and a read-only tool:

```python
LOCAL_POLLING = REPO_ROOT / "src" / "mikroclear" / "telegram" / "polling.py"

@mcp.tool()
def compare_production_polling() -> dict[str, Any]:
    local_bytes = LOCAL_POLLING.read_bytes()
    command = (
        "/opt/mikroclear-venv/bin/python -c \"import base64,hashlib; "
        "from pathlib import Path; import mikroclear.telegram.polling as p; "
        "path=Path(p.__file__); data=path.read_bytes(); print(path); "
        "print(hashlib.sha256(data).hexdigest()); "
        "print(base64.b64encode(data).decode('ascii'))\""
    )
    lines = run_ssh(command, 30).splitlines()
    if len(lines) != 3:
        return {"matches": False, "error": "Unexpected remote polling response"}
    remote_path, remote_sha256, encoded = lines
    remote_bytes = base64.b64decode(encoded, validate=True)
    local_text = local_bytes.decode("utf-8")
    remote_text = remote_bytes.decode("utf-8")
    return {
        "matches": local_bytes == remote_bytes,
        "local_path": str(LOCAL_POLLING),
        "local_sha256": hashlib.sha256(local_bytes).hexdigest(),
        "remote_path": remote_path,
        "remote_sha256": remote_sha256,
        "diff": "\n".join(difflib.unified_diff(
            remote_text.splitlines(), local_text.splitlines(),
            fromfile=remote_path, tofile=str(LOCAL_POLLING), lineterm="",
        )),
    }
```

- [ ] **Step 4: Run MCP tests and verify GREEN**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_mcp_server -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add services/mcp-server/server.py tests/test_mcp_server.py
git commit -m "Add production Telegram polling comparison"
```

### Task 5: Incident Report, Full Verification, and Review

**Files:**
- Modify: `docs/ru/telegram-bot-incident-2026-07-14.md`

**Interfaces:**
- Documents: safe operator sequence and revised root-cause confidence.
- Changes no runtime interfaces.

- [ ] **Step 1: Update incident conclusions and operator sequence**

Replace the primary recommendation with this ordered procedure:

```text
1. Run the read-only probe and record config/runtime token fingerprints, getMe identity, and getWebhookInfo.
2. Compare the production polling module with the local artifact.
3. Stop mikroclear.service with explicit confirmation.
4. Run the confirmed allowed_updates reset and verify post-reset state.
5. Send /status only after reset verification.
6. Start the service and inspect polling/update/response markers.
7. Use a new bot identity only as a controlled experiment if the same artifact and token identity are confirmed.
```

State explicitly that the original stop-test did not prove Telegram-side root cause because subscription reset and post-readback were not established before the test message.

- [ ] **Step 2: Run focused Telegram and MCP suites**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_telegram_notify tests.test_telegram_command_boundary tests.test_telegram_commands tests.test_telegram_polling tests.test_telegram_polling_worker tests.test_telegram_getupdates_probe tests.test_mcp_server tests.test_sudoers tests.test_runtime tests.test_settings tests.test_app -v
```

Expected: PASS.

- [ ] **Step 3: Run the full test suite**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests PASS with no live Telegram or RouterOS traffic.

- [ ] **Step 4: Run syntax and repository checks**

```bash
bash -n scripts/install-selks-codex-sudoers.sh
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -c "from pathlib import Path; [compile(Path(p).read_text(encoding='utf-8'), p, 'exec') for p in ['deploy/bin/mikroclear-telegram-getupdates-probe', 'deploy/bin/mikroclear-service-env', 'deploy/bin/mikroclear-mask-env']]; print('helper syntax OK')"
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m compileall -q src tests services
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -c "import pathlib,re; pattern=re.compile(r'bot[0-9]{6,}:[A-Za-z0-9_-]{20,}'); roots=[pathlib.Path('src'),pathlib.Path('services'),pathlib.Path('deploy'),pathlib.Path('config')]; hits=[str(path) for root in roots for path in root.rglob('*') if path.is_file() and pattern.search(path.read_text(encoding='utf-8', errors='ignore'))]; assert not hits, hits; print('secret scan OK')"
git diff --check
```

Expected: every command exits 0 and prints no secret value.

- [ ] **Step 5: Confirm scope and commit documentation**

Verify `git diff` contains no removal of existing sudo commands and no production mutation. Then commit:

```bash
git add docs/ru/telegram-bot-incident-2026-07-14.md
git commit -m "Update Telegram incident recovery procedure"
```

- [ ] **Step 6: Request code review**

Invoke `superpowers:requesting-code-review` against the commits created by Tasks 1-5. Resolve high-confidence findings, rerun focused and full tests, and report any residual production-only verification separately.
