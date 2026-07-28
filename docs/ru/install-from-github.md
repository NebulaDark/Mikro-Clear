# Установка Mikro-Clear из Git

Эта инструкция предназначена для чистой установки, повторного запуска и
обновления Mikro-Clear непосредственно на сервере SELKS. Установка выполняется
из локального Git checkout одним скриптом:

```text
scripts/install-selks.sh
```

Скрипт не подключается к другим серверам и не обновляет репозиторий. Он всегда
собирает и устанавливает точный зафиксированный `HEAD`, поэтому перед запуском
оператор сам выбирает нужный тег или commit.

## Поддерживаемая система

Официальная матрица проверки включает Debian 12 и Debian 13. Более новая версия
Debian или другой Linux с systemd также может работать: жёсткой проверки имени
и версии дистрибутива нет. Обязательны:

- Python 3.11 или новее с `venv` и `ensurepip`;
- systemd как активная init-система;
- Git, OpenSSL, util-linux и стандартные GNU utilities;
- `apt-get`, если установщику потребуется поставить недостающие системные
  пакеты;
- не менее 512 MiB свободного места в `/opt`, плюс размер текущего virtualenv
  при обновлении;
- локальный доступ к `eve.json`.

Установщик запускается от `root`. Если системной команды не хватает, он покажет
точный список и отдельно спросит разрешение на `apt-get update` и
`apt-get install`. Другие менеджеры пакетов автоматически не вызываются.

## Получение проверяемой версии

Выполните эти команды непосредственно на SELKS:

```bash
git clone https://github.com/paveltarasov50-coder/Mikro-Clear.git
cd Mikro-Clear
git switch --detach <tag-or-commit>
git status --short
git rev-parse HEAD
```

Замените `<tag-or-commit>` на проверенный тег или полный commit SHA. Незакоммиченные
файлы checkout не войдут в артефакт: установщик использует `git archive HEAD`.

## Автоматическая установка

### Выбор режима в меню

Для запуска меню:

```bash
sudo ./scripts/install-selks.sh
```

Для новой установки предлагаются ровно два варианта:

```text
1) Интерактивная настройка
2) Шаблон конфигурации
```

Если полная установка уже существует, повторный запуск без аргументов считается
обновлением текущего runtime.

### Вариант 1: интерактивная настройка

Режим можно выбрать в меню или явно:

```bash
sudo ./scripts/install-selks.sh --interactive
```

Скрипт запросит:

- имя, пароль, адрес и API-порт RouterOS;
- режим TLS, имя сервера и путь к CA-сертификату;
- включение Telegram, токен и Chat ID;
- включение управления mangle;
- подтверждение итоговой конфигурации.

Пароль RouterOS и Telegram-токен вводятся без отображения. В итоговом резюме
секреты заменяются на `***`. Значения с переводом строки отклоняются.

При проверяемом TLS исходный CA-сертификат валидируется OpenSSL и копируется в:

```text
/etc/mikroclear/certs/mikrotik-ca.crt
```

После записи конфигурации установщик собирает wheel из committed `HEAD`,
создаёт отдельный candidate virtualenv, переключает runtime, запускает сервис и
выполняет acceptance-проверку.

### Вариант 2: шаблон конфигурации

Режим можно выбрать в меню или явно:

```bash
sudo ./scripts/install-selks.sh --config-template
```

Он создаёт каталоги, virtualenv, unit и файл:

```text
/etc/mikroclear/mikroclear.env
```

Сервис при этом не запускается. Заполните конфигурацию:

```bash
sudoedit /etc/mikroclear/mikroclear.env
sudo install -o root -g mikroclear -m 0640 \
  /path/to/routeros-ca.crt \
  /etc/mikroclear/certs/mikrotik-ca.crt
sudo openssl x509 \
  -in /etc/mikroclear/certs/mikrotik-ca.crt \
  -noout
```

Если RouterOS TLS отключён или временно разрешена работа без проверки
сертификата, отдельный CA-файл не требуется. После заполнения конфигурации:

```bash
sudo ./scripts/install-selks.sh --start
```

`--start` проверяет обязательные параметры, доступ к `eve.json`, запускает
сервис и выполняет ту же acceptance-проверку.

## Безопасное включение Telegram-меню и исключений

Установщик сохраняет текущий env при обновлении и не включает write-функции
автоматически. Начните с безопасных значений:

```env
MIKROCLEAR_TELEGRAM_ENABLE=true
MIKROCLEAR_TELEGRAM_UNBLOCK_ENABLE=true
MIKROCLEAR_TELEGRAM_WHITELIST_CONTROL_ENABLE=false
MIKROCLEAR_BOT_ENABLE=true
MIKROCLEAR_BOT_DRY_RUN=true
MIKROCLEAR_BOT_ADMIN_CHAT_IDS=
MIKROCLEAR_BOT_MODULES=status,mangle_control,whitelist_control
```

