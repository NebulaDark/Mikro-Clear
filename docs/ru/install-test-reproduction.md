# План тестирования и воспроизведения установки

Документ фиксирует повторяемую проверку автономного установщика Mikro-Clear.
Автоматические тесты не должны обращаться к production RouterOS, реальному
Telegram-боту или изменять рабочий SELKS. Проверка живых интеграций выполняется
оператором только на выделенном стенде.

Debian 12 и Debian 13 ниже — проверенные примеры, а не запрет на более новую ОС.
Более новый Linux допустим при выполнении требований из
`install-from-github.md`.

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

Проверить отдельно fail-closed контракт повреждённого managed JSON:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python -m unittest \
  tests.test_dynamic_whitelist.DynamicWhitelistStoreTests.test_invalid_existing_document_fails_closed \
  tests.test_dynamic_whitelist.DynamicWhitelistStoreTests.test_invalid_utf8_fails_closed_without_exposing_content
```

Ожидается `OK`: повреждённый `dynamic-whitelist.json` не сбрасывается и не
принимается. При реальном startup это останавливает сервис до обработки EVE.

## STOP: отдельно одобряемая live-проверка

На этом локальная проверка заканчивается. Не обновляйте SELKS, не
перезапускайте сервис и не выполняйте записи в RouterOS или Telegram без
отдельного явного разрешения. До запроса разрешения подготовьте точный commit
SHA, snapshot/rollback point, тестовые RouterOS и Telegram, отдельную сеть и
ожидаемые команды. Следующий раздел выполняется только после такого одобрения.

### Точный сценарий после одобрения

Используйте выделенный изолированный test host `192.168.250.250`. До создания
alert проверьте по DHCP, ARP и инвентарю стенда, что этот адрес не занят, не
попадает под `MIKROCLEAR_WHITELIST_IPS` и не относится к production. Не
подставляйте production IP, пароли, Telegram token или production Chat ID.

1. На стендовом SELKS откройте заранее проверенный Git checkout, убедитесь, что
   рабочее дерево чистое, запишите фактический commit и только затем выполните
   установку/обновление repository script:

   ```bash
   git status --short
   tested_commit="$(git rev-parse HEAD)"
   printf 'tested_commit=%s\n' "${tested_commit}"
   sudo ./scripts/install-selks.sh
   ```

2. В одобренном стендовом env задайте все gates явно:

   ```env
   MIKROCLEAR_TELEGRAM_ENABLE=true
   MIKROCLEAR_TELEGRAM_UNBLOCK_ENABLE=true
   MIKROCLEAR_TELEGRAM_WHITELIST_CONTROL_ENABLE=true
   MIKROCLEAR_MANGLE_CONTROL_ENABLE=true
   MIKROCLEAR_BOT_ENABLE=true
   MIKROCLEAR_BOT_DRY_RUN=false
   MIKROCLEAR_BOT_MODULES=status,mangle_control,whitelist_control
   ```

   В `MIKROCLEAR_BOT_ADMIN_CHAT_IDS` должен быть только заранее одобренный
   тестовый admin chat. На тестовом RouterOS заранее подготовьте хотя бы одно
   безопасное managed fixture rule без IP-адресов: имя `STAND-MANGLE`,
   comment=`MC:STAND-MANGLE`, chain=`prerouting`, action=`mark-routing`.
   Comment prefix, chain и action должны входить в одобренную Mangle
   конфигурацию стенда.
3. До первого alert докажите пустой managed baseline. В admin chat выполните
   `/status`: ожидаются `bot dry-run: off`,
   `telegram whitelist control: on`, правильные `state-dir` и
   `whitelist store`, а также точная строка `managed whitelist: 0`. Вывод
   `/status` не должен содержать `192.168.250.250` или любой другой адрес из
   managed store.

   Затем безопасно проверьте файл только на чтение:

   ```bash
   sudo -u mikroclear /opt/mikroclear-venv/bin/python -c \
     'import json; from pathlib import Path; p=Path("/var/lib/mikroclear/dynamic-whitelist.json"); d=None if not p.exists() else json.loads(p.read_text(encoding="utf-8")); assert d is None or d == {"version": 1, "addresses": []}; print("managed baseline: 0")'
   ```

   Допустимы только отсутствие файла или документ
   `{"version": 1, "addresses": []}`. Если `/status` или команда показывают
   другое состояние, остановите сценарий и восстановите подготовленный
   snapshot. Не удаляйте и не сбрасывайте state этой инструкцией.
4. В изолированной тестовой сети ещё раз подтвердите, что
   `192.168.250.250` не занят. С помощью тестового Suricata rule/fixture
   с подходящими `severity` и `in_iface` создайте контролируемый `BLOCKED` alert,
   где target равен `192.168.250.250`. Сохраните один и тот же sanitized JSON
   event как fixture для повторной подачи.
5. В alert нажмите `🛡 Добавить в исключения 192.168.250.250`, затем подтвердите
   `✅ Добавить и разблокировать`.
6. Проверьте владельца, режим и точный адрес, не публикуя весь state:

   ```bash
   sudo stat -c '%U:%G %a %n' \
     /var/lib/mikroclear/dynamic-whitelist.json
   sudo -u mikroclear /opt/mikroclear-venv/bin/python -c \
     'import json; p="/var/lib/mikroclear/dynamic-whitelist.json"; d=json.load(open(p, encoding="utf-8")); assert d == {"version": 1, "addresses": ["192.168.250.250"]}; print("managed fixture: OK")'
   ```

   Ожидаются `mikroclear:mikroclear`, режим `600` и `managed fixture: OK`.
7. На тестовом RouterOS проверьте, что address-list `Suricata` больше не
   содержит `192.168.250.250`.
8. Оператор должен повторно подать тот же controlled EVE event. Ожидаются
   отсутствие новой блокировки RouterOS и нового `BLOCKED` alert.
9. Откройте `🛡 Mikro-Clear` → `🛡 Исключения`, выберите managed-адрес и
   подтвердите удаление исключения кнопкой `✅ Удалить исключение`. Системные
   записи не должны предлагать удаление.
10. Сразу после удаления исключения подтвердите, что Mikro-Clear не добавил
   адрес в RouterOS автоматически.
11. Ещё раз повторно подайте controlled event. Ожидаются обычная блокировка
    `192.168.250.250` в `Suricata` и новый `BLOCKED` alert.
12. Повторите `/status`: он снова должен показать `managed whitelist: 0` и не
    раскрывать список managed addresses.
13. Проверьте Mangle двумя независимыми поверхностями. В корневом меню компактная
    кнопка fixture должна отражать фактическое состояние:
    `✅ STAND-MANGLE` для enabled или `❌ STAND-MANGLE` для disabled.
    В `Статус` → `🔀 Mangle` ожидается подробное состояние того же fixture с
    chain, action, `Packets:` и `Bytes:`. Выполните обычный подтверждённый
    toggle и верните правило в исходное состояние.
14. Выполните обычный `🔓 Unblock 192.168.250.250`. При искусственно
    воспроизведённом частичном результате alert должен показать
    `🔄 Повторить разблокировку`; retry не должен повторно записывать исключение.

Сохраните evidence с commit SHA, временем, sanitized event SID, `stat`,
состоянием тестового RouterOS и ожидаемыми Telegram labels. После проверки
восстановите snapshot стенда либо выполните ранее одобренный rollback.

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
