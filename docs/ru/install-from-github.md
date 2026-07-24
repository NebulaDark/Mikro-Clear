# Установка Mikro-Clear с GitHub

Документ описывает целевой способ установки Mikro-Clear из GitHub на SELKS.
Актуальная production-модель после деплоя 2026-07-06: systemd запускает пакетный
entrypoint:

```text
/opt/mikroclear-venv/bin/python -m mikroclear
WorkingDirectory=/
```

Проект устанавливается в существующее виртуальное окружение:

```text
/opt/mikroclear-venv
```

Нейтральный рабочий каталог обязателен, пока существует
`/usr/local/bin/mikroclear.py`: при `WorkingDirectory=/usr/local/bin` этот
legacy-файл перехватывает имя `mikroclear`, и пакетный entrypoint фактически не
запускается.

## Что делает установка

1. Клонирует репозиторий Mikro-Clear из GitHub.
2. Собирает wheel-артефакт из текущего кода.
3. Загружает wheel на SELKS.
4. Устанавливает wheel в `/opt/mikroclear-venv`.
5. Проверяет импорт пакета.
6. Перезапускает `mikroclear.service`.
7. Проверяет статус и последние логи.

## Предварительные условия

На локальной машине:

- доступ к приватному репозиторию GitHub;
- Python 3.11+;
- SSH-доступ к SELKS через alias `selks`;
- файл `/home/mgm/.ssh/config` содержит подключение к SELKS;
- локальный checkout чистый перед сборкой.

На SELKS:

- существует `/opt/mikroclear-venv`;
- в venv уже доступны runtime-зависимости проекта;
- существует `/etc/mikroclear/mikroclear.env`;
- существует `/var/lib/mikroclear`;
- `mikroclear.service` использует package entrypoint;
- пользователь, выполняющий финальную установку, имеет `sudo`.

Проверка текущего entrypoint:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'systemctl show mikroclear.service --property=ExecStart --no-pager'
```

Ожидаемо:

```text
ExecStart=... /opt/mikroclear-venv/bin/python -m mikroclear ...
```

## 1. Получить код из GitHub

Для чистой установки:

```bash
git clone https://github.com/paveltarasov50-coder/Mikro-Clear.git
cd Mikro-Clear
```

Для проверки конкретной feature-ветки до merge:

```bash
git fetch origin
git checkout feature/canonical-module-ownership
git pull --ff-only
```

Для production deploy после merge использовать только `main`:

```bash
git checkout main
git pull --ff-only
```

## 2. Создать локальное окружение сборки

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements.txt
```

Если зависимости уже установлены, повторная установка не обязательна.

## 3. Проверить код до сборки

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
PYTHONPYCACHEPREFIX=/tmp/mikroclear-pycache git ls-files '*.py' | xargs .venv/bin/python -m py_compile
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -c "import mikroclear.app as app; svc = app.build_service(); print(type(svc).__name__)"
```

Ожидаемо:

```text
OK
MikroClearService
```

Проверка отсутствия runtime-зависимости от retired module:

```bash
grep -R "from mikroclear import legacy_runtime" src tests || true
grep -R "import mikroclear.legacy_runtime" src tests || true
```

Ожидаемо: команды ничего не выводят.

## 4. Собрать wheel

Рекомендуемая команда для этого репозитория:

```bash
rm -rf dist
.venv/bin/python -m pip wheel --no-build-isolation --no-deps -w dist .
```

Проверить артефакт:

```bash
.venv/bin/python scripts/validate_wheel_artifact.py dist/mikro_clear-0.1.0-py3-none-any.whl
sha256sum dist/mikro_clear-0.1.0-py3-none-any.whl
```

Ожидаемо:

```text
wheel ok: dist/mikro_clear-0.1.0-py3-none-any.whl
```

## 5. Подготовить SELKS

Каталог для deploy-артефактов:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'install -d -m 700 /var/tmp/mikroclear-deploy && stat -c "%U:%G %a %n" /var/tmp/mikroclear-deploy'
```

Загрузить wheel:

```bash
scp -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new \
  dist/mikro_clear-0.1.0-py3-none-any.whl \
  selks:/var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl
```

Загрузить unit с пакетным entrypoint:

```bash
scp -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new \
  systemd/mikroclear.service \
  selks:/var/tmp/mikroclear-deploy/mikroclear-codex.service
```