Заполните admin chat ID, не публикуя token или содержимое env. После отдельно
одобренного изменения конфигурации и restart включите
`MIKROCLEAR_TELEGRAM_WHITELIST_CONTROL_ENABLE=true`, но оставьте dry-run.
Администратор запускает `/start` или `/menu`, получает постоянную кнопку
`🛡 Mikro-Clear` и открывает `🛡 Исключения`. Системные записи там доступны
только для чтения; управляемые точные RFC1918 IPv4 можно удалять с
подтверждением.

Alert для подходящего адреса показывает `🛡 Добавить в исключения <IP>`, затем
`✅ Добавить и разблокировать`. При частичном результате, когда JSON уже
сохранён, а RouterOS не изменён, появляется
`🔄 Повторить разблокировку`. Реальные добавление, удаление и разблокировка
начнутся только при `MIKROCLEAR_BOT_DRY_RUN=false`; это переключение и live
проверки требуют отдельного разрешения оператора.

Перечисленные Telegram/admin/module/feature/Unblock gates ограничивают только
Telegram-операции управления исключениями. Они не отключают runtime policy:
существующий корректный `dynamic-whitelist.json` загружается независимо от
Telegram-управления и участвует в подавлении alert и восстановлении RouterOS.

Dry-run не изменяет RouterOS и `dynamic-whitelist.json`, то есть managed
business store. При этом одноразовое состояние
`telegram-whitelist-actions.json` сохраняет обычный жизненный цикл, а
append-only audit log продолжает фиксировать действия. Поэтому сравнивать все
state-файлы до и после dry-run побайтно нельзя.

Файлы `dynamic-whitelist.json` и `telegram-whitelist-actions.json` по умолчанию
находятся в `MIKROCLEAR_STATE_DIR` (`/var/lib/mikroclear`). Первый файл имеет
режим `0600`. Повреждённый managed JSON останавливает startup до обработки
events; при неуспешном обновлении acceptance запускает штатный rollback.
`/status` показывает флаг, путь и количество управляемых исключений, но никогда
не раскрывает список адресов.

## Пользователь сервиса и файловая раскладка

Runtime работает не от root, а от системного пользователя и группы
`mikroclear`.

| Путь | Владелец | Режим | Назначение |
|---|---|---:|---|
| `/opt/mikroclear-venv` | root:root | доступ на чтение/исполнение | Python runtime |
| `/etc/mikroclear` | root:mikroclear | `0750` | конфигурация |
| `/etc/mikroclear/certs` | root:mikroclear | `0750` | сертификаты |
| `/etc/mikroclear/mikroclear.env` | root:mikroclear | `0640` | параметры и секреты |
| `/etc/mikroclear/certs/mikrotik-ca.crt` | root:mikroclear | `0640` | CA RouterOS |
| `/var/lib/mikroclear` | mikroclear:mikroclear | `0700` | состояние и audit log |
| `/var/backups/mikroclear` | root:root | `0700` | резервные копии обновлений |
| `/etc/systemd/system/mikroclear.service` | root:root | `0644` | systemd unit |

Unit использует:

```text
User=mikroclear
Group=mikroclear
WorkingDirectory=/
EnvironmentFile=/etc/mikroclear/mikroclear.env
ExecStart=/opt/mikroclear-venv/bin/python -m mikroclear
```

## Доступ к eve.json

Ожидаемый путь:

```text
/opt/SELKS/docker/containers-data/suricata/logs/eve.json
```

Установщик только проверяет чтение от имени `mikroclear`:

```bash
sudo -u mikroclear test -r \
  /opt/SELKS/docker/containers-data/suricata/logs/eve.json
```

Он не выполняет `chmod`, `chown`, `setfacl` и не меняет SELKS/Docker
автоматически. При ошибке скрипт выводит `namei`, `stat` и рекомендуемую команду
для группы либо ACL. Оператор должен изучить текущую модель прав, применить
минимальное изменение и повторить проверку.

## Acceptance после запуска

Установщик ждёт до 90 секунд и принимает установку только при выполнении всех
условий:

- `ActiveState=active`, `SubState=running`, `NRestarts=0`;
- `User=mikroclear`, `Group=mikroclear`, `WorkingDirectory=/`;
- процесс действительно запущен от `mikroclear`;
- импорт `mikroclear` идёт из active virtualenv;
- каталог состояния доступен на запись, а `eve.json` — на чтение;
- журнал содержит `Connected to MikroTik`;
- журнал не содержит `Traceback` или fatal-сообщение Telegram worker;
- при включённом Telegram журнал содержит `Telegram polling worker started`, а
  число задач не меньше двух.

