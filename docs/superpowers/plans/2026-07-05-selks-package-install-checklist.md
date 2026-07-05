# SELKS Package Install Checklist

> **For agentic workers:** This checklist is for a future deploy stage only. Requires separate explicit deploy approval. Do not run this checklist during non-deploy planning.

**Goal:** Install the Mikro-Clear wheel into the existing SELKS venv so `/opt/mikrocata-venv/bin/python -m mikroclear` becomes importable before a later systemd ExecStart switch.

**Scope:** Package install/importability only. This checklist does not switch systemd, does not restart `mikroclear.service`, and does not connect to RouterOS.

## Guardrails

- Requires separate explicit deploy approval.
- Do not run this checklist during non-deploy planning.
- Do not push from SELKS.
- Do not change `/etc/systemd/system/mikroclear.service` in this package install step.
- Do not switch ExecStart until import succeeds.
- Do not restart `mikroclear.service` in the package install step.
- Do not run `systemctl daemon-reload`, `start`, `stop`, `restart`, `enable`, or `disable`.
- Do not start the real runtime loop.
- No RouterOS connection.

## Inputs

Expected local artifact from the package importability stage:

```text
dist/mikro_clear-0.1.0-py3-none-any.whl
```

Expected current production service identity:

```text
service: mikroclear.service
unit path: /etc/systemd/system/mikroclear.service
current ExecStart: /opt/mikrocata-venv/bin/python /usr/local/bin/mikroclear.py
candidate ExecStart: /opt/mikrocata-venv/bin/python -m mikroclear
```

## Checklist

1. backup current service and script

   Future approved command shape:

   ```bash
   sudo cp -a /etc/systemd/system/mikroclear.service /etc/systemd/system/mikroclear.service.bak-<timestamp>
   sudo cp -a /usr/local/bin/mikroclear.py /usr/local/bin/mikroclear.py.bak-<timestamp>
   ```

2. upload wheel to /var/tmp/mikroclear-deploy/

   Future approved command shape:

   ```bash
   ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
     'mkdir -p /var/tmp/mikroclear-deploy'

   scp -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new \
     dist/mikro_clear-0.1.0-py3-none-any.whl \
     selks:/var/tmp/mikroclear-deploy/
   ```

3. install wheel into /opt/mikrocata-venv

   Future approved command shape:

   ```bash
   ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
     '/opt/mikrocata-venv/bin/python -m pip install --no-deps /var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl'
   ```

4. run import-only check

   Future approved command shape:

   ```bash
   ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
     '/opt/mikrocata-venv/bin/python -c "import mikroclear; print(mikroclear.__file__)"'
   ```

   This import-only check must not call `app.main()` and must not start Telegram polling.

5. keep systemd unchanged

   Required after package install:

   ```text
   Do not switch ExecStart until import succeeds.
   Do not restart `mikroclear.service` in the package install step.
   ```

   A later separately approved stage may consider replacing:

   ```text
   ExecStart=/opt/mikrocata-venv/bin/python /usr/local/bin/mikroclear.py
   ```

   with:

   ```text
   ExecStart=/opt/mikrocata-venv/bin/python -m mikroclear
   ```

## Rollback

rollback with pip uninstall mikro-clear

Future approved command shape:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikrocata-venv/bin/python -m pip uninstall mikro-clear'
```

Rollback constraints preserve:

```text
/usr/local/bin/mikroclear.py
/etc/systemd/system/mikroclear.service
/etc/mikrocata/mikrocataTZSP0.env
/var/lib/mikrocata
```

If the package install is rolled back before the systemd switch, the active service continues to use:

```text
/opt/mikrocata-venv/bin/python /usr/local/bin/mikroclear.py
```

No `systemctl` action is part of this package-install rollback unless a later approved systemd switch has also happened.
