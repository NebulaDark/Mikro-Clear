# Dedicated service user cutover

Дата: 2026-07-06.

Цель: подготовить перевод `mikroclear.service` с `root` на отдельного
system user `mikroclear` без смешивания этого шага с legacy fallback cleanup.

## Текущий статус

Tracked unit пока остается:

```ini
User=root
Group=root
```

Причина: current Codex/MCP доступ не имеет passwordless sudo для проверки и
переноса ownership внутри `/var/lib/mikroclear`, а также для полного audit
read-access к SELKS paths.

## Preconditions

Перед изменением unit должны быть выполнены все условия:

1. State reconciliation завершен под root/operator.
2. `/var/lib/mikroclear` содержит нужные runtime files.
3. `/var/lib/mikroclear` принадлежит `mikroclear:mikroclear`.
4. Service user читает Suricata `eve.json`.
5. Service user читает RouterOS CA/cert paths из env.
6. Legacy env fallback уже удален из tracked unit и production deploy прошел
   stable observation window.

## Operator commands

Выполнять на SELKS под sudo-capable operator:

```bash
sudo useradd --system --home /var/lib/mikroclear --shell /usr/sbin/nologin mikroclear 2>/dev/null || true

sudo install -d -o mikroclear -g mikroclear -m 700 /var/lib/mikroclear
sudo chown -R mikroclear:mikroclear /var/lib/mikroclear

sudo -u mikroclear test -r /opt/SELKS/docker/containers-data/suricata/logs/eve.json
```

Если `eve.json` недоступен:

```bash
sudo setfacl -m u:mikroclear:rx /opt/SELKS/docker/containers-data/suricata/logs
sudo setfacl -m u:mikroclear:r /opt/SELKS/docker/containers-data/suricata/logs/eve.json
```

Проверить RouterOS TLS files, подставив значения из
`/etc/mikroclear/mikroclear.env`:

```bash
sudo -u mikroclear test -r /etc/mikrocata/certs/mikrotik-ca.crt
```

Если certificate path будет перенесен в `/etc/mikroclear`, проверить новый path
точно так же.

## Unit change

Только после preconditions:

```ini
User=mikroclear
Group=mikroclear
```

Deploy unit отдельным approved operation:

```bash
sudo systemd-analyze verify /etc/systemd/system/mikroclear.service
sudo systemctl daemon-reload
sudo systemctl restart mikroclear.service
sudo systemctl status mikroclear.service --no-pager --lines=30
```

## Verification

```bash
systemctl show mikroclear.service --property=ActiveState,SubState,NRestarts,ExecMainStartTimestamp,User,Group --no-pager
sudo journalctl -u mikroclear.service -n 200 --no-pager \
  | sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g' \
  | grep -Ei 'permission denied|traceback|failed|routeros|eve.json' || true
```

Acceptance criteria:

- `ActiveState=active`;
- `SubState=running`;
- `NRestarts=0`;
- no `Permission denied`;
- RouterOS connects;
- `eve.json` monitoring starts;
- state files are writable by `mikroclear`.

## Rollback

If service fails after the user change:

```bash
sudo sed -i 's/^User=mikroclear$/User=root/; s/^Group=mikroclear$/Group=root/' /etc/systemd/system/mikroclear.service
sudo systemctl daemon-reload
sudo systemctl restart mikroclear.service
sudo systemctl status mikroclear.service --no-pager --lines=30
```

Do not delete the `mikroclear` user until logs confirm the rollback reason.
