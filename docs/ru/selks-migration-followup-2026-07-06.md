# SELKS migration follow-up 2026-07-06

Дата: 2026-07-06.

Этот документ фиксирует фактическое состояние после:

- merge canonical module ownership в `main`;
- миграции primary env на `/etc/mikroclear/mikroclear.env`;
- перехода state dir на `/var/lib/mikroclear`;
- повторного package deploy из `main`.

## Package deploy из main

Локальный branch:

```text
main
```

Локальный merge commit на момент deploy:

```text
85a830c Merge systemd env fallback policy
```

Локальные проверки перед deploy:

```text
unittest discover: 196 tests OK
py_compile: OK
app.build_service(): MikroClearService
wheel validation: OK
```

Wheel:

```text
dist/mikro_clear-0.1.0-py3-none-any.whl
```

Sha256:

```text
e4ee2b1cc78e1d21e658eeb151f372fe35f4fb76699ad9a85498619f20b8774e
```

SELKS upload path:

```text
/var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl
```

Install command used:

```bash
sudo -n /opt/mikroclear-venv/bin/python -m pip install --no-deps --force-reinstall \
  /var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl
```

Import check on SELKS returned:

```text
/opt/mikroclear-venv/lib/python3.11/site-packages/mikroclear/__init__.py
MikroClearService
```

## Service state after deploy

```text
ActiveState=active
SubState=running
NRestarts=0
ExecMainStartTimestamp=Mon 2026-07-06 07:38:33 MSK
ExecStart=/opt/mikroclear-venv/bin/python -m mikroclear
```

Fresh startup log evidence:

```text
[Mikro-Clear] Starting Mikro-Clear v3.1.1-TZSP0-ASSET-RESOLVER
[Mikro-Clear] RouterOS API: 192.168.10.1:8729 SSL
[Mikro-Clear] Telegram: enabled
[Mikro-Clear] Connected to MikroTik
[Mikro-Clear] Monitoring /opt/SELKS/docker/containers-data/suricata/logs/eve.json for Suricata alerts
```

No fresh `Traceback` or crash was observed in the checked status/log window.

## Env migration status

Primary env exists and is used:

```text
/etc/mikroclear/mikroclear.env
```

Masked env check confirmed:

```text
MIKROCLEAR_ROUTER_USERNAME=...
MIKROCLEAR_TELEGRAM_TOKEN=***MASKED***
MIKROCLEAR_STATE_DIR="/var/lib/mikroclear"
```

Legacy env remains as fallback/rollback:

```text
/etc/mikrocata/mikrocataTZSP0.env
```

Systemd still intentionally keeps this order:

```text
EnvironmentFile=-/etc/mikrocata/mikrocataTZSP0.env
EnvironmentFile=-/etc/mikroclear/mikroclear.env
```

## Runtime state paths

Runtime settings on SELKS resolved these state paths:

```text
state_dir=/var/lib/mikroclear
save_lists_location=/var/lib/mikroclear/savelists-tzsp0.json
save_lists_location_v6=/var/lib/mikroclear/savelists-tzsp0_v6.json
uptime_bookmark=/var/lib/mikroclear/uptime-tzsp0.bookmark
ignore_list_location=/var/lib/mikroclear/ignore-tzsp0.conf
telegram_lock_file=/var/lib/mikroclear/telegram-rate-limit.lock
telegram_unblock_state_file=/var/lib/mikroclear/telegram-unblock-actions.json
```

The fresh service start after the ignore-list follow-up no longer showed:

```text
Ignore list /var/lib/mikroclear/ignore-tzsp0.conf not found
```

## Remaining state migration commands

The current MCP/SSH user cannot list or copy arbitrary files inside
`/var/lib/mikroclear` and `/var/lib/mikrocata` because those directories are
root-owned and sudoers is intentionally narrow. A root/sudo-capable operator
should run this one-time state reconciliation on SELKS:

```bash
sudo install -d -o root -g root -m 700 /var/lib/mikroclear

for name in \
  savelists-tzsp0.json \
  savelists-tzsp0_v6.json \
  uptime-tzsp0.bookmark \
  ignore-tzsp0.conf \
  telegram-unblock-actions.json
do
  if [ -f "/var/lib/mikrocata/$name" ] && [ ! -f "/var/lib/mikroclear/$name" ]; then
    sudo cp -a "/var/lib/mikrocata/$name" "/var/lib/mikroclear/$name"
  fi
done

sudo touch /var/lib/mikroclear/ignore-tzsp0.conf
sudo chmod 600 /var/lib/mikroclear/*.json /var/lib/mikroclear/*.bookmark /var/lib/mikroclear/*.conf 2>/dev/null || true
sudo chown root:root /var/lib/mikroclear/* 2>/dev/null || true

sudo systemctl restart mikroclear.service
sudo systemctl status mikroclear.service --no-pager --lines=30
```

Rollback note: do not delete `/var/lib/mikrocata` until the service has passed
the fallback-removal criteria in `docs/ru/systemd-env-fallback-policy.md`.
