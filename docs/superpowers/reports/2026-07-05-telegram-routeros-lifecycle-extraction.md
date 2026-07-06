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

The package runtime now keeps the polling loop in `mikroclear.telegram.polling`
and delegates callback processing to this boundary.

## RouterOS Lifecycle Boundary

`mikroclear.routeros.client.RouterOsApiLifecycle` now owns testable API session
state helpers:

- current API object storage;
- connected timestamp;
- close handling;
- ensure-connected helper;
- RouterOS path construction;
- lifecycle-level reconnect helper for future adapters.

`mikroclear.routeros.client.RouterOSClient` now owns the production credential
checks, retry loop, connection logging, and notification behavior behind
runtime-injected settings and callbacks.

## Deferred

- Keep RouterOS write actions covered by adapter tests before any future behavior
  change.
- Keep Telegram polling HTTP getUpdates covered by mocked request tests.
- Keep new control-plane write-actions out of scope until dry-run, allowlist, and
  audit logging are implemented.
