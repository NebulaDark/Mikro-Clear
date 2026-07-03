# Mikro-Clear Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove confirmed secret-exposure paths, reduce operational log noise, tighten SELKS runtime privileges, and narrow deployment permissions without breaking the currently running `mikroclear.service`.

**Architecture:** Keep the deployed single-file compatibility model until hardening changes are verified, but move reusable security behavior into small testable modules under `src/mikroclear`. Apply hardening in deployable slices: logging safety first, Telegram resilience second, filesystem permissions third, then systemd/sudoers containment.

**Tech Stack:** Python 3.11, unittest, systemd, sudoers, SELKS over SSH, Telegram Bot API over `requests`, RouterOS API over `librouteros`, MCP FastMCP deploy helper.

## Global Constraints

- Never print, store, or commit live Telegram tokens, RouterOS passwords, API keys, cookies, or auth headers.
- All log/error handling changes must preserve enough context for operators while masking secrets.
- Every production deploy must run local tests, local `py_compile`, remote candidate compile, service restart, status check, and masked journal scan.
- `mikroclear.service` must remain active/enabled after each deploy; `mikrocataTZSP0.service` must remain inactive/disabled.
- Keep rollback files until the service has passed post-hardening runtime verification.
- Do not delete journal history containing the exposed token until a replacement token is deployed and operator confirms log-retention tradeoff.

---

## Security Review Findings

### Confirmed Findings

- **MKC-SEC-001 Critical:** Telegram Bot token can be disclosed through exception logging.
- **MKC-SEC-002 High:** Telegram polling network failures create repeated error log noise.
- **MKC-SEC-003 High:** systemd service runs as root with minimal sandboxing.
- **MKC-SEC-004 Medium:** MCP sudoers policy has broad wildcard and `/tmp` deploy surface.
- **MKC-SEC-005 Medium:** runtime state files are world-readable in legacy `/var/lib/mikrocata`.

### Evidence Collected

- `mikroclear.service` is active/running for 12h+.
- `journalctl` showed repeated Telegram `ConnectionError` and `ReadTimeout`.
- Telegram request exceptions included `/bot<TOKEN>/getUpdates` in journal output before masking.
- Remote stat showed:

```text
755 root:root /var/lib/mikrocata
644 root:root /var/lib/mikrocata/telegram-unblock-actions.json
644 root:root /var/lib/mikrocata/savelists-tzsp0.json
600 root:root /etc/mikrocata/mikrocataTZSP0.env
755 root:root /usr/local/bin/mikroclear.py
644 root:root /etc/systemd/system/mikroclear.service
```

- `/etc/mikroclear` and `/var/lib/mikroclear` are not yet present on SELKS.
- Local secret-pattern scan found no committed live token; only a false positive on `SUB-SKILL`.

---

## Task 1: Mask Secrets In All Telegram Logs

**Files:**
- Create: `src/mikroclear/security.py`
- Modify: `src/mikroclear/legacy.py`
- Modify: `src/mikroclear/telegram_notify.py`
- Test: `tests/test_security.py`
- Test: `tests/test_telegram_notify.py`

**Interfaces:**
- Produces: `mask_telegram_bot_token(text: object) -> str`
- Produces: `mask_known_secret(text: object, secret: str | None, label: str = "SECRET") -> str`
- Produces: `sanitize_exception_text(exc: BaseException, *secrets: str) -> str`

- [ ] **Step 1: Write failing token masking tests**

Add to `tests/test_security.py`:

```python
from unittest import TestCase

from mikroclear.security import mask_known_secret, mask_telegram_bot_token, sanitize_exception_text


class SecurityMaskingTests(TestCase):
    def test_masks_telegram_bot_token_in_url(self):
        text = "https://api.telegram.org/bot123456:ABC_def-123/getUpdates"
        self.assertEqual(
            mask_telegram_bot_token(text),
            "https://api.telegram.org/bot***MASKED***/getUpdates",
        )

    def test_masks_known_secret_value(self):
        self.assertEqual(mask_known_secret("token=abc123", "abc123", "TOKEN"), "token=***MASKED***")

    def test_sanitize_exception_text_masks_known_secret_and_bot_url(self):
        exc = RuntimeError("failed https://api.telegram.org/bot123456:ABC_def-123/getUpdates token=abc123")
        self.assertNotIn("ABC_def-123", sanitize_exception_text(exc, "abc123"))
        self.assertNotIn("abc123", sanitize_exception_text(exc, "abc123"))
```

