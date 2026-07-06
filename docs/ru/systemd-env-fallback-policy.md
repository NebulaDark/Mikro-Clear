# Политика systemd/env fallback

Состояние production после миграции 2026-07-06:

```text
ExecStart=/opt/mikroclear-venv/bin/python -m mikroclear
EnvironmentFile=-/etc/mikrocata/mikrocataTZSP0.env
EnvironmentFile=-/etc/mikroclear/mikroclear.env
```

`/etc/mikroclear/mikroclear.env` является primary env. Legacy файл
`/etc/mikrocata/mikrocataTZSP0.env` временно оставлен как rollback/fallback.

## Почему fallback пока остается

- rollback на старый env возможен без изменения package code;
- production уже перешел на `python -m mikroclear`, но стабильное окно после
  env/state migration еще не закрыто;
- unit sandbox пока сохраняет доступ к `/var/lib/mikrocata` и `/etc/mikrocata`
  для rollback и совместимости state/config.

Порядок `EnvironmentFile` намеренный: legacy файл читается первым, primary
`/etc/mikroclear/mikroclear.env` вторым. В systemd последняя переменная с тем же
именем выигрывает, поэтому primary env переопределяет fallback.

## Условия удаления legacy env fallback

Удалять `/etc/mikrocata/mikrocataTZSP0.env` из systemd unit можно только после
выполнения всех условий:

1. `mikroclear.service` стабильно работает через package entrypoint не меньше
   одного наблюдаемого operational window.
2. `/etc/mikroclear/mikroclear.env` существует, имеет mode `600`, owner
   `root:root`, и содержит `MIKROCLEAR_*` переменные.
3. `/var/lib/mikroclear` используется как `MIKROCLEAR_STATE_DIR`.
4. Нужные state файлы перенесены или осознанно пересозданы в `/var/lib/mikroclear`.
5. После restart нет `Traceback`, `NameError`, RouterOS reconnect loop или
   предупреждений о потерянных обязательных файлах.
6. Есть rollback artifact: предыдущий wheel или backup unit, который можно
   восстановить без обращения к `/etc/mikrocata`.

## Cleanup PR

Этот cleanup подготовлен отдельно от production deploy. Tracked unit больше не
содержит legacy fallback:

```text
EnvironmentFile=-/etc/mikroclear/mikroclear.env
ReadWritePaths=/var/lib/mikroclear
ReadOnlyPaths=/opt/SELKS/docker/containers-data/suricata/logs /etc/mikroclear
```

Изменения в PR:

- удалить `EnvironmentFile=-/etc/mikrocata/mikrocataTZSP0.env`;
- удалить `/etc/mikrocata` из `ReadOnlyPaths`;
- удалить `/var/lib/mikrocata` из `ReadWritePaths`;
- обновить tests, docs и rollback инструкции;
- не удалять сам legacy env файл с SELKS до отдельного operator cleanup окна.

Production deploy этого unit разрешен только после root/operator state
reconciliation из `docs/ru/project-status-plan-2026-07-06.md`. До deploy на
SELKS legacy paths остаются production rollback boundary, но уже не являются
canonical tracked unit ownership.
