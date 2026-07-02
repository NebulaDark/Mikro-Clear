# Mikro-Clear Global Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Mikro-Clear into a maintainable, deployable SELKS-to-MikroTik security service with clean naming, modular code, Telegram control, safe deployment, and operational checks.

**Architecture:** Keep the current production-compatible script running while gradually extracting focused modules from `src/mikroclear/legacy.py`. Preserve backward compatibility for deployed SELKS configuration during the migration, but make all new names, service units, docs, and deploy tooling use `Mikro-Clear`.

**Tech Stack:** Python 3.11 on SELKS, `librouteros`, `pyinotify`, systemd, Telegram Bot API over `requests`, MCP FastMCP deploy helper, unittest.

## Global Constraints

- Production host: `selks`.
- Production service name: `mikroclear.service`.
- Legacy service name kept only for migration: `mikrocataTZSP0.service`.
- Production script: `/usr/local/bin/mikroclear.py`.
- Legacy production script kept only for backup/rollback: `/usr/local/bin/mikrocataTZSP0.py`.
- New package namespace: `mikroclear`.
- Legacy package namespace `mikrocata` remains as import compatibility shims only.
- New env prefix: `MIKROCLEAR_*`.
- Legacy env prefix `MIKROCATA_*` remains as fallback until config migration is complete.
- Every deploy must run syntax checks, service restart, status check, and journal error scan.
- Do not remove rollback files or old unit files until the new service has been stable through multiple alert cycles.

---

## Completed

- [x] Extracted alert target selection and deduplication logic.
- [x] Added event validation/filtering module.
- [x] Added Telegram inline unblock callback flow.
- [x] Added MCP deploy tooling and restricted sudoers policy.
- [x] Fixed systemd `StartLimitIntervalSec` placement.
- [x] Renamed project runtime identity to `Mikro-Clear`.
- [x] Renamed primary package to `src/mikroclear`.
- [x] Added `src/mikrocata` compatibility shims.
- [x] Renamed production service to `mikroclear.service`.
- [x] Deployed `/usr/local/bin/mikroclear.py` and `mikroclear.service` to SELKS.
- [x] Disabled legacy `mikrocataTZSP0.service`.
- [x] Fixed deployed `NameError: name 'severity' is not defined`.
- [x] Verified local test suite: `38 tests OK`.

---

## Phase 1: Post-Migration Monitoring

### Task 1: Verify Runtime Health After Rebrand

**Files:**
- Read: `README.md`
- Read: `services/mcp-server/server.py`

**Interfaces:**
- Consumes: deployed `mikroclear.service`.
- Produces: confidence that the rebrand did not break runtime behavior.

- [x] Check service state on SELKS.

Run:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'systemctl is-active mikroclear.service; systemctl is-enabled mikroclear.service'
```

Expected:

```text
active
enabled
```

- [x] Check old service remains stopped.

Run:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'systemctl is-active mikrocataTZSP0.service || true; systemctl is-enabled mikrocataTZSP0.service || true'
```

Expected:

```text
inactive
disabled
```

- [x] Scan logs for fresh errors.

Run:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks 'sudo -n journalctl -u mikroclear.service --since "1 hour ago" --no-pager | grep -Ei "error|traceback|nameerror|failed" || true'
```

Expected: no output.

- [x] Commit any documentation updates discovered during verification.

Verified on 2026-07-02:

```text
mikroclear.service: active/enabled
mikrocataTZSP0.service: inactive/disabled
journal: no fresh error/traceback/nameerror/failed lines in last 500 entries
telegram unblock observed: 147.45.112.175 from Suricata - SID:2023753
```

---

## Phase 2: Move Away From Hardcode In One File

### Task 2: Extract Configuration Loading

**Files:**
- Create: `src/mikroclear/config.py`
- Modify: `src/mikroclear/legacy.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `env_name_candidates(name: str) -> tuple[str, ...]`
- Produces: `env_str(name: str, default: str) -> str`
- Produces: `env_bool(name: str, default: bool) -> bool`
- Produces: `env_int(name: str, default: int) -> int`
- Produces: `env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]`

- [x] Write tests proving `MIKROCLEAR_*` overrides `MIKROCATA_*`.
- [x] Move env helper functions from `legacy.py` to `config.py`.
- [x] Update `legacy.py` imports.
- [x] Run:

```bash
.venv/bin/python -m unittest tests.test_config tests.test_rebrand
```

