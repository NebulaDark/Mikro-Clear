# SELKS: проверка после PR №4 и ошибка Mangle

Дата: 2026-09-10, около 23:12 MSK.

## 1. Слияние

PR №4 слит в main: `b2fae337cd8c59f3aa9bc9fcf7b7a0ccc6712fdf`.
Локальный main синхронизирован; дерево merge-коммита совпало с проверенным
`979ec984775b44ceebeb5c6c80bbc04e6df3d74b`.

## 2. Проверка SELKS без изменений

- `ActiveState=active`, `SubState=running`, `MainPID=597`.
- `NRestarts=0`, `TasksCurrent=2`; повторная выборка дала те же значения.
- Запуск: `2026-08-29 15:56:36 MSK`; в журнале в 15:56:37 есть
  `Telegram polling worker started`.
- `User=mikroclear`, `Group=mikroclear`; обязательный
  `/etc/mikroclear/mikroclear.env`, дополнительных drop-in нет.
- Все 69 установленных Python-файлов пакета побайтно совпадают по SHA-256
  с `f6ac4d2` и `4e96087`. Эти версии имеют одинаковый runtime, поэтому
  по Python-файлам нельзя различить исходный commit установки.
- SHA-256 установленного unit совпадает с main:
  `8a15077009226dfd396e7e834b897bf59271109a41135ac2995e34dbd172a367`.
- `/var/lib/mikroclear`: `mikroclear:mikroclear`, `0700`.
- Через masked-env helper подтверждены `MIKROCLEAR_BOT_DRY_RUN=false`,
  включённые Bot, Telegram, Unblock и whitelist control, canonical state/EVE/CA
  пути. Это значения env-файла; helper runtime-env не выводит BOT_DRY_RUN.
- Полные права env/CA/state-файлов, install-manifest и BOT_DRY_RUN в окружении
  процесса не прочитаны: соответствующие sudo-команды требуют пароль.

В выборке 234 строк журнала были сетевые ошибки Telegram (DNS, 429/502,
timeout, TLS EOF) и RouterOS reconnect при потере сети. Они не привели к
перезапуску текущего процесса, но uptime сам по себе не доказывает исправность
каждой управляющей операции.

## 3. Подтверждённый дефект и подготовленное исправление

10 сентября в 22:52:55, 22:53:03 и 22:53:29 записано:

```text
TELEGRAM MANGLE UPDATE FAILED: TypeError
```

В установленной `librouteros=4.0.1` сигнатура:

```text
Path.update(self, **kwargs)
```

Код передавал ID позиционно: `update(rule.rule_id, disabled=...)`.
Проверка binding сигнатуры на SELKS без вызова RouterOS вернула
`TypeError: too many positional arguments`. Локальный тест с настоящим
`librouteros.api.Path` и записывающим транспортом воспроизвёл TypeError
в той же строке. Существовавшие fake-ресурсы ошибочно принимали ID позиционно.

Исправление передаёт `.id` и `disabled` именованными параметрами. Проверка
принадлежности правила управляемой области, авторизация, dry-run, audit и
одноразовые подтверждения сохранены.

Проверка: новый regression до исправления — TypeError и отсутствие записей;
после исправления — точные `/ip/firewall/mangle/set` вызовы для enable/disable.
Полный запуск `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m
unittest discover -s tests`: 500 тестов, OK. `git diff --check`: OK.

Исправление подготовлено в `fix/mangle-librouteros-update`. На SELKS оно
не установлено. Повторная отправка управляющих команд в Telegram/RouterOS
при проверке не выполнялась.

## 4. Почему удаление обёрток отложено

Stable window для управляющих операций не подтверждено: выявлен дефект Mangle.
Внешние потребители `mikrocata` и зависимость rollback от старых импортов также
не проверены. В репозитории legacy-импорты найдены в compatibility tests и
самих алиасах `src/mikrocata`. Удалять их до закрытия этих условий нельзя.

## Следующая read-only проверка оператором

Выполнить на SELKS с sudo-доступом. Команды не изменяют конфигурацию и не
выводят секретные значения:

```bash
sudo stat -c '%U:%G %a %n' /etc/mikroclear/mikroclear.env /etc/mikroclear/certs/mikrotik-ca.crt
sudo find /var/lib/mikroclear -maxdepth 1 -type f -printf '%u:%g %m %f\n'
sudo cat /var/lib/mikroclear/install-manifest
sudo python3 - <<'PY'
import pathlib, subprocess
pid = subprocess.check_output(['systemctl', 'show', '-p', 'MainPID', '--value', 'mikroclear.service'], text=True).strip()
allowed = {'MIKROCLEAR_BOT_DRY_RUN', 'MIKROCLEAR_STATE_DIR', 'MIKROCLEAR_EVE_JSON', 'MIKROCLEAR_CA_FILE'}
entries = pathlib.Path('/proc', pid, 'environ').read_bytes().split(b'\0')
values = dict(entry.decode().split('=', 1) for entry in entries if b'=' in entry)
for key in sorted(allowed):
    print(key + '=' + values.get(key, '<unset>'))
PY
```

После получения вывода — проверить резервную копию, выбрать точный commit
исправления и согласовать deploy через `scripts/install-selks.sh` по
[инструкции установки](install-from-github.md). Исправление включает реальные
Mangle writes при `BOT_DRY_RUN=false`; перед live-проверкой оператор выбирает
допустимое тестовое правило и фиксирует его исходное состояние.
