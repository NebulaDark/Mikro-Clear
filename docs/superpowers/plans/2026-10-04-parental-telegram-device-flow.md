# Parental Telegram Device Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rework the Parental Control Telegram presentation into a device-first flow with television icons and action buttons shown only after device selection.

**Architecture:** Keep `TelegramParentalHandler` as the callback boundary and keep Pi-hole policy operations unchanged. Add pure presentation builders for the device list and selected-device view; selection uses the current inventory index, while BLOCK/ALLOW still use the existing server-side confirmation token.

**Tech Stack:** Python, unittest, existing `MenuView` and Telegram callback protocol.

**Completion update (2026-10-17):** Presentation builders, television labels and
device-selection callbacks are implemented and deployed. Current verification:
553 tests passed, tracked Python sources compiled and `git diff --check` passed.
The additional Pi-hole ALLOW defect was fixed separately in the same deployment;
the user confirmed unblocking after installation. See the
[deployment report](../deploy/2026-10-17-parental-allow-fix.md).
The original steps below are retained as the implementation sequence, not a new
list of outstanding tasks.

## Global Constraints

- Do not change RouterOS, Pi-hole transport, runtime wiring, feature flags, or production environment.
- Preserve `parental:v1` callback protocol and existing TTL, ownership, one-shot, confirmation, and delivery retry behavior.
- Do not add production network calls or call the Telegram API in tests.
- Do not stage `plan.md` or `services/docker-mcp/`.

---

### Task 1: Presentation builders and root icon

**Files:**
- Modify: `src/mikroclear/bot/menu.py`
- Modify: `src/mikroclear/bot/modules/parental.py`
- Test: `tests/test_bot_menu.py`
- Test: `tests/test_telegram_parental.py`

**Interfaces:**
- `build_parental_view(states)` returns the device list view.
- `build_parental_device_view(state, index)` returns the selected device view.
- Device list buttons use `parental:v1:device:<index>`.
- Selected-device action buttons retain `parental:v1:youtube:request:<index>:block|allow`.

- [ ] **Step 1: Write failing assertions** for the television root label, device-list-only buttons, and selected-device action buttons.
- [ ] **Step 2: Run focused tests** with `PYTHONPATH=src .venv/bin/python -m unittest tests.test_bot_menu tests.test_telegram_parental` and confirm the new assertions fail.
- [ ] **Step 3: Change the parental root label** from the family emoji to `📺 Родительский контроль`.
- [ ] **Step 4: Split parental presentation** so the list uses `📺` device rows and the selected-device view contains state plus BLOCK/ALLOW actions.
- [ ] **Step 5: Run the focused tests** and confirm they pass.

### Task 2: Device selection callback

**Files:**
- Modify: `src/mikroclear/telegram/parental_handler.py`
- Test: `tests/test_telegram_parental.py`

**Interfaces:**
- `parental:v1:device:<index>` reads the current managed inventory and state, then renders `build_parental_device_view`.
- Invalid or unavailable indexes return a controlled callback response and do not mutate policy.

- [ ] **Step 1: Add a failing handler test** that selects device index `0`, asserts the selected device view is rendered, and asserts policy mutation methods are not called.
- [ ] **Step 2: Run that test** and confirm it fails because the callback is not handled.
- [ ] **Step 3: Implement the `device` callback branch** with current inventory lookup, state lookup, controlled error handling, and existing `_render` delivery semantics.
- [ ] **Step 4: Run the focused parental tests** and confirm all pass.

### Task 3: Regression verification

**Files:**
- No additional production files.

- [ ] **Step 1: Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_bot_menu tests.test_telegram_parental`.**
- [ ] **Step 2: Run the full test suite with `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`.**
- [ ] **Step 3: Run `git diff --check`.**
- [ ] **Step 4: Run Python compilation for tracked Python files.**
- [ ] **Step 5: Review the diff for unchanged token ownership, confirmation, policy, and transport behavior.**