Run:

```bash
.venv/bin/python -m unittest tests.test_security
```

Expected: fail because `mikroclear.security` does not exist.

- [ ] **Step 2: Implement `src/mikroclear/security.py`**

Implement:

```python
import re
from typing import Any


TELEGRAM_BOT_TOKEN_RE = re.compile(r"/bot[0-9]+:[A-Za-z0-9_-]+/")


def mask_telegram_bot_token(text: Any) -> str:
    return TELEGRAM_BOT_TOKEN_RE.sub("/bot***MASKED***/", str(text))


def mask_known_secret(text: Any, secret: str | None, label: str = "SECRET") -> str:
    value = str(text)
    if secret:
        value = value.replace(secret, f"***{label}***")
    return mask_telegram_bot_token(value)


def sanitize_exception_text(exc: BaseException, *secrets: str) -> str:
    value = f"{type(exc).__name__}: {exc}"
    for secret in secrets:
        value = mask_known_secret(value, secret)
    return mask_telegram_bot_token(value)
```

- [ ] **Step 3: Use sanitizer in Telegram exception logging**

Update `src/mikroclear/legacy.py`:

```python
try:
    from mikroclear.security import sanitize_exception_text
except Exception:  # pragma: no cover - production single-file fallback
    def sanitize_exception_text(exc: BaseException, *secrets: str) -> str:
        text = f"{type(exc).__name__}: {exc}"
        text = re.sub(r"/bot[0-9]+:[A-Za-z0-9_-]+/", "/bot***MASKED***/", text)
        for secret in secrets:
            if secret:
                text = text.replace(secret, "***SECRET***")
        return text
```

Replace raw Telegram exception logs:

```python
log(f"Error answering Telegram callback: {sanitize_exception_text(exc, TELEGRAM_TOKEN)}")
log(f"Error processing Telegram updates: {sanitize_exception_text(exc, TELEGRAM_TOKEN)}")
log(f"Error sending Telegram message: {sanitize_exception_text(exc, TELEGRAM_TOKEN)}")
```

- [ ] **Step 4: Run focused tests**

```bash
.venv/bin/python -m unittest tests.test_security tests.test_telegram_notify tests.test_rebrand
```

Expected: OK.

- [ ] **Step 5: Deploy and verify masked logs**

Run standard deploy workflow, then:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'sudo -n journalctl -u mikroclear.service -n 200 --no-pager | sed -E "s#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g" | grep -Ei "telegram|bot\\*\\*\\*MASKED|error" | tail -n 50'
```

Expected: no raw `/bot<number>:<token>/` strings.

- [ ] **Step 6: Commit**

```bash
git --git-dir=.git-local --work-tree=. add src/mikroclear/security.py src/mikroclear/legacy.py tests/test_security.py tests/test_telegram_notify.py
git --git-dir=.git-local --work-tree=. commit -m "Mask secrets in Telegram logs"
```

---

## Task 2: Add Telegram Polling Backoff And Error Suppression

**Files:**
- Create: `src/mikroclear/telegram_polling.py`
- Modify: `src/mikroclear/legacy.py`
- Test: `tests/test_telegram_polling.py`

**Interfaces:**
- Produces: `TelegramPollingBackoff`
- Produces: `should_poll(now: float) -> bool`
- Produces: `record_success(now: float) -> None`
- Produces: `record_failure(now: float, error_key: str) -> tuple[bool, int]`

- [ ] **Step 1: Write failing backoff tests**

Add to `tests/test_telegram_polling.py`:

```python
from unittest import TestCase

from mikroclear.telegram_polling import TelegramPollingBackoff


class TelegramPollingBackoffTests(TestCase):
    def test_failure_increases_backoff_to_maximum(self):
        backoff = TelegramPollingBackoff(base_seconds=30, max_seconds=300, log_every_seconds=120)
        self.assertEqual(backoff.record_failure(100.0, "ConnectionError"), (True, 30))
        self.assertEqual(backoff.record_failure(130.0, "ConnectionError"), (False, 60))
        self.assertEqual(backoff.record_failure(190.0, "ConnectionError"), (False, 120))
        self.assertEqual(backoff.record_failure(310.0, "ConnectionError"), (True, 240))
        self.assertEqual(backoff.record_failure(550.0, "ConnectionError"), (True, 300))

    def test_success_resets_backoff(self):
        backoff = TelegramPollingBackoff(base_seconds=30, max_seconds=300, log_every_seconds=120)
        backoff.record_failure(100.0, "ReadTimeout")
        backoff.record_success(130.0)
        self.assertTrue(backoff.should_poll(131.0))
        self.assertEqual(backoff.record_failure(131.0, "ReadTimeout"), (True, 30))
