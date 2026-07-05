# Runtime Boundary Extraction Report

Date: 2026-07-05

## Production Observation

Read-only SELKS checks were performed against `mikroclear.service`.

Observed state:

- `ActiveState=active`
- `SubState=running`
- `Result=success`
- `NRestarts=0`
- `ExecStart=/opt/mikroclear-venv/bin/python -m mikroclear`
- `ExecMainStartTimestamp=Sun 2026-07-05 17:50:52 MSK`

No deploy, restart, daemon-reload, RouterOS write action, or SELKS file change was
performed during this check.

## Extraction Slice

This slice kept runtime behavior unchanged and moved small, testable boundaries
out of the former runtime monolith:

- `mikroclear.settings.load_settings()` is now the runtime settings loader
  boundary.
- `mikroclear.telegram.commands.process_message_command()` owns Telegram message
  command dispatch side effects.
- `mikroclear.routeros.client.build_routeros_connect_kwargs()` owns RouterOS API
  connection argument construction.

## Superseded Deferred Items

- Runtime composition and callback polling have since moved into modular package
  providers.
- RouterOS write actions are not changed.
- New Telegram control-plane write actions remain out of scope.
- RouterOS client connection lifecycle is now dependency-injected through
  `mikroclear.routeros.client.RouterOSClient`.
