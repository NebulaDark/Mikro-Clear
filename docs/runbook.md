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
sudoedit /etc/mikroclear/mikroclear.env
```

Replace only the token value:

```text
MIKROCLEAR_TELEGRAM_TOKEN="<new-token>"
```

The service still reads `/etc/mikrocata/mikrocataTZSP0.env` as a temporary
fallback, but `/etc/mikroclear/mikroclear.env` is the primary file.

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

## Env And State Migration

Use this once per SELKS host while migrating from legacy Mikrocata paths:

```bash
sudo install -d -o root -g root -m 700 /etc/mikroclear /var/lib/mikroclear
sudo cp -a /etc/mikrocata/mikrocataTZSP0.env /etc/mikroclear/mikroclear.env
sudo sed -i 's/^MIKROCATA_/MIKROCLEAR_/' /etc/mikroclear/mikroclear.env
sudo sed -i 's#^MIKROCLEAR_STATE_DIR=.*#MIKROCLEAR_STATE_DIR="/var/lib/mikroclear"#' /etc/mikroclear/mikroclear.env
sudo chmod 600 /etc/mikroclear/mikroclear.env
```

Restart and verify:

```bash
sudo systemctl restart mikroclear.service
sudo systemctl status mikroclear.service --no-pager --lines=25
stat -c '%a %U:%G %n' /etc/mikroclear /etc/mikroclear/mikroclear.env /var/lib/mikroclear
```

Expected modes:

```text
700 root:root /etc/mikroclear
600 root:root /etc/mikroclear/mikroclear.env
700 root:root /var/lib/mikroclear
```

## Dedicated Service User Evaluation

Current status from SELKS:

```text
755 UNKNOWN:UNKNOWN /opt/SELKS/docker/containers-data/suricata/logs
644 UNKNOWN:UNKNOWN /opt/SELKS/docker/containers-data/suricata/logs/eve.json
```

The Suricata log path is readable by a non-root service user, but the service
must stay on `User=root` until a sudo-capable operator prepares ownership for
state and verifies certificate/read paths.

Operator preparation:

```bash
sudo useradd --system --home /var/lib/mikroclear --shell /usr/sbin/nologin mikroclear
sudo install -d -o mikroclear -g mikroclear -m 700 /var/lib/mikroclear
sudo chown -R mikroclear:mikroclear /var/lib/mikroclear
sudo setfacl -m u:mikroclear:r /opt/SELKS/docker/containers-data/suricata/logs/eve.json
```

Only after that, change the service unit:

```ini
User=mikroclear
Group=mikroclear
```

Then verify:

```bash
sudo systemctl restart mikroclear.service
sudo systemctl status mikroclear.service --no-pager --lines=30
sudo journalctl -u mikroclear.service -n 100 --no-pager | grep -Ei 'permission denied|failed|traceback' || true
```

## RouterOS TLS Endpoint Identity

The current RouterOS API-SSL certificate observed from SELKS contains:

```text
subject=CN = 192.168.10.1
X509v3 Subject Alternative Name:
    IP Address:192.168.10.1, DNS:r1.21port.ru
```

Keep the configured TLS server name aligned with one SAN entry:

```text
MIKROCLEAR_ROUTER_TLS_SERVER_NAME=192.168.10.1
```

Before changing RouterOS certificates, verify the new certificate:

```bash
printf '' \
  | openssl s_client -connect 192.168.10.1:8729 -servername 192.168.10.1 -showcerts 2>/dev/null \
  | openssl x509 -noout -subject -issuer -ext subjectAltName -fingerprint -sha256
```

The certificate must chain to `MIKROCLEAR_CA_FILE` and include either the
configured IP address or DNS name in SAN. Do not set
`MIKROCLEAR_ALLOW_SELF_SIGNED_CERTS=true` except as an explicit temporary
break-glass rollback.