```

Run:

```bash
.venv/bin/python -m unittest tests.test_telegram_polling
```

Expected: fail because module does not exist.

- [ ] **Step 2: Implement module**

Create `src/mikroclear/telegram_polling.py`:

```python
from dataclasses import dataclass


@dataclass
class TelegramPollingBackoff:
    base_seconds: int = 30
    max_seconds: int = 300
    log_every_seconds: int = 120
    failure_count: int = 0
    next_poll_at: float = 0.0
    last_logged_at: float = 0.0
    last_error_key: str = ""

    def should_poll(self, now: float) -> bool:
        return now >= self.next_poll_at

    def record_success(self, now: float) -> None:
        self.failure_count = 0
        self.next_poll_at = now
        self.last_logged_at = 0.0
        self.last_error_key = ""

    def record_failure(self, now: float, error_key: str) -> tuple[bool, int]:
        delay = min(self.max_seconds, self.base_seconds * (2 ** self.failure_count))
        self.failure_count += 1
        self.next_poll_at = now + delay
        should_log = error_key != self.last_error_key or now - self.last_logged_at >= self.log_every_seconds
        if should_log:
            self.last_logged_at = now
            self.last_error_key = error_key
        return should_log, delay
```

- [ ] **Step 3: Wire into `process_telegram_updates`**

Add globals in `legacy.py`:

```python
telegram_polling_backoff = TelegramPollingBackoff(
    base_seconds=max(TELEGRAM_UPDATES_INTERVAL_SECONDS, 30),
    max_seconds=300,
    log_every_seconds=120,
)
```

At start of `process_telegram_updates()`:

```python
now = time()
if not telegram_polling_backoff.should_poll(now):
    return
```

On successful `response.status_code == 200` and `body.get("ok")`:

```python
telegram_polling_backoff.record_success(now)
```

On exceptions:

```python
safe_error = sanitize_exception_text(exc, TELEGRAM_TOKEN)
should_log, delay = telegram_polling_backoff.record_failure(time(), safe_error)
if should_log:
    log(f"Error processing Telegram updates; retry in {delay}s: {safe_error}")
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_telegram_polling tests.test_telegram_unblock tests.test_rebrand
```

Expected: OK.

- [ ] **Step 5: Deploy and verify lower noise**

After deploy, watch logs for 10 minutes:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'sudo -n journalctl -u mikroclear.service -n 200 --no-pager | grep -Ei "Telegram updates|retry in|Network is unreachable|ReadTimeout" | tail -n 50'
```

Expected: repeated Telegram outage logs appear with backoff delay, not every loop.

- [ ] **Step 6: Commit**

```bash
git --git-dir=.git-local --work-tree=. add src/mikroclear/telegram_polling.py src/mikroclear/legacy.py tests/test_telegram_polling.py
git --git-dir=.git-local --work-tree=. commit -m "Add Telegram polling backoff"
```

---

## Task 3: Rotate Telegram Token And Clean Exposed Logs

