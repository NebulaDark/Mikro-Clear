# Архитектура Mikro-Clear

Состояние после canonical module ownership и деплоя 2026-07-06.

Runtime-код живет в canonical package modules под `src/mikroclear/`. Старые
top-level compatibility shims удалены. Новый production-код должен импортировать
только canonical modules.

## Entry Points

`src/mikroclear/__main__.py`
: Entrypoint для `python -m mikroclear`.

`src/mikroclear/cli.py`
: CLI/console-script parser. Делегирует запуск в `mikroclear.app.main`.

`src/mikroclear/app.py`
: Тонкая граница приложения: загружает settings, собирает service и возвращает
или запускает `MikroClearService`. Не содержит business logic.

`src/mikroclear/legacy.py`
: Compatibility wrapper для старых script-style вызовов. Делегирует в
`mikroclear.app.main`.

## Config Layer

`src/mikroclear/settings.py`
: Typed runtime settings.

`src/mikroclear/config.py`
: Env adapter. `MIKROCLEAR_*` - primary. `MIKROCATA_*` - только legacy fallback
внутри config layer.

Feature modules получают settings/dependencies через runtime wiring и не должны
читать env напрямую.

## Runtime Composition

`src/mikroclear/runtime/__init__.py`
: `MikroClearService`, `RuntimeConfig`, `RuntimeDependencies`. Отвечает за
service loop, signals, pyinotify, startup/shutdown lifecycle и polling.

`src/mikroclear/runtime/wiring.py`
: Преобразует `Settings` в runtime config/dependencies.

`src/mikroclear/runtime/providers.py`
: Создает конкретные providers: RouterOS client, Telegram notifier/poller,
Suricata pipeline, state stores, asset resolver, debug hooks.

`src/mikroclear/runtime/status_snapshot.py`
: Готовит read-only snapshot для Telegram `/status`.

## RouterOS Block

`src/mikroclear/routeros/client.py`
: RouterOS API lifecycle: connect, reconnect, retry loop, heartbeat, error
handling.

`src/mikroclear/routeros/address_list.py`
: Address-list business operations: select, add, update, remove, restore.
RouterOS write-actions должны проходить через этот слой.

`src/mikroclear/routeros/ssl_context.py`
: TLS/SSL context и проверка endpoint identity.

`src/mikroclear/routeros/tls.py`
: Compatibility import path внутри RouterOS package.

## Suricata Block

`src/mikroclear/suricata/alert_logic.py`
: Pure alert decision logic: выбор target IP, peer IP, port и dedup key.

`src/mikroclear/suricata/events.py`
: Parsing/validation EVE JSON events.

`src/mikroclear/suricata/eve_tailer.py`
: Чтение/tailing `eve.json` и обработка rotation.

`src/mikroclear/suricata/event_handler.py`
: pyinotify adapter.

`src/mikroclear/suricata/ignore_rules.py`
: Загрузка и применение ignore-list.

`src/mikroclear/suricata/pipeline.py`
: Batch orchestration, dedup по calculated target, ignore decisions,
`process_single_alert`.

## Telegram Block

`src/mikroclear/telegram/formatting.py`
: HTML escaping/sanitizing, alert/system message formatting.

`src/mikroclear/telegram/notify.py`
: `sendMessage`, alert/system notifications, reply markup, 429/rate-limit
handling.

`src/mikroclear/telegram/polling.py`
: `getUpdates`, offset handling, callback dispatch, HTTP/network errors,
backoff.

`src/mikroclear/telegram/rate_limit.py`
: Локальный rate-limit lock.

`src/mikroclear/telegram/unblock.py`
: Token state и inline keyboard для unblock.

`src/mikroclear/telegram/unblock_handler.py`
: Callback handler: проверяет token, удаляет IP из RouterOS address-list через
adapter, отвечает `answerCallbackQuery`.

`src/mikroclear/telegram/commands.py`
: Интеграция command dispatch для Telegram control plane.

## Bot Block

`src/mikroclear/bot/settings.py`
: Settings для Telegram control plane.

`src/mikroclear/bot/auth.py`
: Проверки allowed/admin chat IDs.

`src/mikroclear/bot/dispatcher.py`
: Routing команд.

`src/mikroclear/bot/modules/status.py`
: Read-only `/status`.

## State Block

`src/mikroclear/state/files.py`
: Private file/dir helpers и permissions.

`src/mikroclear/state/address_list_store.py`
: Save/restore RouterOS address-list state.

`src/mikroclear/state/uptime.py`
: Uptime bookmark persistence.

## Asset Resolver Block

`src/mikroclear/assets/resolver.py`
: DHCP/PTR asset-name resolution. Cache принадлежит runtime provider instance.

## Compatibility Shims

Оставлены только для старых imports:

- `src/mikroclear/asset_resolver.py`
- `src/mikroclear/state_store.py`
- `src/mikroclear/eve_watcher.py`
- `src/mikroclear/telegram_notify.py`
- `src/mikroclear/telegram_polling.py`
- `src/mikroclear/telegram_unblock.py`
- `src/mikroclear/routeros_client.py`
- `src/mikroclear/routeros_tls.py`
- `src/mikroclear/alert_logic.py`
- `src/mikroclear/events.py`
- `src/mikrocata/*`

`src/mikroclear/legacy_runtime.py` удален. Runtime не должен импортировать его.

## Safety Boundaries

- Import пакета не подключается к RouterOS.
- Import пакета не вызывает Telegram API.
- RouterOS writes идут только через adapter/address-list layer.
- Telegram HTTP calls идут только через notifier/poller runtime providers.
- Tests mock RouterOS и Telegram.
- Секреты не хранятся в git.
