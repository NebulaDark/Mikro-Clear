# Mikro-Clear Architecture

Current state as of 2026-07-06.

Mikro-Clear runtime code is owned by canonical package modules under
`src/mikroclear/`. Old top-level modules remain only as compatibility shims for
older imports and tests. New production code should import canonical modules.

## Entry Points

`src/mikroclear/__main__.py`
: Package entrypoint for `python -m mikroclear`.

`src/mikroclear/cli.py`
: Console-script parser. It delegates service startup to `mikroclear.app.main`.

`src/mikroclear/app.py`
: Thin application boundary. It loads settings, builds the service, and returns
or runs `MikroClearService`. It does not own runtime providers or business
logic.

`src/mikroclear/legacy.py`
: Compatibility wrapper for old script-style callers. It delegates to
`mikroclear.app.main`.

## Configuration Layer

`src/mikroclear/settings.py`
: Runtime settings object definitions.

`src/mikroclear/config.py`
: Environment adapter. `MIKROCLEAR_*` names are primary. `MIKROCATA_*` names are
accepted only as legacy fallback inside this layer.

Feature modules should receive settings or explicit dependencies from runtime
wiring instead of reading environment variables directly.

## Runtime Composition

`src/mikroclear/runtime/__init__.py`
: Owns `MikroClearService`, `RuntimeConfig`, and `RuntimeDependencies`. This is
the service loop boundary: signal handling, pyinotify registration, startup,
poll loop, shutdown, and notification lifecycle.

`src/mikroclear/runtime/wiring.py`
: Converts `Settings` into runtime config and dependencies. It imports optional
production dependencies only when building the service.

`src/mikroclear/runtime/providers.py`
: Builds concrete providers used by the service: RouterOS client, Telegram
notifier/poller, Suricata alert pipeline, state stores, asset resolver, and
debug logging hooks.

`src/mikroclear/runtime/status_snapshot.py`
: Builds read-only status snapshots for Telegram bot status reporting.

## RouterOS Block

`src/mikroclear/routeros/client.py`
: RouterOS API lifecycle owner: connect, reconnect, retry loop, heartbeat, and
error handling. It does not own address-list business operations.

`src/mikroclear/routeros/address_list.py`
: Address-list helpers and write-action boundary: select, add, update, remove,
restore, and list-specific helper operations.

`src/mikroclear/routeros/ssl_context.py`
: API-SSL context construction and TLS verification options.

`src/mikroclear/routeros/tls.py`
: Compatibility import path for TLS helpers inside the RouterOS package.

All RouterOS writes should flow through the RouterOS adapter/address-list helper
layer. Imports must not establish a real RouterOS connection.

## Suricata Block

`src/mikroclear/suricata/alert_logic.py`
: Pure alert decision logic: target IP selection, peer IP, port selection, and
deduplication key calculation.

`src/mikroclear/suricata/events.py`
: Event parsing and validation helpers for EVE JSON payloads.

`src/mikroclear/suricata/eve_tailer.py`
: EVE file reading/tailing and file rotation handling.

`src/mikroclear/suricata/event_handler.py`
: pyinotify event adapter that asks the pipeline to process new EVE content.

`src/mikroclear/suricata/ignore_rules.py`
: Ignore-list file loading and matching decisions.

`src/mikroclear/suricata/pipeline.py`
: Alert batch orchestration, calculated-target deduplication, ignore decisions,
and `process_single_alert`.

## Telegram Block

`src/mikroclear/telegram/formatting.py`
: HTML escaping/sanitizing plus alert and system message formatting.

`src/mikroclear/telegram/notify.py`
: Telegram `sendMessage` transport, alert/system notification sending,
reply-markup use, and API rate-limit response handling.

`src/mikroclear/telegram/polling.py`
: `getUpdates` polling, update offset handling, callback query dispatch,
network/HTTP error handling, and backoff.

`src/mikroclear/telegram/rate_limit.py`
: Local rate-limit lock file helpers.

`src/mikroclear/telegram/unblock.py`
: Unblock token state and inline keyboard construction.

`src/mikroclear/telegram/unblock_handler.py`
: Callback handler that validates unblock tokens, removes RouterOS
address-list entries through the adapter, and answers callback queries.

`src/mikroclear/telegram/commands.py`
: Telegram command dispatch integration for the control-plane bot.

Tests must mock Telegram HTTP calls. Imports must not call Telegram APIs.

## Bot Block

`src/mikroclear/bot/settings.py`
: Telegram control-plane settings.

`src/mikroclear/bot/auth.py`
: Allowed/admin chat authorization checks.

`src/mikroclear/bot/dispatcher.py`
: Command routing for Telegram bot messages.

`src/mikroclear/bot/modules/status.py`
: Read-only `/status` command formatting.

Write-capable bot modules must stay behind narrow adapters and must not expose
arbitrary RouterOS paths.

## State Block

`src/mikroclear/state/files.py`
: Private file and directory creation helpers, including permission handling.

`src/mikroclear/state/address_list_store.py`
: Save/restore of RouterOS address-list state.

`src/mikroclear/state/uptime.py`
: Suricata uptime bookmark persistence.

## Asset Resolver Block

`src/mikroclear/assets/resolver.py`
: DHCP and PTR asset-name resolution. Resolver cache is owned by the runtime
provider instance, not by an unmanaged global.

## Compatibility Shims

These files are intentionally kept for old imports only:

- `src/mikroclear/asset_resolver.py`
- `src/mikroclear/state_store.py`
- `src/mikroclear/eve_watcher.py`
- `src/mikroclear/telegram_notify.py`
- `src/mikroclear/telegram_polling.py`
- `src/mikroclear/telegram_unblock.py`
- `src/mikroclear/routeros_client.py`
- `src/mikroclear/routeros_tls.py`
- `src/mikroclear/alert_logic.py`
- `src/mikroclear/events.py`
- `src/mikrocata/*`

New code should not treat these paths as canonical. They should re-export or
delegate to the canonical package modules without owning business logic.

`src/mikroclear/legacy_runtime.py` has been retired and removed. Runtime code
must not import it.

## Safety Boundaries

- No deploy is performed by local refactor commits.
- SELKS and `systemctl` are not touched by package/module cleanup.
- RouterOS connects and writes happen only at runtime through adapters, never at
import time.
- Telegram HTTP calls happen only at runtime through notifier/poller providers,
never at import time.
- Tests mock RouterOS and Telegram network operations.
- No secrets belong in source, tests, docs, or git history.

## Verification

Use this local verification set after module ownership changes:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
git ls-files '*.py' | xargs .venv/bin/python -m py_compile
PYTHONPATH=src .venv/bin/python -c "import mikroclear.app as app; svc = app.build_service(); print(type(svc).__name__)"
grep -R "from mikroclear import legacy_runtime" src tests || true
grep -R "import mikroclear.legacy_runtime" src tests || true
```

The expected service type from `app.build_service()` is `MikroClearService`.