**Files:**
- Modify: `docs/runbook.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: fixed masked logging from Task 1.
- Produces: documented operator flow for rotating the token and handling existing journal exposure.

- [ ] **Step 1: Rotate token in BotFather**

Operator action:

```text
BotFather -> /mybots -> select bot -> API Token -> Revoke current token -> Generate new token
```

Do not paste the token in chat or terminal output.

- [ ] **Step 2: Update SELKS env without exposing token**

Run on SELKS as sudo-capable operator:

```bash
sudoedit /etc/mikrocata/mikrocataTZSP0.env
```

Replace only:

```text
MIKROCATA_TELEGRAM_TOKEN="<new-token>"
```

- [ ] **Step 3: Restart and verify**

```bash
sudo systemctl restart mikroclear.service
sudo systemctl status mikroclear.service --no-pager --lines=25
sudo journalctl -u mikroclear.service -n 100 --no-pager | sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g'
```

- [ ] **Step 4: Decide journal retention**

If policy allows removing logs containing the old token:

```bash
sudo journalctl --rotate
sudo journalctl --vacuum-time=1s
```

If logs must be retained, record that the old token was revoked and no longer grants access.

- [ ] **Step 5: Commit runbook update**

```bash
git --git-dir=.git-local --work-tree=. add docs/runbook.md README.md
git --git-dir=.git-local --work-tree=. commit -m "Document Telegram token rotation"
```

---

## Task 4: Lock Down Runtime State File Permissions

**Files:**
- Modify: `src/mikroclear/telegram_unblock.py`
- Modify: `src/mikroclear/legacy.py`
- Test: `tests/test_telegram_unblock.py`
- Test: `tests/test_runtime_permissions.py`

**Interfaces:**
- Produces: `ensure_private_file(path: Path) -> None`
- Produces: state directory mode `0700`
- Produces: token state file mode `0600`

- [ ] **Step 1: Write failing permission tests**

Add to `tests/test_runtime_permissions.py`:

```python
import os
from pathlib import Path
import tempfile
from unittest import TestCase

from mikroclear.telegram_unblock import ensure_private_state_path


