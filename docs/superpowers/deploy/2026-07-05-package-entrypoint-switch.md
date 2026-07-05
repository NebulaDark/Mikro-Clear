# Package Entrypoint Switch Deploy Report

Date: 2026-07-05

Scope: production `mikroclear.service` package-entrypoint switch on SELKS.

## Result

The production `mikroclear.service` now runs from the package entrypoint:

```text
/opt/mikroclear-venv/bin/python -m mikroclear
```

Final service state:

```text
Result=success
NRestarts=0
ExecStart={ path=/opt/mikroclear-venv/bin/python ; argv[]=/opt/mikroclear-venv/bin/python -m mikroclear ; ignore_errors=no ; start_time=[Sun 2026-07-05 17:50:52 MSK] ; stop_time=[n/a] ; pid=3457281 ; code=(null) ; status=0/0 }
ActiveState=active
SubState=running
```

Final `systemctl status` evidence:

```text
Active: active (running) since Sun 2026-07-05 17:50:52 MSK
CGroup: /system.slice/mikroclear.service
        /opt/mikroclear-venv/bin/python -m mikroclear
```

## Pre-Switch Checks

Confirmed before switch:

```text
/opt/mikroclear-venv/lib/python3.11/site-packages/mikroclear/__init__.py
```

The package import check succeeded:

```bash
/opt/mikroclear-venv/bin/python -c "import mikroclear; print(mikroclear.__file__)"
```

The service was still active on the legacy ExecStart before the switch:

```text
/opt/mikrocata-venv/bin/python /usr/local/bin/mikroclear.py
```

## Initial Failure And Fix

The first restart attempt failed before Python startup with:

```text
status=226/NAMESPACE
Failed to set up mount namespacing: /run/systemd/unit-root/var/lib/mikroclear: No such file or directory
```

Cause:

```text
/var/lib/mikroclear
/etc/mikroclear
```

were missing on SELKS while the candidate unit referenced them in sandbox path
directives.

The service was immediately rolled back to the legacy unit and restored to
active/running. The missing directories were then created by the root operator:

```bash
mkdir -p /var/lib/mikroclear /etc/mikroclear
chmod 700 /var/lib/mikroclear
chmod 755 /etc/mikroclear
chown root:root /var/lib/mikroclear /etc/mikroclear
```

After that, the switch was repeated successfully.

## Rollback Context

The pre-switch unit was saved at:

```text
/var/tmp/mikroclear-deploy/mikroclear.service.before-package-entrypoint
```

Legacy rollback ExecStart:

```text
/opt/mikrocata-venv/bin/python /usr/local/bin/mikroclear.py
```

This legacy rollback remains available until the package-entrypoint runtime has
passed a stable observation window.

## Notes

- `systemd-analyze verify /etc/systemd/system/mikroclear.service` passed before restart.
- `mikroclear.service` is enabled and active.
- RouterOS connection succeeded after the package-entrypoint startup.
- No new Telegram write actions were added.
- The package-entrypoint switch used the already installed wheel in
  `/opt/mikroclear-venv`.
