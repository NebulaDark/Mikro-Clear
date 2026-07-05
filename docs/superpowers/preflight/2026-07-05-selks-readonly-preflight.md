# SELKS Read-Only Preflight Before Package Entrypoint Switch

Date: 2026-07-05

Scope: read-only SELKS preflight before a future systemd package-entrypoint
switch. No push, no deploy, no restart, no `systemctl` mutation, no SELKS file
changes, and no RouterOS write action were performed.

Correction: the production service is `mikroclear.service`. The legacy
`mikrocataTZSP0` names are compatibility paths only and must not be treated as
the active production service.

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

The configured MCP SSH user should therefore use host alias `selks`.

## 1. Current Production Systemd Unit

Commands for the corrected read-only preflight target:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'systemctl cat mikroclear.service'

ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'systemctl status mikroclear.service --no-pager'

ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'systemctl show mikroclear.service --property=ExecStart,EnvironmentFiles,FragmentPath,DropInPaths'
```

Expected current production values:

```text
FragmentPath=/etc/systemd/system/mikroclear.service
ExecStart=/opt/mikrocata-venv/bin/python /usr/local/bin/mikroclear.py
```

Expected env strategy:

```text
EnvironmentFile=-/etc/mikrocata/mikrocataTZSP0.env
EnvironmentFile=-/etc/mikroclear/mikroclear.env
```

The legacy env file remains a compatibility fallback. The production service
unit remains `mikroclear.service`.

## 2. Python And Venv

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikrocata-venv/bin/python --version'
```

Observed result:

```text
Python 3.11.2
```

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikrocata-venv/bin/python -c "import sys; print(sys.path)"'
```

Observed result:

```text
['', '/usr/lib/python311.zip', '/usr/lib/python3.11', '/usr/lib/python3.11/lib-dynload', '/opt/mikrocata-venv/lib/python3.11/site-packages']
```

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikrocata-venv/bin/python -c "import librouteros, requests, ujson; print(\"deps ok\")"'
```

Observed result:

```text
deps ok
```

Findings:

- SELKS venv is Python 3.11.2.
- Core runtime dependencies `librouteros`, `requests`, and `ujson` are present.
- The venv search path does not include the repository package by default.

## 3. Current Production Files And Compatibility Env

Commands for the corrected production script target:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'ls -l /usr/local/bin/mikroclear.py'

ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'ls -l /etc/mikroclear/ /etc/mikroclear/mikroclear.env 2>/dev/null || true'

ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'ls -ld /var/lib/mikroclear/ 2>/dev/null || true'
```

Compatibility checks for legacy env/state paths:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'ls -l /etc/mikrocata/mikrocataTZSP0.env'

ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'ls -ld /var/lib/mikrocata/'
```

Observed compatibility results:

```text
-rw------- 1 root root 3660 Jul  3 13:46 /etc/mikrocata/mikrocataTZSP0.env
drwx------ 2 root root 4096 Jul  5 15:51 /var/lib/mikrocata/
```

Finding:

- Legacy env/state compatibility paths exist.
- Production file checks must target `/usr/local/bin/mikroclear.py` and
  `mikroclear.service`.

## 4. Logs Read-Only

Corrected command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'journalctl -u mikroclear.service -n 80 --no-pager'
```

Known limitation from the MCP SSH user:

```text
Hint: You are currently not seeing messages from other users and the system.
Users in groups 'adm', 'systemd-journal' can see all messages.
```

Finding:

- Journal access for the MCP SSH user may be limited.
- Production logs must be queried with `-u mikroclear.service`.

## 5. Candidate Import Feasibility

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikrocata-venv/bin/python -c "import mikroclear; print(mikroclear.__file__)"'
```

Observed result:

```text
ModuleNotFoundError: No module named 'mikroclear'
```

Finding:

- `mikroclear` is not currently importable in the SELKS venv.
- This blocks a direct `ExecStart=/opt/mikrocata-venv/bin/python -m mikroclear`
  switch until package install or another import path strategy is prepared.

## Risks

- The requested SSH alias `selks-mcp` does not exist locally. The configured MCP
  SSH alias is `selks`.
- The candidate package entrypoint is not importable on SELKS today.
- The active package-entrypoint switch is blocked until `mikroclear` is installed
  or otherwise made importable in `/opt/mikrocata-venv`.
- Read-only journal visibility is limited for the MCP SSH user.
- Legacy env/state directories are root-owned and may need separately approved
  sudo-capable checks for file-level state verification.

## Package-Entrypoint Switch Blockers

Blocking:

```text
/opt/mikrocata-venv/bin/python -m mikroclear
```

would fail today because `mikroclear` is not importable in the SELKS venv.

Not blocking:

- Python 3.11.2 is present.
- Core dependencies import successfully.
- Legacy env/state paths still exist for compatibility and rollback.

## Rollback Constraints

Rollback must preserve:

```text
/usr/local/bin/mikroclear.py
/etc/systemd/system/mikroclear.service
/etc/mikrocata/mikrocataTZSP0.env
/var/lib/mikrocata
```

Any future package-entrypoint deploy plan must include backups of:

```text
/etc/systemd/system/mikroclear.service
/usr/local/bin/mikroclear.py
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
