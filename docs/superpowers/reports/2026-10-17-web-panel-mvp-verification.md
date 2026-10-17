# Web Panel MVP verification — 2026-10-17

Scope: stabilize existing Web Panel PR #17 before merge. The branch includes
`main` at `d0590a1` through merge `1a2de30`. No SELKS deployment, systemd action,
production credential use, or production RouterOS request was performed.

## Corrections

- Encode credentials and CSRF values before constant-time comparison, avoiding
  HTTP 500 for non-ASCII input.
- Require a bounded, locked in-memory active session; logout/re-login revoke the
  previous session, and application restart invalidates earlier cookies.
  Sessions have an absolute eight-hour lifetime; this MVP uses one worker.
- Map unavailable RouterOS inventory to a fixed, secret-free HTTP 503 response.
- Show persistent read errors in the UI, clear failed data, and recover after a
  successful retry. A request generation prevents older responses replacing newer data.
- Audit authenticated request denials, inventory failures and rejected
  confirmations without recording tokens or raw gateway errors.
- Render actual log newlines and ignore private Web env/data in Git.

Behavior regressions were observed before each corresponding implementation.
The final independent review approved both requirement compliance and code quality.

## Verification

| Check | Result |
| --- | --- |
| Full unittest discovery, web and MCP dependencies installed | 589 tests passed |
| Python compilation, tracked plus new source/tests | 150 files passed |
| Native Node resource-loading tests | 3 passed |
| npm ci / lint / build | Passed |
| docker compose config / build | Passed |
| Local container health | Healthy |
| HTTP acceptance checks | 21 passed |
| git diff --check | Passed |

Host tests used Python 3.13, with the Web extra, httpx and the declared MCP tools
dependency installed in a separate temporary virtualenv. The Docker runtime
uses Python 3.11 and serves the production Vite build. Some ASGI/Node tests
required execution outside the sandbox because its worker restrictions stalled
TestClient/Node workers; this did not require production access.

Image: `mikroclear-web:validation-20261017`.
Image ID: `sha256:d5e13cd7c3e11847ffb7b5aa6d479d00bf12addaf086052d3f7f2386f04253af`.

## Container and HTTP checks

The separate validation Compose project used generated temporary credentials,
one synthetic EVE alert, `MONITOR_ONLY=true`, disabled Mangle/integrations, and
an unavailable loopback RouterOS endpoint. Inspected configuration: UID/GID
`10001:10001`, read-only root filesystem, all capabilities dropped,
`Privileged=false`, `no-new-privileges`, read-only EVE/CA mounts, private state
volume, localhost publication on port 18080, and no Docker socket mount.

HTTP checks covered health; SPA HTML and JS/CSS assets; anonymous rejection;
Unicode invalid login; login/session/cookie attributes; dashboard with an offline
router; the mounted EVE alert and filter; disabled Mangle; controlled inventory
503; safe settings; missing CSRF; monitor-only write rejection; audit read and
denied-action audit; logout and saved-cookie revocation.

Authenticated tests use mocks for successful RouterOS inventory and action paths.
Real RouterOS connectivity, reverse-proxy HTTPS configuration and a production
pilot remain deployment checks. These results do not claim browser automation,
live infrastructure validation, or completion of later roadmap features.

## Next step

Review and merge PR #17. Its updated source is ready for a separately approved
pilot deployment. Live alerts/Log Gateway, whitelist/parental Web UI, settings
engine and RBAC remain subsequent stages.
