# План тестирования и воспроизведения установки

Документ фиксирует повторяемую проверку автономного установщика Mikro-Clear.
Автоматические тесты не должны обращаться к production RouterOS, реальному
Telegram-боту или изменять рабочий SELKS. Проверка живых интеграций выполняется
оператором только на выделенном стенде.

## Матрица

| ОС | Режим | Сценарий | Ожидаемый результат |
|---|---|---|---|
| Debian 12 | шаблон | Чистая установка | файлы созданы, сервис не запущен |
| Debian 12 | интерактивный | Чистая установка | acceptance успешен |
| Debian 12 | без аргументов | Повторный запуск | выполняется безопасное обновление |
| Debian 12 | без аргументов | Успешное обновление | новая версия active, старая в backup |
| Debian 12 | тестовая инъекция | Неуспешное обновление | выполнен проверенный rollback |
| Debian 13 | шаблон | Чистая установка | файлы созданы, сервис не запущен |
| Debian 13 | интерактивный | Чистая установка | acceptance успешен |
| Debian 13 | без аргументов | Повторный запуск | выполняется безопасное обновление |
| Debian 13 | без аргументов | Успешное обновление | новая версия active, старая в backup |
| Debian 13 | тестовая инъекция | Неуспешное обновление | выполнен проверенный rollback |
| обе ОС | права EVE | `eve.json` недоступен | отказ до запуска, без изменения прав |
| обе ОС | Telegram выключен | локальная граница | worker marker не требуется |
| обе ОС | Telegram включён | тестовый бот | worker marker и ответ `/status` |

## Подготовка чистой VM

Для каждой ОС создайте отдельную VM с systemd:

- Debian 12, актуальный образ Bookworm;
- Debian 13, актуальный образ Trixie;
- 2 CPU, 2 GiB RAM, не менее 8 GiB свободного диска;
- отдельная тестовая сеть;
- snapshot `before-mikroclear`.

После первого boot:

```bash
sudo apt-get update
sudo apt-get install -y \
  git openssl python3 python3-venv python3-pip systemd util-linux acl
python3 --version
systemctl --version | head -n 1
cat /etc/os-release
```

Получите точную версию кода:

```bash
git clone https://github.com/paveltarasov50-coder/Mikro-Clear.git
cd Mikro-Clear
git switch --detach <tag-or-commit>
git rev-parse HEAD
git status --short
```

Запишите имя образа VM, версию ядра, Python и commit SHA в таблицу evidence.

## Локальная проверка до root-установки

```bash
python3 -m venv .venv
.venv/bin/python -m pip install 'setuptools>=68' wheel
.venv/bin/python -m pip install -e .
bash -n scripts/install-selks.sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python -m unittest discover -s tests
PYTHONPYCACHEPREFIX=/tmp/mikroclear-pycache \
  git ls-files '*.py' | xargs .venv/bin/python -m py_compile
```

Для автоматических тестов RouterOS и Telegram заменяются локальными doubles.
Не подставляйте production env-файл и реальные секреты. Sourceable guard
позволяет тестам вызывать функции установщика без выполнения `main`.

## Fixture eve.json

На обычной Debian VM создайте имитацию SELKS-пути:

```bash
sudo install -d -o root -g root -m 0755 \
  /opt/SELKS/docker/containers-data/suricata/logs
sudo install -o root -g root -m 0644 /dev/null \
  /opt/SELKS/docker/containers-data/suricata/logs/eve.json
```

Это только стендовая fixture. На реальном SELKS установщик не должен менять
владельца, ACL или режимы Docker-каталогов.

## Сценарий 1: шаблон

На snapshot `before-mikroclear`:

```bash
cd Mikro-Clear
sudo ./scripts/install-selks.sh --config-template
systemctl is-active mikroclear.service || true
sudo stat -c '%U:%G %a %n' \
  /etc/mikroclear \
  /etc/mikroclear/certs \
  /etc/mikroclear/mikroclear.env \
  /var/lib/mikroclear \
  /var/backups/mikroclear \
  /etc/systemd/system/mikroclear.service
```

