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

   Follow `docs/ru/systemd-env-fallback-policy.md`.

3. Remove legacy state paths from systemd sandbox.

   Only after `/var/lib/mikroclear` has all required state files and rollback no
   longer needs `/var/lib/mikrocata`.

4. Deprecate top-level shims.

   Add deprecation notes or warnings only if they will not affect production
   logs. Prefer docs/tests first.

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
- production deploys from wheel/package entrypoint;
- env primary path has migrated to `/etc/mikroclear/mikroclear.env`;
- legacy env/state paths remain rollback compatibility boundaries.