Ручная проверка:

```bash
systemctl show mikroclear.service \
  --property=ActiveState,SubState,NRestarts,TasksCurrent,User,Group,WorkingDirectory,MainPID \
  --no-pager
journalctl -u mikroclear.service -n 100 --no-pager |
  sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g'
```

Если Telegram включён, отправьте тестовому боту:

```text
/status
```

Ожидаемый ответ должен показывать uptime, подключение RouterOS, актуальный путь
`eve.json`, address-list, режим monitor-only, Telegram unblock, dry-run и список
модулей. Для write-команд сначала сохраняйте `MIKROCLEAR_BOT_DRY_RUN=true`.

## Обновление

Перейдите в checkout, выберите новый проверенный commit и запустите:

```bash
git fetch origin
git switch --detach <new-tag-or-commit>
git rev-parse HEAD
sudo ./scripts/install-selks.sh
```

При существующей полной установке скрипт:

1. проверяет конфигурацию и доступ к `eve.json`;
2. сохраняет unit, env, CA, manifest, `pip freeze` и точный старый virtualenv;
3. собирает candidate из нового committed `HEAD`;
4. останавливает сервис только перед переключением;
5. переключает virtualenv переименованием в пределах `/opt`;
6. устанавливает unit и выполняет acceptance;
7. сохраняет предыдущий runtime в timestamp-каталоге backup.

Для обновления одновременно с повторным вводом конфигурации используйте:

```bash
sudo ./scripts/install-selks.sh --interactive
```

Режим `--config-template` никогда не перезаписывает существующую установку.

## Rollback

При неуспешном acceptance обновления скрипт автоматически:

- останавливает неуспешный сервис;
- перемещает failed virtualenv в каталог backup;
- возвращает точный предыдущий virtualenv;
- восстанавливает unit, env, CA и manifest;
- выполняет `daemon-reload`, запускает старую версию и проверяет её состояние.

Установщик возвращает ненулевой код даже после успешного автоматического
rollback. Если восстановленная версия не стала `active/running` с
`NRestarts=0`, выводится `ROLLBACK FAILED` и путь к backup. Не удаляйте этот
каталог до расследования.

Проверить резервные копии:

```bash
sudo ls -la /var/backups/mikroclear
sudo find /var/backups/mikroclear -maxdepth 2 -type f -printf '%M %u:%g %p\n'
```

## Диагностика

```bash
systemctl status mikroclear.service --no-pager --lines=30
systemctl show mikroclear.service \
  --property=ActiveState,SubState,NRestarts,TasksCurrent,User,Group,WorkingDirectory,MainPID \
  --no-pager
sudo journalctl -u mikroclear.service -n 100 --no-pager |
  sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g'
sudo stat -c '%U:%G %a %n' \
  /etc/mikroclear \
  /etc/mikroclear/certs \
  /etc/mikroclear/mikroclear.env \
  /etc/mikroclear/certs/mikrotik-ca.crt \
  /var/lib/mikroclear
```

Не публикуйте содержимое env-файла, пароли, токены и Bot API URL без
маскировки.

## Ручная установка

Автоматический скрипт — основной и более безопасный путь. Этот раздел описывает
его ручной эквивалент для аудита или восстановления.

### 1. Зависимости и committed snapshot

```bash
sudo apt-get update
sudo apt-get install -y \
  git openssl python3 python3-venv python3-pip systemd util-linux

git rev-parse HEAD
install_root="$(mktemp -d /var/tmp/mikroclear-manual.XXXXXX)"
git archive HEAD | tar -x -C "${install_root}"
```

### 2. Сборка и проверка wheel

```bash
python3 -m venv "${install_root}/build-venv"
"${install_root}/build-venv/bin/python" -m pip install 'setuptools>=68' wheel
mkdir -p "${install_root}/dist"
"${install_root}/build-venv/bin/python" -m pip wheel \
  --no-deps --no-build-isolation \
  --wheel-dir "${install_root}/dist" \
  "${install_root}"
"${install_root}/build-venv/bin/python" \
  "${install_root}/scripts/validate_wheel_artifact.py" \
  "${install_root}"/dist/mikro_clear-*.whl
sha256sum "${install_root}"/dist/mikro_clear-*.whl
```

Не устанавливайте `requirements.txt` в production runtime.

### 3. Identity, каталоги и конфигурация