Ожидается:

- exit code `0`;
- env-файл создан из шаблона с `root:mikroclear 640`;
- runtime и unit установлены;
- manifest имеет `status=template`;
- сервис не запущен.

Заполните только тестовые значения:

```bash
sudoedit /etc/mikroclear/mikroclear.env
sudo ./scripts/install-selks.sh --start
```

На VM без тестового RouterOS `--start` обязан завершиться ошибкой acceptance и
оставить сервис остановленным. Это ожидаемая безопасная граница, а не успешная
интеграционная проверка.

## Сценарий 2: интерактивная установка

Верните snapshot `before-mikroclear`, снова получите тот же commit и запустите:

```bash
cd Mikro-Clear
sudo ./scripts/install-selks.sh --interactive
```

Используйте только тестовый RouterOS и, если выбран Telegram, только тестового
бота и тестовый Chat ID. Зафиксируйте:

```bash
systemctl show mikroclear.service \
  --property=ActiveState,SubState,NRestarts,TasksCurrent,User,Group,WorkingDirectory,MainPID \
  --no-pager
sudo journalctl -u mikroclear.service -n 100 --no-pager |
  sed -E 's#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g'
sudo stat -c '%U:%G %a %n' \
  /etc/mikroclear/mikroclear.env \
  /etc/mikroclear/certs/mikrotik-ca.crt \
  /var/lib/mikroclear/install-manifest
```

### Telegram выключен

Установите `MIKROCLEAR_TELEGRAM_ENABLE=false`. Ожидается успешный acceptance без
маркера Telegram worker. RouterOS и EVE остаются обязательными.

### Telegram включён

Установите `MIKROCLEAR_TELEGRAM_ENABLE=true`, включите control plane и оставьте
`MIKROCLEAR_BOT_DRY_RUN=true`. Ожидаются:

- `Telegram polling worker started` в журнале;
- `TasksCurrent` не меньше двух;
- ответ тестового бота на `/status`;
- отсутствие `Traceback` и fatal-сообщений.

Секреты в evidence не копируйте.

## Сценарий 3: ошибка доступа к EVE

Верните snapshot либо остановите тестовый сервис, затем:

```bash
sudo chmod 0600 \
  /opt/SELKS/docker/containers-data/suricata/logs/eve.json
before_mode="$(
  stat -c '%U:%G %a' \
    /opt/SELKS/docker/containers-data/suricata/logs/eve.json
)"
sudo ./scripts/install-selks.sh --interactive
after_mode="$(
  stat -c '%U:%G %a' \
    /opt/SELKS/docker/containers-data/suricata/logs/eve.json
)"
printf 'before=%s\nafter=%s\n' "${before_mode}" "${after_mode}"
```

Ожидается ненулевой код, сообщение `eve.json is not readable by mikroclear`,
вывод диагностики и одинаковые `before`/`after`. После теста верните fixture:

```bash
sudo chmod 0644 \
  /opt/SELKS/docker/containers-data/suricata/logs/eve.json
```

## Сценарий 4: Повторный запуск

На успешно установленной тестовой системе, не меняя commit:

```bash
sudo ./scripts/install-selks.sh
systemctl show mikroclear.service \
  --property=ActiveState,SubState,NRestarts \
  --no-pager
sudo ls -la /var/backups/mikroclear
```

Ожидается обновление из того же committed `HEAD`, успешный acceptance и новый
timestamp-каталог backup. Существующая конфигурация не должна быть
перезаписана.

## Сценарий 5: Успешное обновление

Сделайте snapshot `installed-old`, затем:

