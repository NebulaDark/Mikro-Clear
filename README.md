# Mikro-Clear

Local baseline and cleanup workspace for the Mikro-Clear service.

Production on `selks` currently runs from the package entrypoint:

```text
/opt/mikroclear-venv/bin/python -m mikroclear
```

The legacy script compatibility wrapper is stored at:

```text
src/mikroclear/legacy.py
```

This repository is intended to make changes testable before touching the running
service. Runtime implementation lives in canonical package modules under
`src/mikroclear/`.

## Architecture

The current canonical module ownership map is documented in:

```text
docs/architecture.md
```

New production code should import canonical package modules under
`src/mikroclear/`. Old top-level modules are compatibility shims for legacy
imports.

Russian deployment and operator documentation:

```text
docs/ru/install-from-github.md
docs/ru/env-reference.md
docs/ru/architecture.md
docs/ru/deploy-2026-07-06.md
```

## Checks

```bash
PYTHONPATH=src python -m unittest discover -s tests
git ls-files '*.py' | xargs python -m py_compile
```

## Operations

The SELKS operations runbook is stored at:

```text
docs/runbook.md
```

Security recurring checks are stored at:

```text
docs/security-runbook.md
```

Use the Telegram token rotation procedure in the runbook after any suspected
Bot API token exposure. Do not paste live tokens into chat, logs, commits, or
issue trackers. Mask Telegram Bot API URLs before sharing service output:

```bash
sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g'
```

## Configuration Paths

Primary Mikro-Clear configuration on SELKS:

```text
/etc/mikroclear/mikroclear.env
/var/lib/mikroclear
```

The service temporarily also reads the legacy file:

```text
/etc/mikrocata/mikrocataTZSP0.env
```

Keep the legacy file only as a fallback during migration. The active
`/etc/mikroclear/mikroclear.env` file should use `MIKROCLEAR_*` names and set:

```text
MIKROCLEAR_STATE_DIR=/var/lib/mikroclear
```

RouterOS API-SSL should verify endpoint identity. The RouterOS certificate used
by the current SELKS deployment contains `IP Address:192.168.10.1` and
`DNS:r1.21port.ru`, so the default TLS server name can stay:

```text
MIKROCLEAR_ROUTER_TLS_SERVER_NAME=192.168.10.1
```

## Remote Sudo Setup

MCP deploy tools require a one-time sudoers install on `selks`. The candidate
policy is stored at:

```text
deploy/sudoers.d/mikroclear-mcp-selks
```

Validate and install it on `selks` as a sudo-capable user:

```bash
sudo install -o root -g root -m 755 /tmp/mikroclear-mask-env /usr/local/sbin/mikroclear-mask-env
sudo install -o root -g root -m 440 /tmp/mikroclear-mcp-selks.sudoers /etc/sudoers.d/mikroclear-mcp-selks
sudo visudo -cf /etc/sudoers.d/mikroclear-mcp-selks
sudo -l -U mcp-selks
```

The helper source is stored at:

```text
deploy/bin/mikroclear-mask-env
```

## MCP Deploy Workflow

Registered MCP server:

```text
mikroclear-selks
```

Read-only tools:

```text
status_mikroclear
tail_mikroclear_logs
check_mikroclear_import
verify_systemd_unit
```

Legacy `*_mikrocata` MCP tool names remain as compatibility aliases.

Target package deploy flow after merge to `main`:

```text
build wheel from main -> upload_wheel_candidate -> deploy_wheel_candidate(confirm=True)
```

Legacy single-file script deploy is an emergency rollback path only:

```text
compare_production_script -> upload_candidate_script -> deploy_candidate_script(confirm=True)
```

Systemd unit deploy remains a separate approved operation:

```text
upload_unit_candidate -> deploy_unit_candidate(confirm=True)
```

The unit deploy updates `mikroclear.service`; legacy service names are not
production deploy targets.

Standalone service operations:

```text
daemon_reload(confirm=True)
restart_mikroclear(confirm=True)
```

## Local Logic Fixes

- When source IP is whitelisted and the destination is selected as the block
  target, local logic now uses `dest_port`.
- Alert deduplication is now keyed by the calculated block target, not only by
  `src_ip`, so one whitelisted source can report multiple destination targets.

## Telegram Unblock

When Telegram notifications are enabled, `BLOCKED` and `UPDATED` alert messages
include an inline `Unblock <ip>` button. The button consumes a short-lived token
from the local state file and removes the current IP from the MikroTik
address-list. It does not add a permanent whitelist or ignore rule.

Relevant settings:

```text
MIKROCLEAR_TELEGRAM_UNBLOCK_ENABLE=true
MIKROCLEAR_TELEGRAM_UNBLOCK_TTL_SECONDS=86400
MIKROCLEAR_TELEGRAM_UPDATES_INTERVAL_SECONDS=5
```
