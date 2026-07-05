# SELKS Package Install Preflight Plan

> **For agentic workers:** This is a non-deploy, read-only preflight stage. Do not push, deploy, install packages, edit SELKS files, run mutating `systemctl` commands, or connect to RouterOS.

**Goal:** Decide whether Mikro-Clear is ready for a separately approved SELKS wheel upload/install stage.

**Architecture:** Verify local wheel readiness, then perform read-only SELKS checks for the active service, venv, pip availability, import state, and rollback prerequisites. This stage only produces evidence and a go/no-go recommendation; it does not install the wheel.

**Tech Stack:** Python 3.11, setuptools wheel, SSH read-only commands, systemd read-only inspection, unittest.

## Global Constraints

- No push, no deploy, no SELKS file changes.
- Use read-only SELKS checks only.
- Do not install the wheel.
- Do not run `systemctl` mutation commands.
- Do not run `systemctl daemon-reload`, `start`, `stop`, `restart`, `enable`, or `disable`.
- Do not change `/etc/systemd/system/mikroclear.service`.
- Do not change `ExecStart`.
- Do not start the real runtime loop.
- No RouterOS connection.

## Local Prerequisite

Build and validate the wheel locally before considering any SELKS install approval:

```bash
rm -rf /tmp/mikroclear-wheel-validation
mkdir -p /tmp/mikroclear-wheel-validation
.venv/bin/python -m pip wheel --no-deps --no-build-isolation . -w /tmp/mikroclear-wheel-validation
.venv/bin/python scripts/validate_wheel_artifact.py /tmp/mikroclear-wheel-validation/mikro_clear-0.1.0-py3-none-any.whl
```

Expected validator output:

```text
wheel ok: /tmp/mikroclear-wheel-validation/mikro_clear-0.1.0-py3-none-any.whl
```

The validator is `scripts/validate_wheel_artifact.py`. It checks the package entrypoint modules and console script metadata without importing or running the runtime.

## Read-Only SELKS Checks

All SELKS commands in this section are read-only.

### 1. Current Production Service

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'systemctl cat mikroclear.service'

ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'systemctl show mikroclear.service --property=ExecStart,EnvironmentFiles,FragmentPath,DropInPaths'
```

Expected:

```text
FragmentPath=/etc/systemd/system/mikroclear.service
ExecStart=/opt/mikroclear-venv/bin/python /usr/local/bin/mikroclear.py
```

If current ExecStart is not the legacy script, stop and re-plan. The package install stage assumes systemd is still unchanged.

### 2. Existing Venv And Pip

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikroclear-venv/bin/python --version'

ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikroclear-venv/bin/python -m pip --version'
```

Expected:

```text
Python 3.11.x
pip available from /opt/mikroclear-venv
```

### 3. Current Import State

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikroclear-venv/bin/python -c "import mikroclear; print(mikroclear.__file__)"'
```

ModuleNotFoundError is acceptable before install and means the package install blocker still exists.

If `mikroclear` is already importable, record the path and decide whether the existing installed code matches the local commit before installing anything.

### 4. Rollback File Presence

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'ls -l /usr/local/bin/mikroclear.py /etc/systemd/system/mikroclear.service /etc/mikrocata/mikrocataTZSP0.env'
```

Expected rollback anchors:

```text
/usr/local/bin/mikroclear.py
/etc/systemd/system/mikroclear.service
/etc/mikrocata/mikrocataTZSP0.env
```

## Blockers

Do not approve the SELKS package install stage if any of these are true:

- pip is unavailable in `/opt/mikroclear-venv`;
- current ExecStart is not the legacy script;
- `/etc/systemd/system/mikroclear.service` is missing;
- `/usr/local/bin/mikroclear.py` is missing;
- the local wheel does not pass `scripts/validate_wheel_artifact.py`;
- SELKS import already resolves `mikroclear` from an unexpected path;
- SSH read-only checks cannot confirm the active service identity.

## Next Gate

If this preflight is clean, the next gate is explicit operator approval to approve SELKS wheel upload/install.

That future action must follow the SELKS package install checklist and still must not switch systemd:

```text
SELKS package install checklist: docs/superpowers/plans/2026-07-05-selks-package-install-checklist.md
requires separate explicit deploy approval
```

The package install stage may upload and install the wheel into `/opt/mikroclear-venv`, then run only:

```bash
/opt/mikroclear-venv/bin/python -c "import mikroclear; print(mikroclear.__file__)"
```

Changing `ExecStart` to `/opt/mikroclear-venv/bin/python -m mikroclear` remains a later separate systemd switch stage.

## Verification

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_selks_package_install_preflight_plan
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
git ls-files '*.py' | xargs .venv/bin/python -m py_compile
git grep -n -I -E '(BEGIN (RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|[0-9]{6,}:[A-Za-z0-9_-]{30,})' -- .
git status --short
```