```bash
git fetch origin
git switch --detach <new-tag-or-commit>
old_manifest="$(sudo sha256sum /var/lib/mikroclear/install-manifest)"
sudo ./scripts/install-selks.sh
new_manifest="$(sudo sha256sum /var/lib/mikroclear/install-manifest)"
printf 'old=%s\nnew=%s\n' "${old_manifest}" "${new_manifest}"
systemctl show mikroclear.service \
  --property=ActiveState,SubState,NRestarts,User,Group,WorkingDirectory \
  --no-pager
sudo find /var/backups/mikroclear -maxdepth 2 -type f -o -type d
```

Ожидается новый commit в manifest, active/running, `NRestarts=0`, предыдущий
virtualenv в backup и неизменные секретные значения env.

## Сценарий 6: Неуспешное обновление и rollback

Не ломайте production unit, сеть или реальный сервис. Failure injection
выполняется только через sourceable функции в локальном test root:

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_selks_standalone_installer.SelksStandaloneInstallerTests.test_failed_update_runs_rollback_and_returns_nonzero \
  tests.test_selks_standalone_installer.SelksStandaloneInstallerTests.test_rollback_restores_previous_files_and_venv \
  tests.test_selks_standalone_installer.SelksStandaloneInstallerTests.test_rollback_health_checks_all_properties \
  tests.test_selks_standalone_installer.SelksStandaloneInstallerTests.test_rollback_stops_when_venv_restore_fails
```

Ожидается `OK`. Тесты подтверждают порядок операций, byte-for-byte возврат
старого virtualenv и файлов, повторный запуск старого сервиса и отдельный код
ошибки при неуспешном rollback.

На выделенном полном стенде можно воспроизвести acceptance failure отключением
только тестового RouterOS после создания backup. После команды установки
проверьте:

```bash
systemctl show mikroclear.service \
  --property=ActiveState,SubState,NRestarts \
  --no-pager
sudo find /var/backups/mikroclear -maxdepth 2 -printf '%M %u:%g %p\n'
sudo sha256sum \
  /etc/systemd/system/mikroclear.service \
  /etc/mikroclear/mikroclear.env \
  /var/lib/mikroclear/install-manifest
```

Старый сервис должен быть active/running с `NRestarts=0`, а failed runtime —
сохранён в backup.

## Очистка и возврат стенда

Предпочтительный способ — восстановить VM snapshot. Если disposable VM
очищается вручную:

```bash
sudo systemctl disable --now mikroclear.service || true
sudo mv /etc/systemd/system/mikroclear.service \
  /var/tmp/mikroclear.service.test-artifact 2>/dev/null || true
sudo systemctl daemon-reload
sudo mv /opt/mikroclear-venv \
  /var/tmp/mikroclear-venv.test-artifact 2>/dev/null || true
sudo mv /etc/mikroclear \
  /var/tmp/mikroclear-config.test-artifact 2>/dev/null || true
sudo mv /var/lib/mikroclear \
  /var/tmp/mikroclear-state.test-artifact 2>/dev/null || true
```

Перемещение сохраняет артефакты для анализа. Удаляйте их только после проверки
evidence и только на disposable VM.

## Таблица evidence

Для каждого сценария сохраните:

| Поле | Что записать |
|---|---|
| OS | `PRETTY_NAME` из `/etc/os-release` |
| Kernel | `uname -r` |
| Python | `python3 --version` |
| Commit | `git rev-parse HEAD` |
| Wheel SHA | SHA-256 собранного wheel или manifest |
| Paths/modes | `stat` без содержимого env |
| systemd | выбранные свойства через `systemctl show` |
| Acceptance | обязательные markers, без токенов |
| rollback | backup path, хеши восстановленных файлов, health |
| Secret scan | подтверждение, что токены и пароли не попали в evidence |
| Result | PASS, FAIL или NOT RUN с причиной |

Итоговый отчёт должен явно различать локальные автоматические тесты,
стендовую интеграцию и проверки, которые не запускались.
