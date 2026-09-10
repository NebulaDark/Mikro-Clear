# Проверка автономной установки SELKS — 2026-07-24

## Результат

Локальная реализация автономного установщика проверена на committed
`HEAD=d005921290867aafe3342cb6ff086e7b856b8175`.

Проверены Bash-код, Python-тесты, Python-компиляция, wheel из `git archive
HEAD`, metadata wheel, оба systemd unit и документационный контракт. Production
SELKS, живые RouterOS и Telegram не изменялись и автоматическими тестами не
вызывались.

## Среда проверки

| Поле | Значение |
|---|---|
| ОС | Debian GNU/Linux 13 (trixie) |
| Ядро | `6.12.94+deb13-amd64` |
| Python | `3.13.5` |
| systemd | `257.13-1~deb13u1` |
| ShellCheck | `0.10.0`, локально распакован в `/tmp`, без системной установки |
| Git commit | `d005921290867aafe3342cb6ff086e7b856b8175` |

Эта машина не является чистой Debian VM из тестовой матрицы. Наличие Debian 13
подтверждает локальную совместимость проверок, но не заменяет end-to-end
установку из snapshot.

## Статические и целевые проверки

Команды:

```bash
bash -n scripts/install-selks.sh
/tmp/mikroclear-shellcheck-download/root/usr/bin/shellcheck \
  scripts/install-selks.sh
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_settings \
  tests.test_standalone_install_contract \
  tests.test_wheel_artifact_validation \
  tests.test_systemd_unit \
  tests.test_systemd_candidate_unit \
  tests.test_selks_standalone_installer \
  tests.test_install_documentation
```

Результат:

```text
Ran 86 tests
OK
```

`bash -n` и ShellCheck завершились с exit code `0`.

ShellCheck первоначально обнаружил неиспользуемый sourceable state и
неоднозначную конструкцию проверки порта. После минимального исправления
ShellCheck и 51 тест установщика повторно завершились с exit code `0`.

## Полная Python-регрессия

Команды:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python -m unittest discover -s tests
PYTHONPYCACHEPREFIX=/tmp/mikroclear-pycache \
  git ls-files '*.py' | xargs .venv/bin/python -m py_compile
```

Результат:

```text
Ran 347 tests
OK
```

Компиляция всех отслеживаемых Python-файлов завершилась с exit code `0`.

## Проверка committed wheel

Артефакт собран не из рабочего дерева, а из snapshot:

```bash
verify_dir="$(mktemp -d /tmp/mikroclear-install-verify.XXXXXX)"
git archive HEAD | tar -x -C "${verify_dir}"
.venv/bin/python -m pip wheel \
  --no-deps --no-build-isolation \
  --wheel-dir "${verify_dir}/dist" \
  "${verify_dir}"
.venv/bin/python scripts/validate_wheel_artifact.py \
  "${verify_dir}"/dist/mikro_clear-*.whl
```

Финальный результат:

```text
wheel ok: /tmp/mikroclear-install-verify.vdiPUj/dist/mikro_clear-0.1.0-py3-none-any.whl
SHA-256: d748e0bcf4888d29ea1a169903adbdba01f57bcc49e68bff4d94575a818d1fb2
```

`Requires-Dist` содержит только:

```text
librouteros==4.0.1
pyinotify==0.9.6
requests==2.34.2
ujson==5.12.1
maxminddb==3.1.1
```

Tooling-зависимость перенесена в `[dependency-groups]` и отсутствует в wheel
metadata. Установщик дополнительно отклоняет candidate runtime, если tooling
package неожиданно оказался установлен.

### Дефект, найденный проверкой

Первая сборка committed `bc2e7df` завершилась ошибкой validator:

```text
wheel error: forbidden runtime dependency: mcp
```

Причина: `[project.optional-dependencies]` по стандарту сериализуется в
`Requires-Dist` с marker `extra`, то есть не удовлетворяет строгому требованию
об отсутствии tooling package в production metadata.

Исправление выполнено через RED/GREEN:

- тест контракта потребовал top-level `[dependency-groups]`;
- RED подтвердил старое размещение;
- зависимость перенесена без ослабления validator;
- 9 целевых тестов, тестовая сборка и финальная committed-сборка прошли.

## Проверка systemd

Оба unit проверены в отдельных offline-root под `/tmp`. В каждом root созданы
только фиктивный executable, env-файл и ожидаемые каталоги; сервис не
запускался.

Команда для каждого unit:

```bash
systemd-analyze verify \
  --recursive-errors=no \
  --root=<offline-root> \
  /etc/systemd/system/mikroclear.service
```

Результат:

```text
PRIMARY_UNIT_VERIFY=0
CANDIDATE_UNIT_VERIFY=0
```

Unit-тесты дополнительно подтверждают:

- `User=mikroclear`;
- `Group=mikroclear`;
- обязательный `/etc/mikroclear/mikroclear.env`;
- `WorkingDirectory=/`;
- сохранение hardening directives.

## Forbidden scan и рабочее дерево

Проверены установщик и две новые операторские инструкции:

```bash
grep -En \
  '/etc/mikrocata/certs|/home/mgm/\.ssh|mcp-selks|MCP' \
  scripts/install-selks.sh \
  docs/ru/install-from-github.md \
  docs/ru/install-test-reproduction.md

grep -En \
  'pip install.*requirements|pip install -r|git (pull|fetch|checkout|switch)' \
  scripts/install-selks.sh

git diff --check
git status --short
```

Результат: оба поиска не нашли совпадений; `git diff --check` завершился с
exit code `0`; перед созданием этого отчёта рабочее дерево было чистым.

## Что не запускалось

| Проверка | Статус | Причина |
|---|---|---|
| Чистая установка в Debian 12 VM | NOT RUN | отдельная VM не подключена |
| Чистая установка в Debian 13 VM | NOT RUN | локальная машина не является чистым snapshot |
| Полный root-запуск `install-selks.sh` | NOT RUN | не изменяем рабочий хост |
| Production SELKS deploy/restart | NOT RUN | не разрешён и не входит в локальную проверку |
| Живое подключение к RouterOS | NOT RUN | автоматические тесты изолированы от сети |
| Telegram polling и `/status` тестового бота | NOT RUN | тестовый bot/token не предоставлен |
| Failure injection на полном стенде | NOT RUN | безопасно проверен sourceable test double |

Для воспроизведения этих проверок используется
[`docs/ru/install-test-reproduction.md`](../../ru/install-test-reproduction.md).

## Итоговый локальный статус

Локальные автоматические критерии выполнены. Перед production применением
остаются операторские этапы:

1. пройти матрицу на чистых Debian 12 и Debian 13 VM;
2. выполнить clean install с тестовым RouterOS;
3. проверить варианты Telegram выключен/включён и `/status`;
4. воспроизвести успешное обновление и стендовый acceptance failure;
5. только после этого отдельно согласовать production SELKS deploy.
