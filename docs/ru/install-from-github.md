# Установка Mikro-Clear с GitHub

Документ описывает целевой способ установки Mikro-Clear из GitHub на SELKS.
Актуальная production-модель после деплоя 2026-07-06: systemd запускает пакетный
entrypoint:

```text
/opt/mikroclear-venv/bin/python -m mikroclear
```

Проект устанавливается в существующее виртуальное окружение:

```text
/opt/mikroclear-venv
```

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
git clone https://github.com/NebulaDark/Mikro-Clear.git
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

Проверить sha256 на SELKS:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'sha256sum /var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl'
```

Контрольная сумма должна совпадать с локальной.

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

Проверить импорт:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikroclear-venv/bin/python -c "import mikroclear; print(mikroclear.__file__)"'
```

Проверить service factory без запуска runtime-loop:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  '/opt/mikroclear-venv/bin/python -c "import mikroclear.app as app; svc = app.build_service(); print(type(svc).__name__)"'
```

Ожидаемо:

```text
MikroClearService
```

## 7. Перезапустить сервис

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'sudo systemctl restart mikroclear.service && systemctl status mikroclear.service --no-pager --lines=30'
```

Проверить machine-readable status:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'systemctl show mikroclear.service --property=ActiveState,SubState,ExecStart,NRestarts --no-pager'
```

Ожидаемо:

```text
ActiveState=active
SubState=running
NRestarts=0
ExecStart=... /opt/mikroclear-venv/bin/python -m mikroclear ...
```

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

Если новый wheel нужно откатить, установить предыдущий wheel тем же способом:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'sudo /opt/mikroclear-venv/bin/python -m pip install --no-deps --force-reinstall /var/tmp/mikroclear-deploy/<previous-wheel>.whl'
```

Затем:

```bash
ssh -F /home/mgm/.ssh/config -o StrictHostKeyChecking=accept-new selks \
  'sudo systemctl restart mikroclear.service && systemctl status mikroclear.service --no-pager --lines=30'
```

Legacy script rollback сохраняется только как аварийный путь, если systemd unit
явно возвращают на:

```text
/opt/mikroclear-venv/bin/python /usr/local/bin/mikroclear.py
```

Для текущей production-модели целевой rollback - переустановка предыдущего wheel.

## 10. Что не делать

- Не коммитить `.env` с секретами.
- Не хранить Telegram token в README, issues, logs или shell snippets.
- Не менять RouterOS/firewall вручную в ходе package deploy.
- Не переключать `ExecStart`, если текущий package entrypoint уже работает.
- Не запускать runtime-loop локально с production `.env`.
- Не использовать `MIKROCATA_*` как новые имена переменных.
