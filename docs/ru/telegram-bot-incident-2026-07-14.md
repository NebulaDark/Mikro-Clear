# Отчет по инциденту Telegram-бота

Дата: 2026-07-14

## Контекст

На SELKS production бот перестал отвечать на Telegram-команды:

- не приходил ответ на `/status`;
- не появлялись ожидаемые inline-кнопки и "замочек";
- system notifications и alert notifications продолжали работать, то есть
  базовая отправка сообщений в Telegram не была полностью сломана.

Целью расследования было отделить проблемы:

1. runtime/polling Mikro-Clear;
2. bot auth/settings;
3. Telegram Bot API state вне Mikro-Clear;
4. SELKS sudo/operator boundary.

## Что проверено и подтверждено

### 1. Локальный код и тесты

Подтверждено:

- `TelegramUpdatePoller` получает `bot_settings` из runtime wiring один раз,
  а не перечитывает `BotSettings.from_env()` на каждом update.
- Runtime wiring передает единый `bot_settings` в poller.
- Regression test на polling boundary уже есть и проходит.

Дополнительно в этой ветке добавлено:

- логирование неуспешной отправки Telegram command response в
  `src/mikroclear/telegram/commands.py`;
- тест на это поведение в
  `tests/test_telegram_command_boundary.py`.

