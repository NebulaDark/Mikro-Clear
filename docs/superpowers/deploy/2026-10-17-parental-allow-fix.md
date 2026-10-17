# Parental ALLOW fix deployment — 2026-10-17

User approved deployment and restart after reviewing the fix. The package was
built from `ac8ab16` plus the working-tree parental menu and Pi-hole adapter
changes. Local verification: 553 tests passed, 131 tracked Python files compiled,
and `git diff --check` passed. Git changes are being finalized separately from
this production installation.

## Artifacts

- Candidate: `/var/tmp/mikroclear-deploy/parental-fix-20261017/mikro_clear-0.1.0-py3-none-any.whl`
- Candidate SHA-256: `53f16fa2afbf7f45423004a4ee32da9821c0c9ea40224b70e8025080e55ab7b0`
- Rollback: `/var/tmp/mikroclear-deploy/rollback-before-parental-fix-20261017/mikro_clear-0.1.0-py3-none-any.whl`
- Rollback SHA-256: `b00606d3835030e3e9aa1214bc7e30ce085034a21848b43fe87f555d60017663`

Before installation, all 69 Python files in the rollback wheel matched the
installed package. Both saved wheel checksums were verified on SELKS.

## Execution and verification

The deployment helper installed the candidate successfully, but its subsequent
`build_service()` check ran as `mcp-selks` and could not read the service-owned
`/var/lib/mikroclear/dynamic-whitelist.json`. Its chained restart did not run.
No permissions were changed. Imports were checked separately, then the approved
restart was executed through systemd as the configured `mikroclear` service user.

Observed after restart:

- Started: `2026-10-17 10:34:13 MSK`.
- PID: `3881056`; `active/running`; `TasksCurrent=2`; `NRestarts=0`.
- Logs confirm RouterOS connection, Suricata EVE monitoring and Telegram worker startup.
- SHA-256 of all five changed production Python modules matches the local source.

## User acceptance

The user previously confirmed BLOCK works on two televisions. After deployment
and the request to check ALLOW on each television, the user confirmed:
“Подтверждаю разблокировку”. This records user acceptance of the unblocking fix;
no separate authenticated Pi-hole membership snapshot was collected by the agent.

The user subsequently closed the DNS/DoT/DoQ/IPv6 bypass and device-isolation
follow-up, and the restart-persistence and practical-rollback follow-up. These
items are closed by user decision; no additional production tests were run for
them. The user authorized committing the change and opening a pull request.

## Rollback

Run on SELKS with the existing deployment permissions, if needed:

```sh
cp /var/tmp/mikroclear-deploy/rollback-before-parental-fix-20261017/mikro_clear-0.1.0-py3-none-any.whl /var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl
sudo -n /opt/mikroclear-venv/bin/python -m pip install --no-deps --force-reinstall /var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl
sudo -n /usr/bin/systemctl restart mikroclear.service
systemctl show mikroclear.service --property=ActiveState,SubState,TasksCurrent,NRestarts --no-pager
```

Confirm worker startup and RouterOS/EVE monitoring in the journal after rollback.
