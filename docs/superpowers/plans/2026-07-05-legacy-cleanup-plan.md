# Legacy Cleanup Plan

Date: 2026-07-05

## Current State

`mikroclear.service` now runs through the package entrypoint:

```text
ExecStart=/opt/mikroclear-venv/bin/python -m mikroclear
```

The repository keeps `src/mikroclear/legacy.py` as a thin compatibility wrapper
for existing imports and tests. The former monolithic implementation has moved
to `src/mikroclear/legacy_runtime.py`.

This is intentionally not a behavior change. The wrapper preserves existing
runtime symbols while new orchestration code imports `legacy_runtime.py`
directly.

## Completed Slice

- Keep `mikroclear.legacy.main()` as a compatibility wrapper around
  `mikroclear.app.main()`.
- Move the large legacy implementation out of `legacy.py`.
- Keep private and public legacy symbols available for compatibility.
- Make `mikroclear.app.build_service()` depend on `legacy_runtime.py`, not on
  the compatibility wrapper.
- Add unit tests for the wrapper boundary and cleanup plan presence.

## Remaining Work

1. Extract configuration loading from `legacy_runtime.py` into
   `mikroclear.settings` and runtime-specific config adapters.
2. Extract RouterOS write/read helpers into `mikroclear.routeros` modules and
   keep write-safety checks near the API boundary.
3. Extract Telegram polling and command handling into `mikroclear.telegram` and
   `mikroclear.bot` modules.
4. Extract Suricata alert processing into `mikroclear.suricata` modules.
5. Move state-file and ignore-list handling into dedicated state modules.
6. Reduce `legacy_runtime.py` to a composition layer, then retire compatibility
   exports only after production has run stably through the package entrypoint.

## Compatibility Boundaries

- Legacy `/etc/mikrocata` and `/var/lib/mikrocata` paths may remain as
  environment/state compatibility fallbacks.
- The old `mikrocata` virtualenv path must not be used by tracked deployment
  docs or systemd candidates.
- `mikrocataTZSP0.service` must not be referenced as the active production
  service.
- No new Telegram write-actions are part of this cleanup.

## Risks

- `legacy_runtime.py` still contains broad module-level initialization.
- Tests that patch `mikroclear.legacy` rely on the compatibility facade
  exporting private names.
- Future extraction must preserve production behavior around Telegram polling,
  RouterOS reconnects, ignore-list reloads, and systemd runtime paths.

## Next Safe Step

Start with read-only extraction targets: settings adapters, alert parsing, and
message formatting. Defer RouterOS write-path refactors until write safety tests
cover allowlists, dry-run behavior, and audit logging.
