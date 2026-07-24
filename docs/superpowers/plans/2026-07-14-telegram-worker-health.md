# Telegram Polling Worker Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `mikroclear.service` fail with exit code 1 when its started Telegram polling thread dies unexpectedly, while keeping normal shutdown and transient main-loop behavior unchanged.

**Architecture:** `TelegramPollingWorker` owns observable thread health and raises a dedicated `TelegramWorkerFatalError` with sanitized diagnostics. `MikroClearService` checks that health on every loop and treats only this exception as fatal; wiring passes start, health, drain, and stop methods from the same worker instance.

**Tech Stack:** Python 3.11+, `threading`, `unittest`, systemd `Restart=on-failure`.

**Status:** Tasks 1-3 completed and locally verified on 2026-07-24. Task 4 remains pending.

## Global Constraints

- Do not call live Telegram API or RouterOS in tests.
- Do not change update ordering, retry delays, acknowledgement semantics, or the RouterOS main-thread boundary.
- Do not expose Telegram token, update body, callback data, or message text in health logs.
- Do not self-restart the worker or create a second consumer inside the process.
- Keep generic main-loop exceptions on the existing log, sleep 5 seconds, and retry path.
- Production deployment must use a wheel built from committed HEAD, SHA-256 verification, backup, runtime acceptance, and automatic rollback on failure.

---

### Task 1: Observable Worker Health

**Files:**
- Modify: `src/mikroclear/telegram/polling_worker.py`
- Test: `tests/test_telegram_polling_worker.py`

**Interfaces:**
- Produces: `TelegramWorkerFatalError(RuntimeError)`.
- Produces: `TelegramPollingWorker.check_health() -> None`.
- Preserves: `start()`, `drain_ready()`, and `stop()` public behavior.

- [x] **Step 1: Write failing health tests**

Add a poller whose `fetch_updates()` raises a token-bearing exception, then assert:

```python
class CrashingPoller(FakePoller):
    def fetch_updates(self, *, long_poll_seconds):
        raise RuntimeError("fatal token")


def test_fatal_worker_error_does_not_expose_update_payload(self):
    logs = []
    poller = CrashingPoller([])
    worker = TelegramPollingWorker(poller, long_poll_seconds=25, log=logs.append)
    worker.start()
    self.assertTrue(wait_until(lambda: worker._thread is not None and not worker._thread.is_alive()))
    with self.assertRaisesRegex(TelegramWorkerFatalError, "RuntimeError"):
        worker.check_health()
    self.assertNotIn("token", " ".join(logs))
```

Add separate tests proving `check_health()` succeeds before `start()`, while an empty polling worker is alive, and after `stop()`.

- [x] **Step 2: Verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_telegram_polling_worker
```

Expected: failure because `TelegramWorkerFatalError` and `check_health()` do not exist.

- [x] **Step 3: Implement the minimal worker health contract**

In `polling_worker.py`:

```python
class TelegramWorkerFatalError(RuntimeError):
    """Raised when a started polling worker exits unexpectedly."""


def _run_guarded(self) -> None:
    try:
        self._run()
    except Exception as exc:
        with self._lifecycle_lock:
            if self._stopping:
                return
            self._fatal_error = type(exc).__name__
            self.log(f"Telegram polling worker failed: {self._fatal_error}")


def check_health(self) -> None:
    with self._lifecycle_lock:
        if not self._started or self._stopping:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        detail = self._fatal_error or "thread exited without an error"
    raise TelegramWorkerFatalError(f"Telegram polling worker is not running: {detail}")
```

Initialize `_started`, `_stopping`, `_fatal_error`, and `_lifecycle_lock`; target
`_run_guarded`; log `Telegram polling worker started`; set `_stopping` under
the same lock before normal stop. Fatal diagnostics store only the exception
class name, and failures released after shutdown begins do not create fatal
state. Export the exception in `__all__`.

- [x] **Step 4: Verify GREEN**

Run the focused command from Step 2. Expected: all worker tests pass with no unhandled thread traceback.

- [x] **Step 5: Commit Task 1**

```bash
git add src/mikroclear/telegram/polling_worker.py tests/test_telegram_polling_worker.py
git commit -m "Add Telegram polling worker health checks"
```

---

### Task 2: Runtime Fail-Fast Semantics

**Files:**
- Modify: `src/mikroclear/runtime/__init__.py`
- Test: `tests/test_runtime.py`

**Interfaces:**
- Consumes: `TelegramWorkerFatalError` from Task 1.
- Produces: `RuntimeDependencies.check_telegram_worker: Callable[[], None]`.
- Preserves: generic exception retry behavior and ordered shutdown.

- [x] **Step 1: Write failing runtime tests**

Extend the dependency fixture with `check_telegram_worker`. Assert `run_once()` calls it before `process_telegram_updates`. Add a test dependency that raises `TelegramWorkerFatalError("worker dead")` and assert:

```python
result = service.run()

