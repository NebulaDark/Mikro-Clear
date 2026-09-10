# Legacy compatibility cleanup plan

This plan closes the current cleanup stage and defines the remaining legacy
compatibility work. It is intentionally separated from the production deploy
steps: compatibility removal should be done in small PRs after stable
observation windows.

## Current canonical runtime

Canonical runtime modules live under:

```text
src/mikroclear/
```

Production entrypoint:

```text
python -m mikroclear
```

Retired:

```text
src/mikroclear/legacy_runtime.py
```

## Compatibility paths intentionally retained

Top-level shims:

```text
src/mikroclear/asset_resolver.py
src/mikroclear/state_store.py
src/mikroclear/eve_watcher.py
src/mikroclear/telegram_notify.py
src/mikroclear/telegram_polling.py
src/mikroclear/telegram_unblock.py
src/mikroclear/routeros_client.py
src/mikroclear/routeros_tls.py
src/mikroclear/alert_logic.py
src/mikroclear/events.py
```

Legacy package aliases:

```text
src/mikrocata/*
```

These paths must stay import-only wrappers until downstream users, docs, and
rollback procedures no longer depend on them.

## Cleanup stages

1. Audit imports.

   Required check:

   ```bash
   rg -n "from mikroclear import (asset_resolver|state_store|eve_watcher|telegram_notify|telegram_polling|telegram_unblock|routeros_client|routeros_tls|alert_logic|events)|import mikroclear\\.(asset_resolver|state_store|eve_watcher|telegram_notify|telegram_polling|telegram_unblock|routeros_client|routeros_tls|alert_logic|events)" src tests docs README.md
   ```

   Production code should use canonical package modules. Compatibility imports
   should remain only in tests that explicitly validate shims or docs that
   explain rollback.

2. Remove legacy env fallback from systemd.

   Completed in the tracked units. The canonical env file is mandatory.
   Follow `docs/ru/systemd-env-fallback-policy.md` for older installations.

3. Remove legacy state paths from systemd sandbox.

   Completed in the tracked units. On an older server, first verify that
   `/var/lib/mikroclear` has all required state files and a usable backup.

4. Deprecate top-level shims.

   Current status: top-level shims are marked as deprecated compatibility
   shims in module docstrings. Runtime warnings are intentionally not emitted,
   so production logs stay quiet. Details:

   ```text
   docs/ru/compatibility-shim-deprecation.md
   ```

5. Remove top-level shims and `src/mikrocata/*`.

   This should be a later major cleanup PR. Acceptance criteria:

   - full tests pass;
   - package entrypoint imports safely;
   - docs no longer present old imports as supported API;
   - rollback plan does not require legacy Python import paths;
   - SELKS production has run through a stable observation window.

## Current stop point

Do not remove compatibility shims yet. The current safe stop point is:

- runtime ownership is canonical;
- the supported deployment uses the wheel/package entrypoint;
- tracked units require `/etc/mikroclear/mikroclear.env` and run as `mikroclear`;
- tracked units contain no legacy env/state paths;
- the current production configuration requires a separate live check;
- compatibility imports remain available until the removal gates are met.
