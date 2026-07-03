# Mikro-Clear Runbook

Operational procedures for the SELKS-hosted Mikro-Clear service.

## Telegram Token Rotation

Use this procedure after any suspected Telegram Bot token exposure, and after
logging fixes that previously could have printed Bot API URLs.

Do not paste the live token into chat, issue trackers, shell history snippets,
logs, or commits.

### 1. Revoke And Generate Token

In Telegram BotFather:

```text
/mybots -> select bot -> API Token -> Revoke current token -> Generate new token
```

Keep the new token only in the operator's password manager or secure clipboard
for the time needed to update SELKS.

### 2. Update SELKS Environment

Run this on SELKS as a sudo-capable operator:

```bash
sudoedit /etc/mikrocata/mikrocataTZSP0.env
```

Replace only the token value:

```text
MIKROCATA_TELEGRAM_TOKEN="<new-token>"
```

The current service accepts both legacy `MIKROCATA_*` and new `MIKROCLEAR_*`
environment names. Keep the existing file format until the environment rename
task is completed.

### 3. Restart And Verify

Run:

```bash
sudo systemctl restart mikroclear.service
sudo systemctl status mikroclear.service --no-pager --lines=25
```

Check that the service is active and that no raw Bot API token appears in recent
logs. Always mask output before sharing it:

```bash
sudo journalctl -u mikroclear.service -n 100 --no-pager \
  | sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g'
```

Expected:

```text
mikroclear.service: active
Telegram API URLs, if present, show /bot***MASKED***/
no Traceback or NameError lines after restart
```

### 4. Decide Journal Retention

Old journal entries may still contain the revoked token from before the logging
fix. After the token has been revoked, choose one of these options:

Option A: keep logs for audit retention. Record that the exposed token was
revoked and no longer grants access.

Option B: purge old journal history if local retention policy allows it. This
affects systemd journal history on the host, not only Mikro-Clear logs:

```bash
sudo journalctl --rotate
sudo journalctl --vacuum-time=1s
```

After either option, verify current service state again:

```bash
sudo systemctl status mikroclear.service --no-pager --lines=25
sudo journalctl -u mikroclear.service -n 100 --no-pager \
  | sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g'
```

## Telegram Log Sharing Rule

Before sharing any Mikro-Clear service logs, run them through token masking:

```bash
sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g'
```
