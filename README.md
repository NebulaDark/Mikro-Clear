# Mikro-Clear

Local baseline and cleanup workspace for the Mikrocata TZSP0 service.

The production script currently runs on `selks` as:

```text
/usr/local/bin/mikrocataTZSP0.py
```

The copied baseline is stored at:

```text
src/mikrocata/legacy.py
```

This repository is intended to make changes testable before touching the running
service. The first extracted module is pure alert decision logic for target IP,
peer IP, port selection, and event deduplication.

## Checks

```bash
python -m unittest discover -s tests
python -m py_compile src/mikrocata/legacy.py src/mikrocata/alert_logic.py
```

## Remote Sudo Setup

MCP deploy tools require a one-time sudoers install on `selks`. The candidate
policy is stored at:

```text
deploy/sudoers.d/mikrocata-mcp-selks
```

Validate and install it on `selks` as a sudo-capable user:

```bash
sudo install -o root -g root -m 440 /tmp/mikrocata-mcp-selks.sudoers /etc/sudoers.d/mikrocata-mcp-selks
sudo visudo -cf /etc/sudoers.d/mikrocata-mcp-selks
sudo -l -U mcp-selks
```

## MCP Deploy Workflow

Registered MCP server:

```text
mikroclear-selks
```

Read-only tools:

```text
status_mikrocata
tail_mikrocata_logs
check_mikrocata_syntax
compare_production_script
verify_systemd_unit
```

Deploy flow for the production script:

```text
compare_production_script -> upload_candidate_script -> deploy_candidate_script(confirm=True)
```

Deploy flow for the systemd unit:

```text
upload_unit_candidate -> deploy_unit_candidate(confirm=True)
```

Standalone service operations:

```text
daemon_reload(confirm=True)
restart_mikrocata(confirm=True)
```

## Local Logic Fixes

- When source IP is whitelisted and the destination is selected as the block
  target, local logic now uses `dest_port`.
- Alert deduplication is now keyed by the calculated block target, not only by
  `src_ip`, so one whitelisted source can report multiple destination targets.