- [x] Commit:

```bash
git --git-dir=.git-local --work-tree=. commit -m "Extract Mikro-Clear configuration helpers"
```

### Task 3: Extract Telegram Formatting And Delivery

**Files:**
- Create: `src/mikroclear/telegram_notify.py`
- Modify: `src/mikroclear/legacy.py`
- Test: `tests/test_telegram_notify.py`

**Interfaces:**
- Produces: `format_alert_message(event, wanted_ip, peer_ip, wanted_port, action_type) -> str`
- Produces: `format_system_message(message: str, event_type: str) -> str`
- Produces: `send_telegram_message(token, chat_id, text, reply_markup=None, timeout=10) -> bool`

- [ ] Move Telegram message formatting out of `legacy.py`.
- [ ] Keep existing Telegram unblock module unchanged unless imports need updating.
- [ ] Verify notification text says `Mikro-Clear` and `#mikroclear`.
- [ ] Run:

```bash
.venv/bin/python -m unittest tests.test_telegram_notify tests.test_telegram_unblock tests.test_rebrand
```

- [ ] Commit:

```bash
git --git-dir=.git-local --work-tree=. commit -m "Extract Telegram notification handling"
```

### Task 4: Extract RouterOS Client Operations

**Files:**
- Create: `src/mikroclear/routeros_client.py`
- Modify: `src/mikroclear/legacy.py`
- Test: `tests/test_routeros_client.py`

**Interfaces:**
- Produces: `RouterOsClientConfig`
- Produces: `RouterOsConnectionManager`
- Produces: `remove_from_address_list(api, list_name: str, address: str) -> int`
- Produces: `add_to_address_list(address_list, list_name: str, address: str, comment: str, timeout: str) -> None`

- [ ] Move reconnect wrapper and address-list helpers from `legacy.py`.
- [ ] Keep behavior identical for heartbeat and reconnect logs.
- [ ] Add tests with fake RouterOS resources.
- [ ] Run:

```bash
.venv/bin/python -m unittest tests.test_routeros_client tests.test_telegram_unblock
```

- [ ] Commit:

```bash
git --git-dir=.git-local --work-tree=. commit -m "Extract RouterOS operations"
```

---

## Phase 3: Telegram Control Plane

### Task 5: Add Confirmed Unblock Flow

**Files:**
- Modify: `src/mikroclear/telegram_unblock.py`
- Modify: `src/mikroclear/legacy.py`
- Test: `tests/test_telegram_unblock.py`

**Interfaces:**
- Consumes: existing callback token state file.
- Produces: Telegram callback action that removes IP from MikroTik address-list.

- [ ] Keep existing `Unblock <ip>` inline button.
- [ ] Add callback response text for success, expired token, already removed, and RouterOS failure.
- [ ] Log every unblock action with operator-visible result.
- [ ] Send Telegram system notification after successful unblock.
- [ ] Run:

```bash
.venv/bin/python -m unittest tests.test_telegram_unblock tests.test_rebrand
```

- [ ] Commit:

```bash
git --git-dir=.git-local --work-tree=. commit -m "Harden Telegram unblock callbacks"
```

### Task 6: Add Telegram `/status` Command

**Files:**
- Modify: `src/mikroclear/telegram_unblock.py`
- Modify: `src/mikroclear/legacy.py`
- Test: `tests/test_telegram_commands.py`

**Interfaces:**
- Produces: command handler for `/status`.

- [ ] Return service uptime, RouterOS connection state, monitored EVE path, address-list name, and monitor-only mode.
- [ ] Mask secrets in every response.
- [ ] Reject commands from non-configured chat IDs.
- [ ] Run:

```bash
.venv/bin/python -m unittest tests.test_telegram_commands
```

- [ ] Commit:

```bash
git --git-dir=.git-local --work-tree=. commit -m "Add Telegram status command"
```

---

## Phase 4: Packaging And Deployment Cleanup

### Task 7: Finalize Naming Across Deploy Artifacts

**Files:**
- Modify: `README.md`
- Modify: `config/mikroclear.env.example`
- Modify: `deploy/sudoers.d/mikroclear-mcp-selks`
- Modify: `services/mcp-server/server.py`

**Interfaces:**
- Consumes: current compatibility aliases.
- Produces: deploy tooling where new names are primary and old names are clearly marked legacy.

