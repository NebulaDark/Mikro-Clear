# SELKS Read-Only Preflight Before Package Entrypoint Switch

Date: 2026-07-05

Scope: read-only SELKS preflight before a future systemd package-entrypoint
switch. No push, no deploy, no restart, no `systemctl` mutation, no SELKS file
changes, and no RouterOS write action were performed.

## SSH Target

Requested host alias:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks-mcp ...
```

Result:

```text
ssh: Could not resolve hostname selks-mcp: Name or service not known
```

Available SSH config contains only:

```text
Host selks
  User mcp-selks
  HostName 192.168.10.15
```

The preflight was therefore executed through the configured MCP SSH user via
host alias `selks`.

## 1. Current Legacy Systemd Unit

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'systemctl cat mikrocataTZSP0.service'
```

Result:

```text
# /etc/systemd/system/mikrocataTZSP0.service
[Unit]
Description=Mikrocata TZSP0 - Suricata to MikroTik AutoBlock
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
EnvironmentFile=/etc/mikrocata/mikrocataTZSP0.env
ExecStart=/opt/mikrocata-venv/bin/python /usr/local/bin/mikrocataTZSP0.py
Restart=on-failure
RestartSec=30
User=root
Group=root
WorkingDirectory=/usr/local/bin
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'systemctl status mikrocataTZSP0.service --no-pager'
```

Result:

```text
Loaded: loaded (/etc/systemd/system/mikrocataTZSP0.service; disabled; preset: enabled)
Active: inactive (dead)
```

The command exited with code `3`, which is expected for an inactive unit.

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'systemctl show mikrocataTZSP0.service --property=ExecStart,EnvironmentFiles,FragmentPath,DropInPaths'
```

Result:

```text
ExecStart={ path=/opt/mikrocata-venv/bin/python ; argv[]=/opt/mikrocata-venv/bin/python /usr/local/bin/mikrocataTZSP0.py ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }
EnvironmentFiles=/etc/mikrocata/mikrocataTZSP0.env (ignore_errors=no)
FragmentPath=/etc/systemd/system/mikrocataTZSP0.service
DropInPaths=
```

Findings:

- Legacy unit exists.
- Legacy unit is disabled and inactive.
- Legacy unit still launches `/usr/local/bin/mikrocataTZSP0.py`.
- Legacy unit uses only `/etc/mikrocata/mikrocataTZSP0.env`.

## 2. Python And Venv

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikrocata-venv/bin/python --version'
```

Result:

```text
Python 3.11.2
```

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikrocata-venv/bin/python -c "import sys; print(sys.path)"'
```

Result:

```text
['', '/usr/lib/python311.zip', '/usr/lib/python3.11', '/usr/lib/python3.11/lib-dynload', '/opt/mikrocata-venv/lib/python3.11/site-packages']
```

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikrocata-venv/bin/python -c "import librouteros, requests, ujson; print(\"deps ok\")"'
```

Result:

```text
deps ok
```

Findings:

- SELKS venv is Python 3.11.2.
- Core runtime dependencies `librouteros`, `requests`, and `ujson` are present.
- The venv search path does not include the repository package by default.

## 3. Legacy Files And Env Presence

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'ls -l /usr/local/bin/mikrocataTZSP0.py'
```

Result:

```text
-rwxr-xr-x 1 root root 52955 Jul  2 17:32 /usr/local/bin/mikrocataTZSP0.py
```

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'ls -l /etc/mikrocata/'
```

Result:

```text
drwx------ 2 root root 4096 Jun  9 13:51 certs
drwxr-xr-x 2 root root 4096 Jun 11 20:01 geoip
-rw------- 1 root root 3660 Jul  3 13:46 mikrocataTZSP0.env
```

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'ls -l /etc/mikrocata/mikrocataTZSP0.env'
```

Result:

```text
-rw------- 1 root root 3660 Jul  3 13:46 /etc/mikrocata/mikrocataTZSP0.env
```

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'ls -l /var/lib/mikrocata/'
```

Result:

```text
ls: cannot open directory '/var/lib/mikrocata/': Permission denied
```

Additional read-only metadata command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'ls -ld /var/lib/mikrocata/'
```

Result:

```text
drwx------ 2 root root 4096 Jul  5 15:51 /var/lib/mikrocata/
```

Findings:

- Legacy script exists and is executable.
- Legacy env exists with mode `0600`.
- Legacy state directory exists with mode `0700`.
- The MCP SSH user cannot list state file contents because the directory is root-only.

## 4. Logs Read-Only

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'journalctl -u mikrocataTZSP0.service -n 80 --no-pager'
```

Result:

```text
Hint: You are currently not seeing messages from other users and the system.
      Users in groups 'adm', 'systemd-journal' can see all messages.
-- No entries --
```

Finding:

- Journal access for the MCP SSH user is limited.
- No entries for the inactive legacy unit were visible without elevated journal permissions.

## 5. Candidate Import Feasibility

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikrocata-venv/bin/python -c "import mikroclear; print(mikroclear.__file__)"'
```

Result:

```text
ModuleNotFoundError: No module named 'mikroclear'
```

Finding:

- `mikroclear` is not currently importable in the SELKS venv.
- This is expected because the package has not been installed into the venv.
- This blocks a direct `ExecStart=/opt/mikrocata-venv/bin/python -m mikroclear`
  switch until a package install or equivalent import path strategy is prepared.

## Risks

- The requested SSH alias `selks-mcp` does not exist locally. The configured MCP
  SSH alias is `selks`.
- The candidate package entrypoint is not importable on SELKS today.
- The active package-entrypoint switch is blocked until `mikroclear` is installed
  or otherwise made importable in `/opt/mikrocata-venv`.
- Read-only journal visibility is limited for the MCP SSH user.
- `/var/lib/mikrocata` is root-only, so file-level state inspection needs a
  separately approved sudo-capable check.

## Package-Entrypoint Switch Blockers

Blocking:

```text
/opt/mikrocata-venv/bin/python -m mikroclear
```

would fail today because `mikroclear` is not importable in the SELKS venv.

Not blocking:

- Python 3.11.2 is present.
- Core dependencies import successfully.
- Legacy script/env/state paths still exist for rollback.

## Rollback Constraints

Rollback must preserve:

```text
/usr/local/bin/mikrocataTZSP0.py
/etc/mikrocata/mikrocataTZSP0.env
/var/lib/mikrocata
/etc/systemd/system/mikrocataTZSP0.service
```

Any future package-entrypoint deploy plan must include backups of:

```text
/etc/systemd/system/mikroclear.service
/usr/local/bin/mikroclear.py
/usr/local/bin/mikrocataTZSP0.py
/etc/mikrocata/mikrocataTZSP0.env
/etc/mikroclear/mikroclear.env if present
```

No rollback commands were executed in this preflight.

## Next Safe Step

Prepare a separate non-deploy package install/importability plan:

1. Decide how SELKS venv will get the package:
   - editable install from a deployed source tree;
   - wheel install into `/opt/mikrocata-venv`;
   - or a controlled `PYTHONPATH` strategy.
2. Add local tests for the chosen install artifact.
3. Plan a read-only SELKS check to verify candidate importability without
   starting the runtime loop.
4. Only after explicit approval, perform SELKS package installation or candidate
   upload in a deploy-specific stage.