```bash
sudo groupadd --system mikroclear 2>/dev/null || true
sudo useradd --system --gid mikroclear --no-create-home \
  --home-dir /nonexistent --shell /usr/sbin/nologin \
  mikroclear 2>/dev/null || true
sudo install -d -o root -g mikroclear -m 0750 \
  /etc/mikroclear /etc/mikroclear/certs
sudo install -d -o mikroclear -g mikroclear -m 0700 /var/lib/mikroclear
sudo install -d -o root -g root -m 0700 /var/backups/mikroclear
sudo install -o root -g mikroclear -m 0640 \
  "${install_root}/config/mikroclear.env.example" \
  /etc/mikroclear/mikroclear.env
sudoedit /etc/mikroclear/mikroclear.env
```

Минимально заполните RouterOS user, password, IP, port, state dir и EVE path.
Секретные значения в документации намеренно не приводятся:

```text
MIKROCLEAR_ROUTER_USERNAME=""
MIKROCLEAR_ROUTER_PASSWORD=""
MIKROCLEAR_ROUTER_IP=""
MIKROCLEAR_ROUTER_PORT=8729
MIKROCLEAR_STATE_DIR=/var/lib/mikroclear
MIKROCLEAR_EVE_JSON=/opt/SELKS/docker/containers-data/suricata/logs/eve.json
MIKROCLEAR_CA_FILE=/etc/mikroclear/certs/mikrotik-ca.crt
MIKROCLEAR_TELEGRAM_TOKEN=""
```

Для проверяемого RouterOS TLS:

```bash
sudo openssl x509 -in /path/to/routeros-ca.crt -noout
sudo install -o root -g mikroclear -m 0640 \
  /path/to/routeros-ca.crt \
  /etc/mikroclear/certs/mikrotik-ca.crt
```

### 4. Candidate virtualenv и EVE

```bash
sudo python3 -m venv /opt/.mikroclear-venv.candidate
sudo /opt/.mikroclear-venv.candidate/bin/python -m pip install \
  "${install_root}"/dist/mikro_clear-*.whl
cd /
/opt/.mikroclear-venv.candidate/bin/python -c \
  'import pathlib, mikroclear; print(pathlib.Path(mikroclear.__file__).resolve())'
sudo -u mikroclear test -r \
  /opt/SELKS/docker/containers-data/suricata/logs/eve.json
sudo -u mikroclear test -w /var/lib/mikroclear
```

Импорт должен указывать внутрь candidate `site-packages`.

### 5. Backup и переключение

Для чистой установки пропустите копирование старых файлов. При обновлении:

```bash
backup_dir="/var/backups/mikroclear/$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -d -o root -g root -m 0700 "${backup_dir}"
sudo cp -a /etc/systemd/system/mikroclear.service "${backup_dir}/"
sudo cp -a /etc/mikroclear/mikroclear.env "${backup_dir}/"
sudo cp -a /etc/mikroclear/certs/mikrotik-ca.crt "${backup_dir}/"
sudo cp -a /var/lib/mikroclear/install-manifest "${backup_dir}/"
sudo /opt/mikroclear-venv/bin/python -m pip freeze |
  sudo tee "${backup_dir}/pip-freeze.txt" >/dev/null
sudo systemctl stop mikroclear.service
sudo mv /opt/mikroclear-venv /opt/.mikroclear-venv.rollback
```

Переключение:

```bash
sudo mv /opt/.mikroclear-venv.candidate /opt/mikroclear-venv
sudo install -o root -g root -m 0644 \
  "${install_root}/systemd/mikroclear.service" \
  /etc/systemd/system/mikroclear.service
sudo systemd-analyze verify /etc/systemd/system/mikroclear.service
sudo systemctl daemon-reload
sudo systemctl enable --now mikroclear.service
```

Выполните acceptance-команды из раздела выше. Только после успеха перенесите
старый runtime в backup:

```bash
sudo mv /opt/.mikroclear-venv.rollback "${backup_dir}/venv"
```

### 6. Ручной rollback

Если новая версия не прошла проверку:

```bash
sudo systemctl stop mikroclear.service
sudo mv /opt/mikroclear-venv "${backup_dir}/failed-venv"
sudo mv /opt/.mikroclear-venv.rollback /opt/mikroclear-venv
sudo install -o root -g root -m 0644 \
  "${backup_dir}/mikroclear.service" \
  /etc/systemd/system/mikroclear.service
sudo install -o root -g mikroclear -m 0640 \
  "${backup_dir}/mikroclear.env" \
  /etc/mikroclear/mikroclear.env
sudo install -o root -g mikroclear -m 0640 \
  "${backup_dir}/mikrotik-ca.crt" \
  /etc/mikroclear/certs/mikrotik-ca.crt
sudo systemctl daemon-reload
sudo systemctl start mikroclear.service
systemctl show mikroclear.service \
  --property=ActiveState,SubState,NRestarts \
  --no-pager
```

Сохраните commit SHA, SHA-256 wheel и вывод проверок. План полного
воспроизведения приведён в
[`install-test-reproduction.md`](install-test-reproduction.md).