- [ ] Rename remaining MCP public tools from `*_mikrocata` to `*_mikroclear` where not already done.
- [ ] Keep old MCP tools as compatibility aliases.
- [ ] Document rollback commands using old script/unit.
- [ ] Run:

```bash
.venv/bin/python -m unittest tests.test_mcp_server tests.test_sudoers
```

- [ ] Commit:

```bash
git --git-dir=.git-local --work-tree=. commit -m "Finalize Mikro-Clear deploy naming"
```

### Task 8: Add Installer/Upgrade Script

**Files:**
- Create: `deploy/install-mikroclear.sh`
- Create: `tests/test_install_script.py`
- Modify: `README.md`

**Interfaces:**
- Produces: repeatable install flow for SELKS.

- [ ] Script validates root privileges.
- [ ] Script installs `/usr/local/bin/mikroclear.py`.
- [ ] Script installs `/etc/systemd/system/mikroclear.service`.
- [ ] Script runs `systemd-analyze verify`.
- [ ] Script runs `daemon-reload`, `enable`, and `restart`.
- [ ] Script refuses to proceed if env file is missing unless `--allow-legacy-env` is passed.
- [ ] Run:

```bash
.venv/bin/python -m unittest tests.test_install_script
```

- [ ] Commit:

```bash
git --git-dir=.git-local --work-tree=. commit -m "Add Mikro-Clear installer script"
```

---

## Phase 5: Observability And Operations

### Task 9: Add Structured Runtime Counters

**Files:**
- Create: `src/mikroclear/runtime_state.py`
- Modify: `src/mikroclear/legacy.py`
- Test: `tests/test_runtime_state.py`

**Interfaces:**
- Produces: counters for processed alerts, skipped alerts, blocked IPs, updated IPs, Telegram sends, unblock successes, RouterOS reconnects.

- [ ] Add in-memory counters.
- [ ] Include counters in Telegram `/status`.
- [ ] Log periodic heartbeat with counters every configured heartbeat interval.
- [ ] Run:

```bash
.venv/bin/python -m unittest tests.test_runtime_state tests.test_telegram_commands
```

- [ ] Commit:

```bash
git --git-dir=.git-local --work-tree=. commit -m "Add runtime counters"
```

### Task 10: Add Operational Runbook

**Files:**
- Create: `docs/runbook.md`
- Modify: `README.md`

**Interfaces:**
- Produces: operator documentation for SELKS.

- [ ] Document status checks.
- [ ] Document log checks.
- [ ] Document rollback to `mikrocataTZSP0.service`.
- [ ] Document Telegram unblock behavior.
- [ ] Document env migration from `MIKROCATA_*` to `MIKROCLEAR_*`.
- [ ] Document sudoers update flow.
- [ ] Commit:

```bash
git --git-dir=.git-local --work-tree=. commit -m "Add Mikro-Clear runbook"
```

---

## Phase 6: Compatibility Removal Later

### Task 11: Plan Legacy Removal Only After Stable Runtime

**Files:**
- Modify later: `src/mikrocata/*`
- Modify later: `systemd` legacy references
- Modify later: `deploy/sudoers.d/mikroclear-mcp-selks`

**Interfaces:**
- Consumes: operational evidence that `mikroclear.service` is stable.
- Produces: smaller project with legacy names removed.

- [ ] Keep compatibility for now.
- [ ] After stable runtime, migrate `/etc/mikrocata/mikrocataTZSP0.env` to `/etc/mikroclear/mikroclear.env`.
- [ ] After env migration, remove old env fallback.
- [ ] After rollback window expires, remove old service/script sudoers entries.
- [ ] After external imports are confirmed migrated, remove `src/mikrocata` compatibility shims.

---

## Standard Verification Before Every Deploy

- [ ] Run local unit tests.

```bash
.venv/bin/python -m unittest discover -s tests
```

- [ ] Run local compile check.

```bash
.venv/bin/python -m py_compile src/mikroclear/legacy.py src/mikroclear/events.py src/mikroclear/alert_logic.py src/mikroclear/telegram_unblock.py services/mcp-server/server.py
```

- [ ] Upload candidate script and unit to SELKS.
- [ ] Compile candidate script on SELKS.
- [ ] Verify candidate unit on SELKS.
- [ ] Install candidate script/unit.
- [ ] Restart `mikroclear.service`.
- [ ] Check `systemctl status mikroclear.service --no-pager --lines=25`.
- [ ] Check journal for `error|traceback|nameerror|failed`.
- [ ] Commit after verification.
