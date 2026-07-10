# Telegram Polling Regression Gap

**Goal:** Capture the accepted root cause and close the test gap that let production Telegram polling drift without a failing local test.

## Accepted Finding

The production polling path is:

`python -m mikroclear` -> `mikroclear.cli.main()` -> `mikroclear.app.build_service()` -> `mikroclear.runtime.wiring.build_runtime_service()` -> `RuntimeProviders.poller` -> `MikroClearService.run_once()` -> `TelegramUpdatePoller.process_updates()`

Current tests cover pieces of that path, but they do not lock the configuration boundary that matters in production.

## Root Cause

`TelegramUpdatePoller` rebuilds bot authorization state from `BotSettings.from_env()` inside `_process_message()` and `_process_callback()` instead of consuming a prebuilt bot settings object from runtime wiring.

That means:

- production behavior depends on ambient process environment at poll time
- direct poller tests can pass while bypassing the real runtime config boundary
- runtime wiring tests can pass while only asserting object presence, not auth behavior

## Why Existing Tests Missed It

- `tests/test_runtime.py` stubs `process_telegram_updates` and never enters real poller logic
- `tests/test_app.py` asserts provider wiring but not poller auth behavior
- `tests/test_telegram_commands.py` exercises `TelegramUpdatePoller` directly with synthetic settings and relies on `telegram_chatid` fallback
- no regression test proves that polling honors injected bot allowlists when environment state differs

## Required Coverage

- Add a failing regression test that clears `os.environ`, injects explicit bot settings, and proves `/status` still works for an allowed chat through `TelegramUpdatePoller.process_updates()`
- Wire `BotSettings` once in runtime/provider construction and pass it into `TelegramUpdatePoller`
- Remove polling-time `BotSettings.from_env()` reads from message and callback handling

## Constraints

- No deploy
- No SELKS changes
- No real Telegram or RouterOS calls in tests
