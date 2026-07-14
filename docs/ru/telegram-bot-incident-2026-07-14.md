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
    "url": "",
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

Это исключило `mikroclear.service` как consumer, который "съедает" update раньше
журнала. Сообщение не попадало в Telegram update queue этого token вообще.

5. После ручного reset через direct `getUpdates(...allowed_updates=["message","callback_query"])`
   состояние временно исправлялось, но после reboot/prod reuse снова наблюдался
   откат к:

```json
"allowed_updates": ["callback_query"]
```

## Вывод расследования

На момент фиксации root cause внутри кода Mikro-Clear не подтвержден.

Наиболее вероятная причина:

- Telegram-side state этого bot token/identity меняется вне SELKS;
- в результате обычные `message` updates не доходят до production poller;
- у бота остается только `callback_query` path, поэтому не появляются ни
  `/status` ответы, ни новые inline-кнопки/lock UI.

Что было исключено:

- банальный crash `mikroclear.service`;
- отсутствие runtime bot settings;
- отсутствие production polling diagnostics;
- локальная ошибка `/status` formatter/dispatcher как первичный блокер;
- второй consumer на самом SELKS host
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

### Незакоммиченные изменения рабочего дерева

На момент фиксации в рабочем дереве есть:

1. `src/mikroclear/telegram/commands.py`
   Что изменено:
   - command response теперь проверяет результат `send_message`;
   - при `ok=False` пишется явный лог
     `Failed to send Telegram command response to chat ...`.

2. `tests/test_telegram_command_boundary.py`
   Что изменено:
   - добавлен тест на logging failed command response send.

3. `scripts/install-selks-codex-sudoers.sh`
   Что добавлено:
   - root-side installer для helper scripts и sudoers policy на SELKS.

4. `tests/test_selks_codex_sudoers_installer.py`
   Что добавлено:
   - тест на наличие installer script и ожидаемые target paths.

5. `docs/ru/telegram-bot-incident-2026-07-14.md`
   Что добавлено:
   - этот отчет.

## Предложения

### Рекомендуемый путь

Использовать новую Telegram bot identity, а не продолжать отладку старого бота:

1. создать нового бота у `@BotFather`;
2. вписать новый token в `/etc/mikroclear/mikroclear.env`;
3. перезапустить `mikroclear.service`;
4. отправить новому боту `Start`, затем `/status`;
5. сразу проверить:
   - `getWebhookInfo`;
   - `getUpdates`;
   - journal polling markers.

Причина рекомендации:

- старый bot token/state уже демонстрировал устойчивый откат к
  `allowed_updates=["callback_query"]`;
- этот симптом повторялся даже после reboot и token replacement;
- для production быстрее и надежнее проверить новый bot identity, чем
  продолжать спорить с неочевидным Telegram-side состоянием старого.

### Если продолжать по старому боту

Нужно делать только как Telegram-side investigation:

- перепроверить все внешние consumers этого token вне SELKS;
- исключить другие CI secrets / test hosts / user scripts;
- снять Telegram Bot API state сразу после каждого действия;
- не трактовать отсутствие `/status` как локальный баг Mikro-Clear без
  подтверждения `message update` в `getUpdates`.

## Рекомендуемый commit этой фиксации

```text
Document Telegram bot incident and add SELKS sudoers installer
```