Проверить SHA-256 обоих кандидатов на SELKS и синтаксис unit:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'sha256sum /var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl /var/tmp/mikroclear-deploy/mikroclear-codex.service && systemd-analyze verify /var/tmp/mikroclear-deploy/mikroclear-codex.service'
```

Контрольные суммы должны совпадать с локальными.

До первой мутации сохранить точную копию эффективного unit:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'sudo install -o root -g root -m 600 /etc/systemd/system/mikroclear.service /var/tmp/mikroclear-deploy/mikroclear.service.rollback && sha256sum /etc/systemd/system/mikroclear.service /var/tmp/mikroclear-deploy/mikroclear.service.rollback'
```

Предыдущий проверенный wheel также должен оставаться в
`/var/tmp/mikroclear-deploy` под отдельным именем до завершения acceptance.

## 6. Установить wheel в production venv

Эта команда требует `sudo`, потому что `/opt/mikroclear-venv` принадлежит root:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'sudo /opt/mikroclear-venv/bin/python -m pip install --no-deps --force-reinstall /var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl'
```

Проверить установленный пакет:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikroclear-venv/bin/python -m pip show mikro-clear | sed -n "1,14p"'
```

Проверить импорт из нейтрального рабочего каталога:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'cd / && /opt/mikroclear-venv/bin/python -c "import mikroclear; print(mikroclear.__file__); print(mikroclear.__path__)"'
```

Путь должен указывать в `site-packages`, а `mikroclear.__path__` должен
существовать.

Проверить service factory без запуска runtime-loop:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikroclear-venv/bin/python -c "import mikroclear.app as app; svc = app.build_service(); print(type(svc).__name__)"'
```

Ожидаемо:

```text
MikroClearService
```

## 7. Установить unit и перезапустить сервис

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'sudo install -o root -g root -m 644 /var/tmp/mikroclear-deploy/mikroclear-codex.service /etc/systemd/system/mikroclear.service && sudo systemctl daemon-reload && sudo systemd-analyze verify /etc/systemd/system/mikroclear.service && sudo systemctl restart mikroclear.service && systemctl status mikroclear.service --no-pager --lines=30'
```

Проверить machine-readable status:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'systemctl show mikroclear.service --property=ActiveState,SubState,ExecStart,WorkingDirectory,NRestarts,TasksCurrent --no-pager'
```

Ожидаемо:

```text
ActiveState=active
SubState=running
NRestarts=0
TasksCurrent=2
WorkingDirectory=/
ExecStart=... /opt/mikroclear-venv/bin/python -m mikroclear ...
```

`TasksCurrent` должен быть не меньше `2`. После полного long-poll окна журнал
должен содержать marker запуска Telegram worker и не содержать traceback.

## 8. Проверить логи

Никогда не выводить Telegram token без маскировки.

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'sudo journalctl -u mikroclear.service -n 100 --no-pager | sed -E "s#/bot[0-9]+:[A-Za-z0-9_-]+/#/bot***MASKED***/#g"'
```

Нужно проверить:

- нет `Traceback`;
- нет `NameError`;
- сервис пишет `Starting Mikro-Clear`;
- RouterOS подключение успешно;
- мониторинг `eve.json` поднялся;
- нет необработанных Telegram token в выводе.

## 9. Rollback

Если acceptance не прошёл, восстановить и предыдущий wheel, и точную резервную
копию unit:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'sudo /opt/mikroclear-venv/bin/python -m pip install --no-deps --force-reinstall /var/tmp/mikroclear-deploy/<previous-wheel>.whl && sudo install -o root -g root -m 644 /var/tmp/mikroclear-deploy/mikroclear.service.rollback /etc/systemd/system/mikroclear.service && sudo systemctl daemon-reload && sudo systemd-analyze verify /etc/systemd/system/mikroclear.service'
```

Затем:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'sudo systemctl restart mikroclear.service && systemctl show mikroclear.service --property=ActiveState,SubState,WorkingDirectory,NRestarts,TasksCurrent --no-pager && sha256sum /etc/systemd/system/mikroclear.service'
```

Legacy script rollback сохраняется только как аварийный путь, если systemd unit
явно возвращают на:

```text
/opt/mikroclear-venv/bin/python /usr/local/bin/mikroclear.py
```

Для текущей production-модели целевой rollback всегда восстанавливает оба
изменяемых артефакта: предыдущий wheel и предыдущий unit.

## 10. Что не делать

- Не коммитить `.env` с секретами.
- Не хранить Telegram token в README, issues, logs или shell snippets.
- Не менять RouterOS/firewall вручную в ходе package deploy.
- Не переключать `ExecStart`, если текущий package entrypoint уже работает.
- Не использовать `WorkingDirectory=/usr/local/bin` с пакетным entrypoint.
- Не запускать runtime-loop локально с production `.env`.
- Не использовать `MIKROCATA_*` как новые имена переменных.
