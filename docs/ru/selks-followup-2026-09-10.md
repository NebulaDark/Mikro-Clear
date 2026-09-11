# SELKS: проверка после PR №4 и ошибка Mangle

Дата: 2026-09-10, около 23:12 MSK.

> Разделы 1–4 и операторский блок ниже описывают исходную проверку до deploy.
> Результат обновления и функциональной проверки приведён в последнем разделе.

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

## Результат обновления и проверки Work-PC

PR №5 слит в main: `145f6afe6dcd937abb55febbb940d6d9d7b33aca`.
После отдельного согласования оператор запустил установщик на SELKS из
проверенного commit `3483e0887e0f289d99a0c1ec245d322aeaf200c5`.

Подтверждено выводом root-консоли:

- До обновления env и CA имели `root:mikroclear 0640`; показанные state-файлы
  — `mikroclear:mikroclear 0600`.
- В окружении запущенного процесса были `MIKROCLEAR_BOT_DRY_RUN=false` и
  canonical state/EVE/CA пути.
- `INSTALLER_EXIT=0`.
- Manifest: `status=active`, commit `3483e0887e0f289d99a0c1ec245d322aeaf200c5`,
  Python 3.11.2, `installed_at=2026-09-10T20:25:46Z`.
- SHA-256 wheel:
  `4d3a6e83474e170e9b233f930542394b3a46b27abcef6982f0b75e22b42cd45f`.

Независимая read-only проверка после установки:

- SHA-256 установленного `routeros/mangle.py` совпал с исправленным исходником:
  `9c7707699fc5cce2d5e8e1d265167e920eb45ef441e7a6dd37f5fdddb207f7ba`.
- Новый процесс `MainPID=1588288` запущен в `2026-09-10 23:25:44 MSK`.
- В 23:25:45 записаны `Connected to MikroTik` и
  `Telegram polling worker started`.
- `active/running`, `NRestarts=0`, `TasksCurrent=2`; эти значения сохранились
  при повторной проверке после пользовательского теста.

Оператор выбрал правило Work-PC и после инструкции переключить его через
Telegram и вернуть исходное состояние сообщил: «проверил, работает».
Это пользовательское подтверждение функциональной проверки; отдельное чтение
итогового состояния правила из RouterOS не выполнялось.

В последних 100 строках журнала, отфильтрованных по текущему PID, после теста
не найдены `MANGLE UPDATE FAILED`, `Traceback`, `Permission denied` или
`TelegramWorkerFatalError`. Это ограниченная выборка, а не длительное окно
наблюдения.

Исправление Mangle установлено и проверено. Перед удалением compatibility
shims остаются условия из `compatibility-shim-deprecation.md`: стабильное
наблюдение, проверка внешних потребителей и независимости rollback от старых
импортов. Этот deploy сам по себе не разрешает удаление этих путей.

## Восстановление address-list после перезагрузки RouterOS

Ранее восстановление сохранённых списков было привязано к обработке alert и
интервалу сохранения. Поэтому после перезагрузки RouterOS, если новых alert не
было, `add_saved_lists()` не вызывался. Запись `Router reboot detected` могла
появиться только позднее.

Исправление в следующем изменении вызывает отдельную проверку uptime и
восстановление сразу после успешного startup/heartbeat RouterOS. Периодическое
сохранение списка остаётся в прежнем интервале и не выполняется на каждом
цикле. При следующем согласованном deploy нужно проверить reboot RouterOS и
сверить `Suricata` с `savelists-tzsp0.json`.
