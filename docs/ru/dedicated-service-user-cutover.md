# Отдельный пользователь службы Mikro-Clear

Обновлено: 2026-09-10 при завершении PR №4.

В текущем репозитории оба systemd unit уже используют:

```ini
User=mikroclear
Group=mikroclear
WorkingDirectory=/
EnvironmentFile=/etc/mikroclear/mikroclear.env
```

Это состояние исходников, а не подтверждение текущей конфигурации SELKS.
При завершении PR сервер не проверялся и не изменялся.

## Поддерживаемый переход

Для старой установки используйте [инструкцию установки](install-from-github.md).
`scripts/install-selks.sh` создаёт пользователя, проверяет доступ к `eve.json`,
нормализует права runtime-файлов и выполняет обновление с резервной копией и
проверкой запуска. Ручная замена только `User`/`Group` не заменяет эти шаги.

Если старый env требует миграции, сначала изучите
`scripts/migrate-selks-config-f6ac4d2.py`: он отдельно переносит параметры и CA,
создаёт резервную копию и оставляет операции бота в dry-run. Применять его
повторно без сверки текущих настроек нельзя: он задаёт целевые значения Bot.

Ожидаемые права соответствуют установщику:

| Объект | Владелец | Режим |
|---|---|---|
| `/var/lib/mikroclear` | `mikroclear:mikroclear` | `0700` |
| `/etc/mikroclear/mikroclear.env` | `root:mikroclear` | `0640` |
| `/etc/mikroclear/certs/mikrotik-ca.crt` | `root:mikroclear` | `0640` |

Не выполняйте рекурсивный `chown` над state-каталогом вместо проверок
установщика. Доступ к Suricata должен сохраняться после ротации логов.

## Проверка на SELKS

Команды чтения для оператора с соответствующими правами:

```bash
systemctl show mikroclear.service --property=ActiveState,SubState,NRestarts,User,Group,TasksCurrent,ExecStart --no-pager
sudo stat -c '%U:%G %a %n' /var/lib/mikroclear /etc/mikroclear/mikroclear.env /etc/mikroclear/certs/mikrotik-ca.crt
sudo -u mikroclear test -r /opt/SELKS/docker/containers-data/suricata/logs/eve.json
sudo -u mikroclear test -r /etc/mikroclear/certs/mikrotik-ca.crt
sudo -u mikroclear test -w /var/lib/mikroclear
```

Путь `eve.json` и необходимость CA сверяйте с действующей конфигурацией.
Не публикуйте содержимое env или необработанный журнал с секретами.

При включённом Telegram polling дополнительно нужны сообщение
`Telegram polling worker started`, не менее двух задач процесса и окно
наблюдения без перезапусков. Одного `active/running` недостаточно.

## Откат

Используйте резервную копию и процедуру rollback из инструкции установки.
Не переводите сервис на root как универсальный способ исправить права:
сначала определите недоступный файл и восстановите согласованную версию
runtime, unit и конфигурации. Deploy, restart и rollback на SELKS требуют
отдельного согласования с оператором.
