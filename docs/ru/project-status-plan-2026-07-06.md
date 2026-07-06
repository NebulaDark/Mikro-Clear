# Mikro-Clear project status and next plan

Дата: 2026-07-06.

Этот документ является сводным планом: что уже сделано, что подтверждено в
production, и что осталось выполнить. Детальные документы остаются источниками
подробностей, а этот файл служит навигацией по текущему состоянию.

## Текущее состояние

Production service на SELKS:

```text
service: mikroclear.service
entrypoint: /opt/mikroclear-venv/bin/python -m mikroclear
package: mikro-clear 0.1.0
primary env: /etc/mikroclear/mikroclear.env
primary state dir: /var/lib/mikroclear
legacy env fallback: /etc/mikrocata/mikrocataTZSP0.env
```

Последний подтвержденный deploy из `main`:

```text
main commit: 85a830c Merge systemd env fallback policy
wheel sha256: e4ee2b1cc78e1d21e658eeb151f372fe35f4fb76699ad9a85498619f20b8774e
service start: Mon 2026-07-06 07:38:33 MSK
state: active/running
NRestarts: 0
```

## Что сделано

### 1. Уход от `legacy_runtime.py`

Сделано:

- `src/mikroclear/legacy_runtime.py` удален.
- `src/mikroclear/legacy.py` оставлен как compatibility wrapper на
  `mikroclear.app.main`.
- Runtime больше не импортирует `legacy_runtime`.
- `python -m mikroclear` и CLI используют package entrypoint.

Проверки:

```bash
rg -n "from mikroclear import legacy_runtime|import mikroclear\\.legacy_runtime" src tests || true
```

Ожидаемо: нет совпадений.

### 2. Canonical module ownership

Сделано:

- Реализация перенесена в canonical package modules:
  `assets/`, `state/`, `suricata/`, `routeros/`, `telegram/`, `runtime/`.
- Старые top-level modules оставлены как compatibility shims.
- `app.py` стал тонким entrypoint/wiring boundary.
- Runtime composition вынесен в `runtime/providers.py`,
  `runtime/wiring.py`, `runtime/status_snapshot.py`.

Документы:

```text
docs/architecture.md
docs/ru/architecture.md
docs/ru/legacy-compatibility-cleanup-plan.md
```

### 3. Config/env migration

Сделано:

- `Settings.from_env()` читает canonical `MIKROCLEAR_*` имена.
- Legacy `MIKROCATA_*` fallback остался только в `config.py`.
- `/etc/mikroclear/mikroclear.env` создан на SELKS и используется как primary.
- `/etc/mikrocata/mikrocataTZSP0.env` оставлен как fallback/rollback.

Документы:

```text
docs/ru/env-reference.md
docs/ru/systemd-env-fallback-policy.md
```

### 4. Package deploy из GitHub/main

Сделано:

- Branch `feature/canonical-module-ownership` смержен в `main`.
- Branch `feature/systemd-env-fallback-policy` смержен в `main`.
- Branch `feature/selks-migration-followup` смержен в `main`.
- Wheel собран из `main` и установлен в `/opt/mikroclear-venv`.
- Service перезапущен и проверен.

Документы:

```text
docs/ru/install-from-github.md
docs/ru/deploy-2026-07-06.md
docs/ru/selks-migration-followup-2026-07-06.md
```

### 5. MCP deploy tooling

Сделано:

- Добавлены MCP tools:
  `check_mikroclear_import`, `upload_wheel_candidate`,
  `deploy_wheel_candidate`.
- Sudoers расширен под package wheel deploy.
- Helper `/usr/local/sbin/mikroclear-mask-env` установлен на SELKS.
- Sudoers `/etc/sudoers.d/mikroclear-mcp-selks` установлен на SELKS.

Ограничение:

- MCP sudoers намеренно узкий и не разрешает произвольный `cp`, `grep`,
  `find`, `visudo` или `sudo -l`.
- Произвольная state reconciliation внутри `/var/lib/*` требует root/operator.

## Что осталось сделать

### A. Завершить state reconciliation

Цель: убедиться, что все нужные runtime state files перенесены или осознанно
пересозданы в `/var/lib/mikroclear`.

Команды для root/operator на SELKS:

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

Acceptance criteria:

- service `active/running`;
- `NRestarts=0`;
- no fresh `Traceback`;
- no warning about missing required state files;
- RouterOS connects;
- `eve.json` monitoring starts.

### B. Observation window

Цель: не удалять rollback paths сразу после migration.

Наблюдать:

- service uptime;
- RouterOS reconnect behavior;
- Telegram polling errors/rate limits;
- alert processing;
- save-list persistence;
- ignore-list behavior;
- absence of raw secrets in logs.

Минимальные checks:

```bash
systemctl show mikroclear.service --property=ActiveState,SubState,NRestarts,ExecMainStartTimestamp --no-pager
sudo journalctl -u mikroclear.service -n 300 --no-pager | sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g'
```

### C. Remove legacy env fallback from systemd

Цель: после observation window убрать `/etc/mikrocata` из runtime unit.

Делать отдельным PR.

Изменения:

- удалить `EnvironmentFile=-/etc/mikrocata/mikrocataTZSP0.env`;
- удалить `/etc/mikrocata` из `ReadOnlyPaths`;
- удалить `/var/lib/mikrocata` из `ReadWritePaths`;
- обновить tests и docs;
- deploy unit только после отдельного approval.

Критерии описаны в:

```text
docs/ru/systemd-env-fallback-policy.md
```

### D. Compatibility shim deprecation

Цель: подготовить удаление старых import paths без неожиданного production
breakage.

Делать отдельными PR:

1. Audit production imports.
2. Пометить top-level shims как deprecated в docs.
3. Убедиться, что rollback не зависит от legacy Python imports.
4. Удалить shims и `src/mikrocata/*` только после stable window.

Критерии описаны в:

```text
docs/ru/legacy-compatibility-cleanup-plan.md
```

### E. Dedicated service user

Цель: перестать запускать service от `root`, если SELKS permissions позволят.

Предварительные действия:

- создать system user `mikroclear`;
- выдать доступ к `/var/lib/mikroclear`;
- проверить read access к Suricata `eve.json`;
- проверить RouterOS cert/CA paths;
- обновить unit `User=` и `Group=`;
- restart и проверка logs.

Этот шаг не должен смешиваться с удалением legacy fallback.

## Текущий safe stop point

На текущий момент безопасно остановиться здесь:

- production deploy из `main` выполнен;
- service active/running;
- primary env используется;
- state dir переключен на `/var/lib/mikroclear`;
- legacy env/state paths сохранены как rollback boundaries;
- compatibility shims не удалены.

Следующий практический шаг:

```text
A. Завершить state reconciliation под root/operator на SELKS.
```

После этого можно начинать observation window и готовить PR на удаление legacy
env fallback из systemd.
