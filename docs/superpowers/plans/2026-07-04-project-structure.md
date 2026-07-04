# Mikro-Clear Project Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape the repository into a package layout that separates runtime orchestration, Suricata parsing, RouterOS integration, Telegram integration, deploy artifacts, and legacy compatibility.

**Architecture:** Create the final package directories first, then move existing extracted modules into those directories with compatibility wrappers at the old import paths. Keep `src/mikroclear/legacy.py` deployable until the service is switched to package entrypoints.

**Tech Stack:** Python 3.11, setuptools package discovery, unittest, systemd, Docker artifacts later.

## Global Constraints

- Keep production behavior unchanged while `mikroclear.service` still runs `/usr/local/bin/mikroclear.py`.
- Preserve old import paths until all call sites and tests have migrated.
- Add tests for every new public import path before moving code.
- Keep `src/mikroclear/legacy.py` as a compatibility wrapper until runtime orchestration has moved.
- Do not introduce Docker or binary build artifacts before package boundaries are stable.

---

## Target Structure

```text
src/mikroclear/
├── __init__.py
├── __main__.py
├── cli.py
├── app.py
├── settings.py
├── runtime.py
├── logging.py
├── eve_watcher.py
├── alert_processor.py
├── asset_resolver.py
├── state_store.py
├── routeros/
│   ├── __init__.py
│   ├── client.py
│   ├── tls.py
│   └── address_list.py
├── telegram/
│   ├── __init__.py
│   ├── notify.py
│   ├── polling.py
│   ├── unblock.py
│   └── commands.py
├── suricata/
│   ├── __init__.py
│   ├── events.py
│   └── alert_logic.py
├── security.py
└── legacy.py
```

## Task 1: Move Extracted Modules Into Domain Packages

**Files:**
- Create: `src/mikroclear/routeros/__init__.py`
- Create: `src/mikroclear/routeros/client.py`
- Create: `src/mikroclear/routeros/tls.py`
- Create: `src/mikroclear/routeros/address_list.py`
- Create: `src/mikroclear/telegram/__init__.py`
- Create: `src/mikroclear/telegram/notify.py`
- Create: `src/mikroclear/telegram/polling.py`
- Create: `src/mikroclear/telegram/unblock.py`
- Create: `src/mikroclear/telegram/commands.py`
- Create: `src/mikroclear/suricata/__init__.py`
- Create: `src/mikroclear/suricata/events.py`
- Create: `src/mikroclear/suricata/alert_logic.py`
- Modify: old flat module paths as compatibility wrappers.
- Test: `tests/test_project_structure.py`

**Interfaces:**
- Produces: new imports under `mikroclear.routeros`, `mikroclear.telegram`, and `mikroclear.suricata`.
- Produces: old flat imports still working for `legacy.py` and existing users.

- [x] Write failing tests for new and old import paths resolving to the same functions/classes.
- [x] Move existing module contents into domain packages.
- [x] Replace old flat files with wrappers that import from the new package paths.
- [x] Run `python -m unittest tests.test_project_structure`.
- [x] Run full test suite and compile checks.
- [x] Commit.

## Task 2: Add Runtime Skeleton Modules

**Files:**
- Create: `src/mikroclear/app.py`
- Create: `src/mikroclear/settings.py`
- Create: `src/mikroclear/runtime.py`
- Create: `src/mikroclear/logging.py`
- Create: `src/mikroclear/eve_watcher.py`
- Create: `src/mikroclear/alert_processor.py`
- Create: `src/mikroclear/asset_resolver.py`
- Create: `src/mikroclear/state_store.py`
- Test: `tests/test_project_structure.py`

**Interfaces:**
- Produces: importable runtime skeleton modules with no behavior change.

- [ ] Add import tests for every runtime skeleton module.
- [ ] Add minimal module docstrings and exported names.
- [ ] Run project-structure tests.
- [ ] Commit.

## Task 3: Move Settings Loading Out Of `legacy.py`

**Files:**
- Modify: `src/mikroclear/settings.py`
- Modify: `src/mikroclear/legacy.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings.from_env()`.
- Consumes: `mikroclear.config` env helpers.

- [ ] Add tests for `MIKROCLEAR_*` precedence over `MIKROCATA_*`.
- [ ] Move runtime config constants into a dataclass.
- [ ] Keep legacy module constants assigned from `Settings.from_env()` during transition.
- [ ] Run focused and full tests.
- [ ] Commit.

## Task 4: Move Watcher And Alert Processing Out Of `legacy.py`

**Files:**
- Modify: `src/mikroclear/eve_watcher.py`
- Modify: `src/mikroclear/alert_processor.py`
- Modify: `src/mikroclear/legacy.py`
- Test: `tests/test_eve_watcher.py`
- Test: `tests/test_alert_processor.py`

**Interfaces:**
- Produces: importable watcher and alert processor units.

- [ ] Move file seek/read JSON behavior.
- [ ] Move single-alert and batch alert processing behind explicit dependencies.
- [ ] Keep legacy wrappers until production entrypoint changes.
- [ ] Run focused and full tests.
- [ ] Commit.

## Task 5: Move Asset Resolver And State Store Out Of `legacy.py`

**Files:**
- Modify: `src/mikroclear/asset_resolver.py`
- Modify: `src/mikroclear/state_store.py`
- Modify: `src/mikroclear/legacy.py`
- Test: `tests/test_asset_resolver.py`
- Test: `tests/test_state_store.py`

**Interfaces:**
- Produces: asset resolution and RouterOS list persistence modules.

- [ ] Move DHCP/PTR/cache logic.
- [ ] Move save/restore list logic.
- [ ] Run focused and full tests.
- [ ] Commit.

## Task 6: Switch CLI To `app.py`

**Files:**
- Modify: `src/mikroclear/app.py`
- Modify: `src/mikroclear/cli.py`
- Modify: `src/mikroclear/legacy.py`
- Test: `tests/test_app.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `mikroclear.app.main()`.
- Keeps: `legacy.main()` compatibility wrapper.

- [ ] Add tests proving `cli.main()` calls `app.main()`.
- [ ] Make `legacy.main()` delegate to `app.main()` or remain fallback during deployment window.
- [ ] Run full tests.
- [ ] Commit.
