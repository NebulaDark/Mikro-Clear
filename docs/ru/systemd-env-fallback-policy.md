# Политика systemd/env fallback

Обновлено: 2026-09-10 при завершении PR №4.

## Текущее состояние репозитория

Tracked unit больше не содержит legacy fallback. Оба файла,
`systemd/mikroclear.service` и `deploy/systemd/mikroclear.service.candidate`,
используют:

```ini
ExecStart=/opt/mikroclear-venv/bin/python -m mikroclear
EnvironmentFile=/etc/mikroclear/mikroclear.env
User=mikroclear
Group=mikroclear
WorkingDirectory=/
ReadWritePaths=/var/lib/mikroclear
ReadOnlyPaths=/opt/SELKS/docker/containers-data/suricata/logs /etc/mikroclear
```

Env-файл обязателен: отсутствие ведущего `-` предотвращает запуск с
отсутствующим файлом. Это поведение уже реализовано в `main` до завершения
PR №4. Актуальное состояние SELKS нужно проверять отдельно.

## Исторический fallback

В конфигурации от 6 июля использовались два необязательных файла:

```ini
EnvironmentFile=-/etc/mikrocata/mikrocataTZSP0.env
EnvironmentFile=-/etc/mikroclear/mikroclear.env
```

Primary env читался вторым и переопределял значения legacy env. Эта схема
приведена только для распознавания старой установки, не для нового deploy.

## Условия удаления legacy env fallback

При обновлении старого сервера оператор проверяет:

1. Полноту `/etc/mikroclear/mikroclear.env`, включая canonical `MIKROCLEAR_*`
   параметры. Установщик задаёт владельца `root:mikroclear` и режим `0640`.
2. Использование `/var/lib/mikroclear` для state и сохранность необходимых
   файлов; каталог принадлежит `mikroclear:mikroclear` с режимом `0700`.
3. Доступ пользователя службы к `eve.json` и настроенному CA-сертификату.
4. Наличие резервной копии runtime, unit, env и state согласно инструкции
   установки, прежде чем менять действующий сервис.
5. После согласованного обновления — package entrypoint, `active/running`,
   `NRestarts=0`, отсутствие ошибок доступа и окно наблюдения. При включённом
   Telegram polling проверяются также worker и число задач процесса.

Порядок миграции, acceptance и rollback описан в
[инструкции установки](install-from-github.md) и
[проверке отдельного пользователя](dedicated-service-user-cutover.md).
Завершение PR само по себе не выполняет deploy и не удаляет старые env/state
файлы на SELKS. Их удаление относится к отдельному операторскому действию.