self.assertEqual(result, 1)
self.assertIn(("log", "Fatal Telegram polling worker error: worker dead"), calls)
self.assertIn(("stop_telegram_worker",), calls)
self.assertNotIn(("sleep", 5), calls)
```

Keep the existing generic exception test and assert it still sleeps 5 seconds rather than taking the fatal path.

- [x] **Step 2: Verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_runtime
```

Expected: fixture/type failures because `check_telegram_worker` is not part of `RuntimeDependencies`, followed by the missing fatal branch.

- [x] **Step 3: Implement the minimal runtime branch**

Add `check_telegram_worker` to `RuntimeDependencies`, call it first in `run_once()`, and handle the dedicated error outside the generic loop retry:

```python
exit_code = 0
try:
    while not self.shutdown_requested:
        try:
            self.run_once()
        except TelegramWorkerFatalError as exc:
            self.deps.log(f"Fatal Telegram polling worker error: {exc}")
            exit_code = 1
            break
        except Exception as exc:
            ...
finally:
    self.shutdown()
return exit_code
```

- [x] **Step 4: Verify GREEN**

Run the focused command from Step 2. Expected: all runtime tests pass and the existing generic retry assertion remains green.

- [x] **Step 5: Commit Task 2**

```bash
git add src/mikroclear/runtime/__init__.py tests/test_runtime.py
git commit -m "Fail fast when Telegram worker stops"
```

---

### Task 3: Wiring Integration And Verification

**Files:**
- Modify: `src/mikroclear/runtime/wiring.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `TelegramPollingWorker.check_health()` and `RuntimeDependencies.check_telegram_worker`.
- Produces: one worker instance bound to start, health, drain, and stop lifecycle callbacks.

- [x] **Step 1: Write the failing wiring assertion**

In the app wiring test, assert:

```python
self.assertIs(
    service.deps.check_telegram_worker.__self__,
    providers.polling_worker,
)
self.assertIs(
    service.deps.check_telegram_worker.__func__,
    providers.polling_worker.check_health.__func__,
)
```

- [x] **Step 2: Verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_app
```

Expected: failure because wiring does not supply `check_telegram_worker`.

- [x] **Step 3: Wire the same worker health method**

Add:

```python
check_telegram_worker=providers.polling_worker.check_health,
```

between start and drain callbacks in `build_runtime_service()`.

- [x] **Step 4: Run focused and full verification**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_telegram_polling_worker tests.test_runtime tests.test_app
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m compileall -q src tests
git diff --check
```

Expected: focused and full suites pass, compilation exits 0, and `git diff --check` emits no output.

- [x] **Step 5: Scan changed files for secret exposure**

```bash
grep -RInE 'bot[0-9]+:|MIKROCLEAR_TELEGRAM_TOKEN=' src tests docs/superpowers/specs docs/superpowers/plans
```

Expected: no literal Telegram credentials; configuration key references without values are acceptable.

- [x] **Step 6: Commit Task 3**

```bash
git add src/mikroclear/runtime/wiring.py tests/test_app.py docs/superpowers/plans/2026-07-14-telegram-worker-health.md
git commit -m "Wire Telegram worker health into runtime"
```

---

### Task 4: Review, Merge, And Staged SELKS Deploy

**Files:**
- No additional source files unless review finds a defect.
- Artifact: `dist/mikro_clear-0.1.0-py3-none-any.whl` built from merged committed HEAD.

**Interfaces:**
- Consumes: all prior tasks and the existing SELKS wheel deployment boundary.
- Produces: verified production state or verified rollback state.

- [ ] **Step 1: Review the complete branch diff**

Inspect for thread races, shutdown ambiguity, duplicate consumers, exception leakage, and missing tests. Fix findings through an additional TDD cycle before continuing.

- [ ] **Step 2: Merge locally into `main` without including existing dirty dependency files**

Use a fast-forward merge after full tests. Preserve the existing uncommitted `pyproject.toml` and `requirements.txt` changes in the main checkout.

- [ ] **Step 3: Build from committed HEAD in a clean temporary source tree**

Build with `pip wheel --no-deps --no-build-isolation`, validate with `python -m zipfile -t`, and record SHA-256. Do not build from the dirty main checkout.

- [ ] **Step 4: Deploy with rollback ready**

Capture service state, copy the validated wheel, create a site-packages backup, install through the exact allowed sudo command, and restart `mikroclear.service`.

- [ ] **Step 5: Apply runtime acceptance**

Require all of:

```text
ActiveState=active
SubState=running
NRestarts=0
Tasks >= 2
journal contains "Telegram polling worker started"
installed module SHA matches the wheel
no fatal worker error or traceback after at least one 25-second poll window
```

- [ ] **Step 6: Roll back on any failed acceptance condition**

Reinstall the exact rollback wheel matching pre-deploy `polling.py` SHA, restart, and confirm `active/running`, `NRestarts=0`, and the restored source SHA.

- [ ] **Step 7: Report privileged remainder**

If helper and sudoers still differ, report exact candidate hashes and root install commands. Do not claim a full helper/reset deploy until root-owned files match.