class RuntimePermissionTests(TestCase):
    def test_ensure_private_state_path_sets_private_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "telegram-unblock-actions.json"
            ensure_private_state_path(path)
            self.assertEqual(oct(path.parent.stat().st_mode & 0o777), "0o700")
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
```

- [ ] **Step 2: Implement permission helper**

In `src/mikroclear/telegram_unblock.py`:

```python
def ensure_private_state_path(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if not path.exists():
        path.write_text("{}", encoding="utf-8")
    os.chmod(path, 0o600)
```

Call this before loading/writing token state.

- [ ] **Step 3: Apply remote chmod immediately after deploy**

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'sudo chmod 700 /var/lib/mikrocata && sudo chmod 600 /var/lib/mikrocata/telegram-unblock-actions.json /var/lib/mikrocata/savelists-tzsp0.json'
```

- [ ] **Step 4: Verify remote modes**

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'stat -c "%a %U:%G %n" /var/lib/mikrocata /var/lib/mikrocata/telegram-unblock-actions.json /var/lib/mikrocata/savelists-tzsp0.json'
```

Expected:

```text
700 root:root /var/lib/mikrocata
600 root:root /var/lib/mikrocata/telegram-unblock-actions.json
600 root:root /var/lib/mikrocata/savelists-tzsp0.json
```

- [ ] **Step 5: Commit**

```bash
git --git-dir=.git-local --work-tree=. add src/mikroclear/telegram_unblock.py src/mikroclear/legacy.py tests/test_telegram_unblock.py tests/test_runtime_permissions.py
git --git-dir=.git-local --work-tree=. commit -m "Restrict runtime state permissions"
```

---

## Task 5: Migrate Env And State Paths To Mikro-Clear Names

**Files:**
- Modify: `systemd/mikroclear.service`
- Modify: `config/mikroclear.env.example`
- Modify: `README.md`
- Modify: `docs/runbook.md`
- Test: `tests/test_systemd_unit.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: current fallback support for `MIKROCATA_*`.
- Produces: primary `/etc/mikroclear/mikroclear.env` and `/var/lib/mikroclear`.

- [ ] **Step 1: Create SELKS target directories**

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'sudo install -d -o root -g root -m 700 /etc/mikroclear /var/lib/mikroclear'
```

- [ ] **Step 2: Copy and migrate env**

Run on SELKS:

```bash
sudo cp -a /etc/mikrocata/mikrocataTZSP0.env /etc/mikroclear/mikroclear.env
sudo sed -i 's/^MIKROCATA_/MIKROCLEAR_/' /etc/mikroclear/mikroclear.env
sudo sed -i 's#^MIKROCLEAR_STATE_DIR=.*#MIKROCLEAR_STATE_DIR="/var/lib/mikroclear"#' /etc/mikroclear/mikroclear.env
sudo chmod 600 /etc/mikroclear/mikroclear.env
```

- [ ] **Step 3: Preserve legacy env fallback in unit temporarily**

Keep both lines in `systemd/mikroclear.service` until one stable restart with new env:

```ini
EnvironmentFile=-/etc/mikrocata/mikrocataTZSP0.env
EnvironmentFile=-/etc/mikroclear/mikroclear.env
```

- [ ] **Step 4: Restart and verify config source**

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'sudo systemctl restart mikroclear.service && sudo systemctl status mikroclear.service --no-pager --lines=25'
```

- [ ] **Step 5: Commit docs/tests**

```bash
git --git-dir=.git-local --work-tree=. add systemd/mikroclear.service config/mikroclear.env.example README.md docs/runbook.md tests/test_systemd_unit.py tests/test_config.py
git --git-dir=.git-local --work-tree=. commit -m "Migrate Mikro-Clear env and state paths"
```

---

## Task 6: Harden systemd Unit Incrementally

**Files:**
- Modify: `systemd/mikroclear.service`
- Test: `tests/test_systemd_unit.py`

**Interfaces:**
- Produces: stricter sandbox while preserving eve.json read access and state writes.

- [ ] **Step 1: Add systemd unit tests**

Assert unit contains:

```text
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
RestrictSUIDSGID=true
LockPersonality=true
ReadWritePaths=/var/lib/mikroclear /var/lib/mikrocata
ReadOnlyPaths=/opt/SELKS/docker/containers-data/suricata/logs /etc/mikroclear /etc/mikrocata
```

- [ ] **Step 2: Update unit**

Add:

```ini
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true
ReadWritePaths=/var/lib/mikroclear /var/lib/mikrocata
ReadOnlyPaths=/opt/SELKS/docker/containers-data/suricata/logs /etc/mikroclear /etc/mikrocata
```

Do not change `User=root` in this task; sandbox first, user separation later.

- [ ] **Step 3: Verify unit on SELKS before deploy**

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks '/usr/bin/systemd-analyze verify /tmp/mikroclear-codex.service'
```

- [ ] **Step 4: Deploy unit and verify runtime**

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'sudo -n systemctl status mikroclear.service --no-pager --lines=30'
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'sudo -n journalctl -u mikroclear.service -n 100 --no-pager | grep -Ei "permission denied|protect|read-only|failed|traceback" || true'
```

- [ ] **Step 5: Commit**

```bash
git --git-dir=.git-local --work-tree=. add systemd/mikroclear.service tests/test_systemd_unit.py
git --git-dir=.git-local --work-tree=. commit -m "Harden Mikro-Clear systemd sandbox"
```

---

## Task 7: Narrow MCP sudoers And Move Candidates Out Of `/tmp`

**Files:**
- Modify: `services/mcp-server/server.py`
- Modify: `deploy/sudoers.d/mikroclear-mcp-selks`
- Modify: `tests/test_mcp_server.py`
- Modify: `tests/test_sudoers.py`
- Modify: `README.md`

**Interfaces:**
- Produces: candidate directory `/var/tmp/mikroclear-deploy`
- Produces: candidate files `/var/tmp/mikroclear-deploy/mikroclear.py.codex-candidate` and `/var/tmp/mikroclear-deploy/mikroclear-codex.service`

- [ ] **Step 1: Update tests to expect secure candidate directory**

Expected constants:

```python
CANDIDATE_DIR = "/var/tmp/mikroclear-deploy"
CANDIDATE_SCRIPT = "/var/tmp/mikroclear-deploy/mikroclear.py.codex-candidate"
CANDIDATE_UNIT = "/var/tmp/mikroclear-deploy/mikroclear-codex.service"
```

- [ ] **Step 2: Update MCP upload commands**

Before writing candidates:

```bash
install -d -m 700 /var/tmp/mikroclear-deploy
```

After upload:

```bash
chmod 600 /var/tmp/mikroclear-deploy/mikroclear.py.codex-candidate
chmod 600 /var/tmp/mikroclear-deploy/mikroclear-codex.service
```

- [ ] **Step 3: Update sudoers**

Remove legacy install/restart entries after rollback window:

```text
/usr/bin/systemctl restart mikrocataTZSP0.service
/usr/bin/install ... mikrocataTZSP0...
```

Narrow logs to fixed sizes:

```text
/usr/bin/journalctl -u mikroclear.service -n 100 --no-pager
/usr/bin/journalctl -u mikroclear.service -n 300 --no-pager
/usr/bin/journalctl -u mikroclear.service -n 500 --no-pager
```

- [ ] **Step 4: Validate sudoers**

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks '/usr/sbin/visudo -cf /tmp/mikroclear-mcp-selks.sudoers'
```

- [ ] **Step 5: Commit**

```bash
git --git-dir=.git-local --work-tree=. add services/mcp-server/server.py deploy/sudoers.d/mikroclear-mcp-selks tests/test_mcp_server.py tests/test_sudoers.py README.md
git --git-dir=.git-local --work-tree=. commit -m "Narrow MCP deploy sudoers policy"
```

---

## Task 8: Evaluate Dedicated `mikroclear` Service User

**Files:**
- Modify: `systemd/mikroclear.service`
- Modify: `docs/runbook.md`
- Test: `tests/test_systemd_unit.py`

**Interfaces:**
- Produces: decision record for root vs dedicated service user.

- [ ] **Step 1: Check eve.json access requirements**

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'stat -c "%a %U:%G %n" /opt/SELKS/docker/containers-data/suricata/logs /opt/SELKS/docker/containers-data/suricata/logs/eve.json'
```

- [ ] **Step 2: If readable via group/ACL, create user**

```bash
sudo useradd --system --home /var/lib/mikroclear --shell /usr/sbin/nologin mikroclear
sudo chown -R mikroclear:mikroclear /var/lib/mikroclear
sudo setfacl -m u:mikroclear:r /opt/SELKS/docker/containers-data/suricata/logs/eve.json
```

- [ ] **Step 3: Change unit only after access is proven**

```ini
User=mikroclear
Group=mikroclear
```

- [ ] **Step 4: Deploy and verify**

```bash
systemctl status mikroclear.service --no-pager --lines=30
journalctl -u mikroclear.service -n 100 --no-pager | grep -Ei "permission denied|failed|traceback" || true
```

- [ ] **Step 5: Commit or document root exception**

If root remains required, document why and keep systemd sandbox from Task 6.

---

## Task 9: Add Security Runbook And Recurring Checks

**Files:**
- Create: `docs/security-runbook.md`
- Modify: `README.md`

**Interfaces:**
- Produces: repeatable operator checklist.

- [ ] **Step 1: Document weekly checks**

Include:

```bash
systemctl status mikroclear.service --no-pager --lines=25
journalctl -u mikroclear.service -n 500 --no-pager | sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g' | grep -Ei 'error|traceback|failed|token|bot'
stat -c '%a %U:%G %n' /etc/mikroclear/mikroclear.env /var/lib/mikroclear
```

- [ ] **Step 2: Document token rotation**

Include BotFather rotation, env update, restart, and journal retention decision.

- [ ] **Step 3: Document deploy verification**

Include local tests, remote compile, systemd status, masked journal scan, rollback backup path.

- [ ] **Step 4: Commit**

```bash
git --git-dir=.git-local --work-tree=. add docs/security-runbook.md README.md
git --git-dir=.git-local --work-tree=. commit -m "Add Mikro-Clear security runbook"
```

---

## Standard Security Verification Before Completion

- [ ] Local tests:

```bash
.venv/bin/python -m unittest discover -s tests
```

- [ ] Local compile:

```bash
.venv/bin/python -m py_compile src/mikroclear/*.py services/mcp-server/server.py
```

- [ ] Local secret-pattern scan with masking:

```bash
rg -n "bot[0-9]+:|sk-[A-Za-z0-9_-]+|BEGIN (RSA|OPENSSH|PRIVATE) KEY|TOKEN=.+|PASSWORD=.+" . | sed -E 's#bot[0-9]+:[A-Za-z0-9_-]+#bot***MASKED***#g; s#(TOKEN|PASSWORD)=.*#\\1=***MASKED***#g'
```

- [ ] Remote service status:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'systemctl is-active mikroclear.service; systemctl is-enabled mikroclear.service'
```

- [ ] Remote masked journal scan:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'sudo -n journalctl -u mikroclear.service -n 500 --no-pager | sed -E "s#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g" | grep -Ei "error|traceback|failed|bot[0-9]+:" || true'
```

- [ ] Remote permissions check:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'stat -c "%a %U:%G %n" /etc/mikroclear /etc/mikroclear/mikroclear.env /var/lib/mikroclear /var/lib/mikroclear/telegram-unblock-actions.json 2>/dev/null || true'
```

