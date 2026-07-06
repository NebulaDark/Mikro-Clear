# Telegram Mangle Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe Telegram control for pre-existing MikroTik mangle rules by toggling only `disabled=yes/no`.

**Architecture:** RouterOS validation and writes live in `routeros/mangle.py`. Telegram display and keyboards live in `bot/mangle_control.py`. Command/callback orchestration and short-lived tokens live in `telegram/mangle_handler.py`, wired into the existing Telegram polling loop.

**Tech Stack:** Python stdlib `unittest`, librouteros-style resource objects, existing Telegram `send_telegram_message` injection.

## Global Constraints

- No deploy, no push before final report.
- Do not touch SELKS or run systemctl.
- Do not call real RouterOS or Telegram APIs in tests.
- Do not create/delete RouterOS mangle rules.
- Only update `disabled` on managed `/ip/firewall/mangle` rules.

---

### Task 1: RouterOS mangle adapter

**Files:**
- Create: `src/mikroclear/routeros/mangle.py`
- Create: `tests/test_routeros_mangle.py`
- Modify: `src/mikroclear/settings.py`

**Interfaces:**
- `MangleRule`
- `list_managed_mangle_rules(api, settings) -> list[MangleRule]`
- `get_managed_mangle_rule(api, rule_id, settings) -> MangleRule | None`
- `set_mangle_rule_disabled(api, rule_id, disabled, settings) -> None`

Steps:
- [ ] Add failing tests for list filtering and write safety.
- [ ] Add settings defaults/env loading tests.
- [ ] Implement minimal adapter and settings.
- [ ] Run focused tests and commit.

### Task 2: Telegram mangle workflow

**Files:**
- Create: `src/mikroclear/bot/mangle_control.py`
- Create: `src/mikroclear/telegram/mangle_handler.py`
- Modify: `src/mikroclear/telegram/polling.py`
- Modify: `src/mikroclear/runtime/providers.py`
- Create: `tests/test_telegram_mangle_control.py`

**Interfaces:**
- `format_mangle_status(rules) -> str`
- `build_mangle_keyboard(rules) -> dict`
- `build_mangle_confirm_keyboard(token) -> dict`
- `TelegramMangleHandler.handle_message(...) -> bool`
- `TelegramMangleHandler.handle_callback(...) -> bool`

Steps:
- [ ] Add failing tests for formatting and keyboard.
- [ ] Add failing tests for `/mangle`, request, confirm, cancel, refresh, auth.
- [ ] Implement handler and wire into existing polling loop.
- [ ] Run focused tests and commit.

### Task 3: Full verification

**Files:**
- Modify tests and project structure imports as needed.

Steps:
- [ ] Run full unittest.
- [ ] Run py_compile.
- [ ] Run build_service import check.
- [ ] Run high-signal secret scan.
- [ ] Run git status.
- [ ] Commit final test updates if needed.
