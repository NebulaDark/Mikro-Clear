# Mikro-Clear Security Runbook

Security-focused checks for the SELKS-hosted Mikro-Clear deployment.

## Weekly Checks

Run on SELKS as a sudo-capable operator:

```bash
systemctl status mikroclear.service --no-pager --lines=25
systemctl is-active mikroclear.service
systemctl is-enabled mikroclear.service
systemctl is-active mikrocataTZSP0.service || true
systemctl is-enabled mikrocataTZSP0.service || true
```

Review recent service logs with token masking before copying output:

```bash
journalctl -u mikroclear.service -n 500 --no-pager \
  | sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g' \
  | grep -Ei 'error|traceback|failed|token|bot' || true
```

Check private config and state permissions:

```bash
stat -c '%a %U:%G %n' \
  /etc/mikroclear \
  /etc/mikroclear/mikroclear.env \
  /var/lib/mikroclear \
  /var/lib/mikroclear/telegram-unblock-actions.json 2>/dev/null || true
```

Expected private modes:

```text
700 /etc/mikroclear
600 /etc/mikroclear/mikroclear.env
700 /var/lib/mikroclear
600 /var/lib/mikroclear/telegram-unblock-actions.json
```

## Token Rotation

Use this after suspected token exposure or after any log-sharing mistake:

1. In BotFather, revoke the current token and generate a new one.
2. Update only `MIKROCLEAR_TELEGRAM_TOKEN` in `/etc/mikroclear/mikroclear.env`.
3. Restart the service:

```bash
sudo systemctl restart mikroclear.service
sudo systemctl status mikroclear.service --no-pager --lines=25
```

4. Verify masked logs:

```bash
sudo journalctl -u mikroclear.service -n 100 --no-pager \
  | sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g'
```

5. Decide whether to retain or vacuum old journal history. If policy allows
   purging old exposed-token logs after rotation:

```bash
sudo journalctl --rotate
sudo journalctl --vacuum-time=1s
```

## Deploy Verification

Before deploying:

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m py_compile src/mikroclear/*.py services/mcp-server/server.py
```

Upload and verify candidates on SELKS:

```bash
/usr/bin/install -d -m 700 /var/tmp/mikroclear-deploy
# upload /var/tmp/mikroclear-deploy/mikroclear.py.codex-candidate
# upload /var/tmp/mikroclear-deploy/mikroclear-codex.service
/opt/mikrocata-venv/bin/python -c "path='/var/tmp/mikroclear-deploy/mikroclear.py.codex-candidate'; compile(open(path, encoding='utf-8').read(), path, 'exec'); print('OK')"
/usr/bin/systemd-analyze verify /var/tmp/mikroclear-deploy/mikroclear-codex.service
```

After deploy:

```bash
sudo systemctl status mikroclear.service --no-pager --lines=30
sudo journalctl -u mikroclear.service -n 100 --no-pager \
  | sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g' \
  | grep -Ei 'permission denied|protect|read-only|failed|traceback|bot[0-9]+:' || true
```

Keep rollback backup paths printed by the deploy workflow until the service has
passed runtime verification.

## Sudoers Regression Checks

After installing `deploy/sudoers.d/mikroclear-mcp-selks`, these checks should be
denied:

```bash
sudo -n -l /usr/bin/sed -E 's/.*/id/e' /etc/mikrocata/mikrocataTZSP0.env
sudo -n -l /usr/bin/tail -n '+1' /etc/shadow /opt/SELKS/docker/containers-data/suricata/logs/eve.json
sudo -n -l /usr/bin/journalctl -u mikroclear.service -n '10 -u ssh.service' --no-pager
```

The allowed env read path is the fixed helper:

```bash
sudo -n /usr/local/sbin/mikroclear-mask-env /etc/mikroclear/mikroclear.env
```