Проверки:

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests
./.venv/bin/python -m compileall src tests
```

Локальный результат на момент фиксации: `240 tests OK`.

### 2. SELKS sudo access и helper tooling

Для продолжения расследования без ручного operator loop были подготовлены
и добавлены:

- `scripts/install-selks-codex-sudoers.sh`
- `tests/test_selks_codex_sudoers_installer.py`

Скрипт устанавливает:

- `/usr/local/sbin/mikroclear-mask-env`
- `/usr/local/sbin/mikroclear-service-env`
- `/usr/local/sbin/mikroclear-telegram-getupdates-probe`
- `/etc/sudoers.d/mikroclear-mcp-selks`

После установки `mcp-selks` получил достаточно узкий `sudo -n` доступ для:

- `systemctl start/stop/restart/status` для `mikroclear.service`;
- `journalctl -u mikroclear.service -n ... --no-pager`;
- masked read env;
- service-env probe;
- Telegram getUpdates probe.

### 3. SELKS runtime state

Подтверждено read-only/probe checks:

- service запускается как
  `/opt/mikroclear-venv/bin/python -m mikroclear`;
- primary env file:
  `/etc/mikroclear/mikroclear.env`;
- process env включает:
  `MIKROCLEAR_TELEGRAM_CHATID`,
  `MIKROCLEAR_BOT_ALLOWED_CHAT_IDS`,
  `MIKROCLEAR_BOT_ADMIN_CHAT_IDS`,
  `MIKROCLEAR_MANGLE_CONTROL_ENABLE`.

Также подтверждено, что установленный production-файл
`/opt/mikroclear-venv/lib/python3.11/site-packages/mikroclear/telegram/polling.py`
уже содержит новые diagnostics:

- `Telegram updates received: ...`
- `Telegram command update: ...`
- `Telegram callback update: ...`

То есть расследование велось уже на актуальном коде с polling markers.

### 4. Telegram Bot API факты

Ключевые наблюдения:

1. На ранних запусках в journal был:

```text
Error processing Telegram updates; retry in 30s: HTTP 401: {"ok":false,"error_code":401,"description":"Unauthorized"}
```

2. После restart/token churn `getMe` для проверяемого токена мог давать `ok: true`,
   то есть "токен вообще невалиден" не объяснял все симптомы.

3. Прямой probe с SELKS регулярно показывал:

```json
{
  "ok": true,
  "result": {
    "url_configured": false,
    "pending_update_count": 0,
    "allowed_updates": ["callback_query"]
  }
}
```

и:

```json
{"ok": true, "result": []}
```

на `getUpdates`.

4. Во время изолированного stop-test:

- `mikroclear.service` был остановлен;
- в бот отправлялся `/status`;
- direct `getUpdates` с SELKS все равно возвращал пустой `result`.

Этот тест показал, что во время наблюдения update не получил остановленный
`mikroclear.service`. Однако он не доказал Telegram-side root cause: перед
отправкой `/status` не были последовательно подтверждены reset
`allowed_updates=["message","callback_query"]` и post-reset readback.

5. После ручного reset через direct `getUpdates(...allowed_updates=["message","callback_query"])`
   состояние временно исправлялось, но после reboot/prod reuse снова наблюдался
   откат к:

```json
"allowed_updates": ["callback_query"]
```

## Обновление 2026-07-24: подтверждён root cause staged deploy

Два staged deploy пакетного runtime оставляли сервис в состоянии `Tasks=1` без
Telegram worker, хотя SHA установленных модулей совпадали с wheel. Причина
подтверждена отдельным read-only импортом на SELKS:

- unit запускал `/opt/mikroclear-venv/bin/python -m mikroclear`;
- `WorkingDirectory` оставался `/usr/local/bin`;
- в этом каталоге находится legacy `/usr/local/bin/mikroclear.py`;
- Python разрешал `mikroclear` в этот файл без package `__path__`, поэтому
  установленный пакет не исполнялся.

Первый неуспешный deploy `5e01be5` был откатан к `43cbf17`. Повторный deploy
`a3cae62` был автоматически откатан к точному прежнему wheel с SHA-256
`a70e6e9f155d0da0357df5b9a2e54a986296f11af485fc182e138d178ede19bb`.
В репозитории добавлен regression test и unit исправлен на
`WorkingDirectory=/`. Это объясняет ложноположительный результат именно
пакетных deploy; отдельная гипотеза о Telegram `allowed_updates` требует
повторной проверки после успешного запуска пакетного worker.

Исправленный wheel из коммита `27665e6` и unit с `WorkingDirectory=/` были
развёрнуты 2026-07-24. После полного long-poll окна сервис оставался
`active/running`, `NRestarts=0`, `TasksCurrent=2`; импорт разрешался в
`site-packages`, журнал содержал `Telegram polling worker started`, RouterOS
был подключён, а fatal worker error и traceback отсутствовали. Подготовленные
rollback wheel и unit не потребовались.

## Вывод расследования

Для отсутствующего worker при staged deploy root cause подтверждён: legacy
module shadowing из-за рабочего каталога systemd unit.

Для исходного поведения Telegram updates рабочая гипотеза всё ещё требует
контролируемого теста после исправленного deploy:

- Telegram-side state этого bot token/identity меняется вне SELKS;
- в результате обычные `message` updates не доходят до production poller;
- у бота остается только `callback_query` path, поэтому не появляются ни
  `/status` ответы, ни новые inline-кнопки/lock UI.

Конкурирующие Telegram-side объяснения остаются открытыми: неполный reset
subscription state или внешний consumer этого token. Отличие установленного
polling artifact от локального кода исключено сравнением SHA, но ранее этот
artifact не достигал выполнения из-за module shadowing.

Что было исключено:

- банальный crash `mikroclear.service`;
- отсутствие runtime bot settings;
- отсутствие production polling diagnostics;
- локальная ошибка `/status` formatter/dispatcher как первичный блокер;
- второй обнаружимый consumer на самом SELKS host в момент проверки
  (`systemctl list-units` и `ps -ef` показывали только `mikroclear.service`).

## Изменения в текущей ветке

### Уже закоммиченные изменения ветки

Последние релевантные коммиты:

```text
41c9c13 Expand SELKS MCP runtime operations
b6988e9 Add Telegram polling diagnostics
49743bd Remove legacy env fallback from unit and MCP tooling
a030a14 Fix status snapshot bot settings drift
cee0e4f Fix Telegram polling bot settings boundary
9bcbc83 Log Telegram mangle command handling
6cbadbf Report disabled mangle control in Telegram
a015acb Restore mangle allowlist validation
```

Их смысл:

- добавлены Telegram polling diagnostics;
- закрыт дрейф `bot_settings` между runtime wiring и polling/status snapshot;
- расширены SELKS MCP runtime operations;
- обновлены mangle-control diagnostics и disabled reporting.

### Изменения reliability-ветки

В отдельной ветке подготовлены:

- подтверждение update offset только после успешной обработки и доставки
  command response;
- long-polling worker с ограниченной очередью, retry и явным abandon marker;
- read-only Telegram probe по умолчанию без вывода token и payload updates;
- отдельный подтверждаемый reset `allowed_updates`, запрещенный при активном
  `mikroclear.service`;
- read-only MCP-сравнение production polling module с локальным artifact по
  SHA-256 и unified diff.

Существующие SELKS sudo-команды не удалены и не сужены. Развертывание этих
изменений на production в рамках подготовки ветки не выполнялось.

## Предложения

### Безопасная последовательность оператора

Каждый изменяющий production шаг требует отдельного явного подтверждения.

1. Запустить read-only probe и сохранить fingerprints config/runtime token,
   identity из `getMe` и состояние `getWebhookInfo`.
2. Сравнить production polling module с локальным artifact через
   `compare_production_polling`; продолжать тест только при понятном результате.
3. Остановить `mikroclear.service` с явным подтверждением оператора.
4. Запустить подтвержденный reset `allowed_updates`. Helper временно применяет
   runtime mask к unit, снимает его после операции и проверяет post-reset
   состояние до отправки тестового сообщения.
5. Только после успешного readback отправить боту `/status`.
6. Запустить service и проверить polling/update/response markers в journal.
7. Использовать новую bot identity только как контролируемый эксперимент, если
   совпадение artifact и token identity уже подтверждено, а воспроизводимость
   проблемы сохранена.

Helper не снимает mask, существовавший до reset. Если cleanup собственного
runtime mask не удался или процесс был принудительно завершен, выполнить от
root и затем повторить read-only probe:

```bash
/usr/bin/systemctl unmask --runtime mikroclear.service
/usr/bin/rm -f /run/mikroclear-telegram-reset-mask-owned
/usr/bin/systemctl is-enabled mikroclear.service
```

Если update снова не появляется, отдельно проверить внешние consumers token:
CI secrets, test hosts и пользовательские скрипты. Отсутствие ответа `/status`
само по себе не доказывает локальный дефект Mikro-Clear или Telegram-side сбой.
