# Legacy Cleanup Plan

Date: 2026-07-05

## Current State

`mikroclear.service` now runs through the package entrypoint:

```text
ExecStart=/opt/mikroclear-venv/bin/python -m mikroclear
```

The repository keeps `src/mikroclear/legacy.py` as a thin compatibility wrapper
for existing imports. The former runtime monolith has been retired; package
runtime composition is now built from `app.py`, `runtime.py`, and focused
RouterOS, Suricata, Telegram, state, and asset modules.

This is intentionally not a behavior change. The wrapper exposes only
`main()` and delegates to `mikroclear.app.main()`.

## Completed Slice

- Keep `mikroclear.legacy.main()` as a compatibility wrapper around
  `mikroclear.app.main()`.
- Move the large legacy implementation out of `legacy.py`.
- Stop exporting private runtime symbols through `mikroclear.legacy`.
- Make `mikroclear.app.build_service()` depend on modular package providers.
- Add unit tests for the wrapper boundary and cleanup plan presence.
- Extract configuration loading into `mikroclear.settings` and `config.py`.
- Extract RouterOS connect/reconnect/heartbeat and address-list actions into
  `mikroclear.routeros`.
- Extract Telegram polling, notification, formatting, rate-limit, command, and
  unblock boundaries into `mikroclear.telegram` and `mikroclear.bot`.
- Extract Suricata tailing, ignore rules, event handling, and alert pipeline
  into `mikroclear.suricata`.
- Move state-file, save/restore, uptime, and private permission helpers under
  `mikroclear.state`.
- Wire asset resolver through runtime-owned dependencies.

## Remaining Work

- Deploy is intentionally out of scope for this branch.
- After review, run a SELKS read-only preflight before any service restart.

## Compatibility Boundaries

- Legacy `/etc/mikrocata` and `/var/lib/mikrocata` paths may remain as
  environment/state compatibility fallbacks.
- The old `mikrocata` virtualenv path must not be used by tracked deployment
  docs or systemd candidates.
- `mikrocataTZSP0.service` must not be referenced as the active production
  service.
- No new Telegram write-actions are part of this cleanup.

## Risks

- Future extraction must preserve production behavior around Telegram polling,
  RouterOS reconnects, ignore-list reloads, and systemd runtime paths.
- The branch has not been deployed or exercised against SELKS production.

## Next Safe Step

Review the modular runtime diff, then run local package artifact validation and
SELKS read-only checks before considering a deployment window.
