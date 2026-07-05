# Mikro-Clear

Local baseline and cleanup workspace for the Mikro-Clear service.

The production script currently runs on `selks` as:

```text
/usr/local/bin/mikroclear.py
```

The copied baseline is stored at:

```text
src/mikroclear/legacy.py
```

This repository is intended to make changes testable before touching the running
service. The first extracted module is pure alert decision logic for target IP,
peer IP, port selection, and event deduplication.

## Checks

```bash
python -m unittest discover -s tests
python -m py_compile src/mikroclear/legacy.py src/mikroclear/alert_logic.py
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
check_mikroclear_syntax
compare_production_script
verify_systemd_unit
```

Legacy `*_mikrocata` MCP tool names remain as compatibility aliases.

Deploy flow for the production script:

```text
compare_production_script -> upload_candidate_script -> deploy_candidate_script(confirm=True)
```

Deploy flow for the systemd unit:

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
