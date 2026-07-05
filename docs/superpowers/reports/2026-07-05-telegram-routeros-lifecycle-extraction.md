# Telegram and RouterOS Lifecycle Extraction Report

Date: 2026-07-05

## Scope

This stage extracts the next runtime boundaries without adding Telegram
write-actions, deploying to SELKS, restarting systemd, or changing RouterOS
production state.

## Telegram Callback Boundary

`mikroclear.telegram.commands.process_callback_update()` now owns callback-query
control flow for Telegram unblock actions:

- unauthorized chat rejection;
- unblock callback token parsing;
- expired or consumed token handling;
- calling the injected unblock action handler;
- sending the success system notification only after successful unblock.

`legacy_runtime.py` keeps the polling loop and delegates callback processing to
this boundary.

## RouterOS Lifecycle Boundary

`mikroclear.routeros.client.RouterOsApiLifecycle` now owns testable API session
state helpers:

- current API object storage;
- connected timestamp;
- close handling;
- ensure-connected helper;
- RouterOS path construction;
- lifecycle-level reconnect helper for future adapters.

`legacy_runtime.RouterOSClient` still owns the production credential checks,
retry loop, connection logging, and notification behavior. This is intentional:
it avoids changing outage/retry semantics during a structural refactor.

## Deferred

- Move the full `RouterOSClient.connect()` retry loop into an injected adapter
  after dedicated tests cover every exception branch.
- Move Telegram polling HTTP getUpdates handling after callback and message
  boundaries remain stable.
- Keep new control-plane write-actions out of scope until dry-run, allowlist, and
  audit logging are implemented.
