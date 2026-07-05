# Mikro-Clear Systemd Package Entrypoint Candidate Plan

> **For agentic workers:** This is a non-deploy planning stage. Do not push, deploy,
> run `systemctl`, connect to RouterOS, touch SELKS, or start the real runtime loop.

**Goal:** Prepare a testable candidate systemd unit that can later switch
`mikroclear.service` from the legacy script path to the Mikro-Clear package
entrypoint.

**Candidate file:** `deploy/systemd/mikroclear.service.candidate`

**Production unit left unchanged:** `systemd/mikroclear.service`

## 1. Current Legacy Systemd Launch

The current production unit template in this repository still uses the deployed
single-file script:

```text
ExecStart=/opt/mikroclear-venv/bin/python /usr/local/bin/mikroclear.py
```

This is intentionally preserved in `systemd/mikroclear.service` for rollback and
for the current SELKS deployment window.

The unit reads both env files:

```text
EnvironmentFile=-/etc/mikrocata/mikrocataTZSP0.env
EnvironmentFile=-/etc/mikroclear/mikroclear.env
```

The legacy file is read first and the Mikro-Clear file second, so
`/etc/mikroclear/mikroclear.env` can override values after the config migration.

Legacy paths preserved during the transition:

```text
/usr/local/bin/mikroclear.py
/etc/mikrocata/mikrocataTZSP0.env
/var/lib/mikrocata
/etc/mikrocata
/opt/mikroclear-venv
```

Current Mikro-Clear paths already represented in the unit:

```text
/etc/mikroclear/mikroclear.env
/var/lib/mikroclear
```

## 2. Candidate ExecStart

The candidate unit uses the package module entrypoint:

```text
ExecStart=/opt/mikroclear-venv/bin/python -m mikroclear
```

This is safer than relying on a console script for the first switch because the
existing venv Python path is explicit and does not depend on whether a
`mikroclear` console wrapper exists in the SELKS venv `PATH`.

The console script remains useful later:

```text
mikroclear = "mikroclear.cli:main"
```

First switch recommendation:

1. Keep `/opt/mikroclear-venv/bin/python`.
2. Use `-m mikroclear`.
3. Keep `WorkingDirectory=/usr/local/bin` for now.
4. Keep the legacy script and env fallback until one stable runtime window passes.

## 3. EnvironmentFile Strategy

Keep both env files in the candidate:

```text
EnvironmentFile=-/etc/mikrocata/mikrocataTZSP0.env
EnvironmentFile=-/etc/mikroclear/mikroclear.env
```

Keep `/etc/mikrocata/mikrocataTZSP0.env` temporarily because production still has
legacy env history and rollback depends on it.

Use `/etc/mikroclear/mikroclear.env` as the migration target. It should contain
`MIKROCLEAR_*` variables and set:

```text
MIKROCLEAR_STATE_DIR=/var/lib/mikroclear
```

Required aliases and fallbacks:

- `MIKROCLEAR_*` must continue to override `MIKROCATA_*`.
- `MIKROCATA_*` must remain readable until the env migration and rollback window
  are complete.
- The unit must keep `/var/lib/mikrocata` writable until migrated state files are
  verified in `/var/lib/mikroclear`.

Later cleanup, after stable runtime:

1. Remove legacy env fallback.
2. Remove `/var/lib/mikrocata` from `ReadWritePaths`.
3. Remove `/etc/mikrocata` from `ReadOnlyPaths`.
4. Remove script rollback references after operator approval.

## 4. Rollback

Fast rollback is to restore the legacy ExecStart:

```text
ExecStart=/opt/mikroclear-venv/bin/python /usr/local/bin/mikroclear.py
```

Backups to create before any future deploy stage:

```text
/etc/systemd/system/mikroclear.service.bak-<timestamp>
/usr/local/bin/mikroclear.py.bak-<timestamp>
/etc/mikroclear/mikroclear.env.bak-<timestamp> if present
/etc/mikrocata/mikrocataTZSP0.env.bak-<timestamp>
```

Rollback checks after a future approved rollback:

```text
systemctl status mikroclear.service --no-pager --lines=25
journalctl -u mikroclear.service -n 100 --no-pager
python -m py_compile /usr/local/bin/mikroclear.py
```

These are documentation for a later approved SELKS stage. Do not run them in
this non-deploy stage.

## 5. Safety

Do not run systemctl in this stage.

Local-only checks allowed now:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_systemd_candidate_unit tests.test_systemd_unit
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
git ls-files '*.py' | xargs .venv/bin/python -m py_compile
git grep -n -I -E '(BEGIN (RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|[0-9]{6,}:[A-Za-z0-9_-]{30,})' -- .
```

Text-only candidate inspection allowed now:

```bash
sed -n '1,120p' deploy/systemd/mikroclear.service.candidate
```

SELKS commands require separate explicit confirmation in a later stage:

```text
systemd-analyze verify /path/to/candidate
systemctl daemon-reload
systemctl restart mikroclear.service
journalctl -u mikroclear.service ...
```

Do not connect to RouterOS and do not start the real runtime loop in this stage.

## 6. Tests

Text-based unit tests must verify:

- production unit still has the legacy ExecStart;
- candidate unit uses `/opt/mikroclear-venv/bin/python -m mikroclear`;
- candidate keeps both env files in legacy-then-current override order;
- candidate keeps legacy state/config paths during the transition;
- this plan contains rollback and safety notes.

The candidate unit is a repository artifact only. It is not a production unit and
must not be installed without a separate deploy plan and explicit approval.
