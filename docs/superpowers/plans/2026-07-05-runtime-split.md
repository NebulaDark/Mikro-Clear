# Mikro-Clear Runtime Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move production runtime orchestration out of `legacy.py` into `app.py` and `runtime.py` without changing Telegram status bot behavior or adding new write actions.

**Architecture:** `runtime.py` owns `MikroClearService`, signal handling, startup sequence, main loop, Telegram polling lifecycle, and shutdown cleanup. `app.py` composes a service from the existing legacy dependency surface. `legacy.py` keeps compatibility imports and helper functions but its `main()` becomes a thin wrapper to `app.main()`.

**Tech Stack:** Python 3.11+, unittest, existing `pyinotify`, existing RouterOS and Telegram helper functions.

## Global Constraints

- Do not deploy to SELKS.
- Do not push.
- Do not add Telegram write actions.
- Do not change existing `/status` behavior.
- Keep all tests green.
- Use small commits.

---

## Task 1: Add Runtime Service Skeleton

**Files:**
- Modify: `src/mikroclear/runtime.py`
- Test: `tests/test_runtime.py`

**Interfaces:**
- Produces: `RuntimeConfig`
- Produces: `RuntimeDependencies`
- Produces: `MikroClearService`
- Produces: `MikroClearService.install_signal_handlers() -> None`
- Produces: `MikroClearService.startup() -> None`
- Produces: `MikroClearService.run_once() -> None`
- Produces: `MikroClearService.run() -> int`
- Produces: `MikroClearService.shutdown() -> None`

## Task 2: Wire App Entrypoint To Runtime Service

**Files:**
- Modify: `src/mikroclear/app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `MikroClearService`
- Produces: `build_service() -> MikroClearService`
- Produces: `main() -> int`

## Task 3: Convert Legacy Main To Compatibility Wrapper

**Files:**
- Modify: `src/mikroclear/legacy.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `mikroclear.app.main`
- Produces: `legacy.main() -> int`

## Task 4: Full Verification

**Files:**
- Read all changed files.

**Verification Commands:**

```bash
PYTHONPATH=src /home/mgm/Projects/Mikro-Clear/.venv/bin/python -m unittest discover -s tests
git ls-files '*.py' | xargs /home/mgm/Projects/Mikro-Clear/.venv/bin/python -m py_compile
git grep -n -I -E '(BEGIN (RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|[0-9]{6,}:[A-Za-z0-9_-]{30,})' -- .
git status --short
git diff --stat main
```

Expected: tests pass, compile exits 0, secret scan exits 1 with no output, status clean after commits.
