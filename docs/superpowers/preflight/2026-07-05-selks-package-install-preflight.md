# SELKS Package Install Preflight

Date: 2026-07-05

Scope: read-only preflight before a future wheel upload/install stage. No push from SELKS, no deploy, no package install, no SELKS file changes, no `systemctl` mutation, no service restart, no RouterOS connection, and no runtime loop start were performed.

## Result

The SELKS host is ready for a separately approved wheel upload/install stage,
but the package is not installed yet.

The future package install remains blocked until explicit operator approval.
The systemd package-entrypoint switch remains blocked until the wheel is
installed and an import-only check succeeds.

## Current Production Service

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'systemctl cat mikroclear.service'
```

Observed:

```text
# /etc/systemd/system/mikroclear.service
EnvironmentFile=-/etc/mikrocata/mikrocataTZSP0.env
EnvironmentFile=-/etc/mikroclear/mikroclear.env
ExecStart=/opt/mikrocata-venv/bin/python /usr/local/bin/mikroclear.py
```

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'systemctl show mikroclear.service --property=ExecStart,EnvironmentFiles,FragmentPath,DropInPaths'
```

Observed:

```text
ExecStart={ path=/opt/mikrocata-venv/bin/python ; argv[]=/opt/mikrocata-venv/bin/python /usr/local/bin/mikroclear.py ; ignore_errors=no ; start_time=[Sat 2026-07-04 18:31:59 MSK] ; stop_time=[n/a] ; pid=1800991 ; code=(null) ; status=0/0 }
EnvironmentFiles=/etc/mikrocata/mikrocataTZSP0.env (ignore_errors=yes)
EnvironmentFiles=/etc/mikroclear/mikroclear.env (ignore_errors=yes)
FragmentPath=/etc/systemd/system/mikroclear.service
DropInPaths=
```

Finding:

- Production service identity is correct: `mikroclear.service`.
- Current ExecStart is still the legacy script:
  `/opt/mikrocata-venv/bin/python /usr/local/bin/mikroclear.py`.
- No systemd switch has happened.

## Existing Venv And Pip

Commands:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikrocata-venv/bin/python --version'

ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikrocata-venv/bin/python -m pip --version'
```

Observed:

```text
Python 3.11.2
pip 26.1.2 from /opt/mikrocata-venv/lib/python3.11/site-packages/pip (python 3.11)
```

Finding:

- `/opt/mikrocata-venv` can run Python 3.11.
- `pip` is available in the target venv.

## Current Import State

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikrocata-venv/bin/python -c "import mikroclear; print(mikroclear.__file__)"'
```

Observed:

```text
Traceback (most recent call last):
  File "<string>", line 1, in <module>
ModuleNotFoundError: No module named 'mikroclear'
```

Finding:

- `mikroclear` is not importable in the SELKS venv yet.
- This is expected before wheel install.
- Do not switch ExecStart to `/opt/mikrocata-venv/bin/python -m mikroclear`
  until this import-only check succeeds.

## Rollback Anchors

Command:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'ls -l /usr/local/bin/mikroclear.py /etc/systemd/system/mikroclear.service /etc/mikrocata/mikrocataTZSP0.env'
```

Observed:

```text
-rw------- 1 root root  3660 Jul  3 13:46 /etc/mikrocata/mikrocataTZSP0.env
-rw-r--r-- 1 root root   501 Jul  2 20:44 /etc/systemd/system/mikroclear.service
-rwxr-xr-x 1 root root 63445 Jul  4 18:31 /usr/local/bin/mikroclear.py
```

Finding:

- Legacy script, active unit, and legacy env rollback anchors exist.

## Go/No-Go

Go for a separately approved wheel upload/install stage:

- target venv exists;
- target venv has pip;
- production service still runs the legacy script;
- rollback anchors exist.

Still no-go for systemd package-entrypoint switch:

- `mikroclear` is not importable in `/opt/mikrocata-venv`.

## Next Safe Step

After explicit approval, perform only the package install stage:

1. Build and validate wheel locally.
2. Upload wheel to `/var/tmp/mikroclear-deploy/`.
3. Install with:

   ```bash
   /opt/mikrocata-venv/bin/python -m pip install --no-deps /var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl
   ```

4. Run only:

   ```bash
   /opt/mikrocata-venv/bin/python -c "import mikroclear; print(mikroclear.__file__)"
   ```

Do not run `systemctl`, do not restart `mikroclear.service`, and do not change
`ExecStart` during that package install stage.
