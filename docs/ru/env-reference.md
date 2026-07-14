# Справочник `.env` Mikro-Clear

Основной файл конфигурации на SELKS:

```text
/etc/mikroclear/mikroclear.env
```

Пример в репозитории:

```text
config/mikroclear.env.example
```

`MIKROCLEAR_*` - основной современный префикс. `MIKROCATA_*` поддерживается
только как legacy fallback внутри config layer. Если заданы оба варианта одной
переменной, `MIKROCLEAR_*` имеет приоритет.

Не хранить реальные пароли и Telegram token в git.

## Формат значений

Boolean:

```text
true, yes, y, on, 1
false, no, off, 0 или пустое значение
```

CSV-списки:

```text
value1,value2,value3
```

Также поддерживаются `;` и переносы строк, но для `.env` рекомендуется запятая.

## RouterOS

`MIKROCLEAR_ROUTER_USERNAME`
: Пользователь RouterOS API. Нужен для подключения к MikroTik.

`MIKROCLEAR_ROUTER_PASSWORD`
: Пароль RouterOS API. Секрет. Не коммитить.

`MIKROCLEAR_ROUTER_IP`
: Адрес MikroTik RouterOS API. Значение по умолчанию соответствует текущему SELKS
профилю.

`MIKROCLEAR_USE_SSL`
: Включает RouterOS API-SSL. Рекомендуемое значение: `true`.

`MIKROCLEAR_ROUTER_PORT`
: Порт RouterOS API. Обычно `8729` для SSL и `8728` без SSL.

`MIKROCLEAR_ALLOW_SELF_SIGNED_CERTS`
: Разрешает небезопасный режим TLS для самоподписанных сертификатов. Использовать
только как временный аварийный режим.

`MIKROCLEAR_CA_FILE`
: Путь к CA certificate для проверки RouterOS API-SSL.

`MIKROCLEAR_ROUTER_TLS_SERVER_NAME`
: Имя или IP для проверки certificate SAN/CN при TLS. Должно совпадать с
сертификатом RouterOS.

`MIKROCLEAR_ROUTER_CONNECT_RETRY_SECONDS`
: Пауза между повторными попытками первичного подключения к RouterOS.

`MIKROCLEAR_SOCKET_TIMEOUT_SECONDS`
: Timeout сетевых операций RouterOS API.

`MIKROCLEAR_ROUTER_HEARTBEAT_SECONDS`
: Интервал heartbeat-проверки RouterOS соединения.

`MIKROCLEAR_ROUTER_RECONNECT_SLEEP_SECONDS`
: Пауза перед reconnect после ошибки RouterOS API.

`MIKROCLEAR_ROUTER_CONNECT_NOTIFY_ENABLE`
: Отправлять ли Telegram system notification при подключении к RouterOS.

## RouterOS Address List

`MIKROCLEAR_BLOCK_LIST_NAME`
: Имя RouterOS address-list, куда Mikro-Clear добавляет IP из Suricata alerts.

`MIKROCLEAR_BLOCK_TIMEOUT`
: Timeout записи в address-list, например `1d`, `30d`, `1h`.

`MIKROCLEAR_MONITOR_ONLY`
: Если `true`, Mikro-Clear анализирует события и уведомляет, но не добавляет IP в
RouterOS address-list.

## Telegram

`MIKROCLEAR_TELEGRAM_ENABLE`
: Включает Telegram уведомления и polling.

`MIKROCLEAR_TELEGRAM_TOKEN`
: Telegram Bot API token. Секрет. Не коммитить и не выводить в логи без
маскировки.

`MIKROCLEAR_TELEGRAM_CHATID`
: Chat ID для alert/system notifications.

`MIKROCLEAR_TELEGRAM_TIMEOUT`
: Timeout HTTP-запросов к Telegram API.

`MIKROCLEAR_TELEGRAM_COOLDOWN_SECONDS`
: Минимальная пауза между alert-сообщениями, чтобы не упереться в Telegram rate
limits.

`MIKROCLEAR_TELEGRAM_SYSTEM_COOLDOWN_SECONDS`
: Cooldown для системных уведомлений.

`MIKROCLEAR_TELEGRAM_UNBLOCK_ENABLE`
: Добавляет inline-кнопку unblock в сообщения `BLOCKED` и `UPDATED`.

`MIKROCLEAR_TELEGRAM_UNBLOCK_TTL_SECONDS`
: Время жизни token для inline unblock action.

`MIKROCLEAR_TELEGRAM_UPDATES_INTERVAL_SECONDS`
: Устаревший интервал polling, сохраненный для совместимости. Сетевой worker
  использует long polling и не зависит от этого значения.

`MIKROCLEAR_TELEGRAM_LONG_POLL_SECONDS`
: Timeout long-poll запроса `getUpdates`. По умолчанию `25`; HTTP timeout
  автоматически увеличивается еще на 5 секунд.

`MIKROCLEAR_TELEGRAM_LOCK_FILE`
: Файл локального rate-limit lock.

`MIKROCLEAR_TELEGRAM_UNBLOCK_STATE_FILE`
: Файл состояния короткоживущих unblock tokens.

## Telegram Bot Control Plane

`MIKROCLEAR_BOT_ENABLE`
: Включает обработку bot-команд в Telegram polling.

`MIKROCLEAR_BOT_DRY_RUN`
: Если `true`, write-capable bot modules должны работать в dry-run режиме.

`MIKROCLEAR_BOT_ADMIN_CHAT_IDS`
: CSV-список chat IDs с admin-доступом.

`MIKROCLEAR_BOT_ALLOWED_CHAT_IDS`
: CSV-список chat IDs с read-only доступом.

`MIKROCLEAR_BOT_MODULES`
: CSV-список включенных bot modules. Сейчас реализованный production-safe модуль:
`status`.

`MIKROCLEAR_BOT_AUDIT_LOG`
: Путь к audit log для Telegram control-plane действий.

## Telegram Mangle Control

`MIKROCLEAR_MANGLE_CONTROL_ENABLE`
: Включает команду `/mangle`. По умолчанию `false`.

`MIKROCLEAR_MANGLE_COMMENT_PREFIX`
: Prefix комментария RouterOS mangle rules, которые Mikro-Clear имеет право
показывать и переключать. По умолчанию `MC:`.

`MIKROCLEAR_MANGLE_ALLOWED_CHAINS`
: CSV allowlist chain для управляемых rules. По умолчанию `prerouting`.

`MIKROCLEAR_MANGLE_ALLOWED_ACTIONS`
: CSV allowlist action для управляемых rules. По умолчанию `mark-routing`.

`MIKROCLEAR_MANGLE_REQUIRE_CONFIRMATION`
: Требовать подтверждение перед изменением `disabled`. По умолчанию `true`.
Текущий Telegram workflow всегда использует подтверждение.

## Local Network And Whitelist

`MIKROCLEAR_WAN_IP`
: Публичный WAN IP, который не должен блокироваться как локальный asset.

`MIKROCLEAR_LOCAL_IP_PREFIX`
: Локальная подсеть, добавляемая в whitelist/default local matching.

`MIKROCLEAR_WHITELIST_IPS`
: CSV-список IP/CIDR/prefix, которые нельзя блокировать. Используется при выборе
target IP.

`MIKROCLEAR_ENABLE_IPV6`
: Включает сохранение/обработку IPv6 address-list state.

## Suricata Filtering

`MIKROCLEAR_SEVERITY`
: CSV-список severity, которые обрабатываются. По умолчанию `1,2`.

`MIKROCLEAR_LISTEN_INTERFACES`
: CSV-список интерфейсов Suricata/TZSP, которые считаются релевантными.

`MIKROCLEAR_ADD_ON_START`
: Если `true`, pipeline может обработать накопленные alert events при старте.

`MIKROCLEAR_DEBUG`
: Включает подробный debug logging.

`MIKROCLEAR_COMMENT_TIME_FORMAT`
: Формат timestamp в comment для RouterOS address-list entries.

## Suricata Paths

`MIKROCLEAR_SURICATA_LOG_DIR`
: Каталог Suricata logs.

`MIKROCLEAR_EVE_JSON`
: Полный путь к `eve.json`.

## State Files

`MIKROCLEAR_STATE_DIR`
: Основной каталог state. Целевой путь на SELKS: `/var/lib/mikroclear`.

`MIKROCLEAR_SAVE_LISTS_LOCATION`
: JSON-файл сохранения RouterOS IPv4 address-list state.

`MIKROCLEAR_SAVE_LISTS_LOCATION_V6`
: JSON-файл сохранения RouterOS IPv6 address-list state.

`MIKROCLEAR_UPTIME_BOOKMARK`
: Bookmark-файл uptime, чтобы не переобрабатывать старые события после restart.

`MIKROCLEAR_IGNORE_LIST_LOCATION`
: Файл ignore rules.

`MIKROCLEAR_SAVE_LISTS`
: CSV-список address-lists, которые сохраняются/восстанавливаются.

`MIKROCLEAR_SAVE_INTERVAL`
: Интервал сохранения RouterOS address-list state.

## Asset Resolver

`MIKROCLEAR_ASSET_RESOLVER_ENABLE`
: Включает enrichment alert-сообщений asset-name данными.

`MIKROCLEAR_ASSET_RESOLVER_PRIVATE_ONLY`
: Выполнять resolver только для private/local IP.

`MIKROCLEAR_ASSET_RESOLVER_DHCP_ENABLE`
: Использовать RouterOS DHCP leases для имени устройства.

`MIKROCLEAR_ASSET_RESOLVER_PTR_ENABLE`
: Использовать PTR lookup.

`MIKROCLEAR_ASSET_RESOLVER_CACHE_TTL`
: TTL cache resolver-а в секундах.

## Минимальный `.env`

```env
MIKROCLEAR_ROUTER_USERNAME=mikroclear-api
MIKROCLEAR_ROUTER_PASSWORD=
MIKROCLEAR_ROUTER_IP=192.168.10.1
MIKROCLEAR_USE_SSL=true
MIKROCLEAR_ROUTER_PORT=8729
MIKROCLEAR_CA_FILE=/etc/mikrocata/certs/mikrotik-ca.crt
MIKROCLEAR_ROUTER_TLS_SERVER_NAME=192.168.10.1

MIKROCLEAR_BLOCK_LIST_NAME=Suricata
MIKROCLEAR_BLOCK_TIMEOUT=30d
MIKROCLEAR_MONITOR_ONLY=false

MIKROCLEAR_TELEGRAM_ENABLE=false
MIKROCLEAR_TELEGRAM_TOKEN=
MIKROCLEAR_TELEGRAM_CHATID=

MIKROCLEAR_SURICATA_LOG_DIR=/opt/SELKS/docker/containers-data/suricata/logs/
MIKROCLEAR_EVE_JSON=/opt/SELKS/docker/containers-data/suricata/logs/eve.json
MIKROCLEAR_STATE_DIR=/var/lib/mikroclear

MIKROCLEAR_SEVERITY=1,2
MIKROCLEAR_LISTEN_INTERFACES=tzsp0
```

## Миграция с legacy env

Если есть старый файл:

```text
/etc/mikrocata/mikrocataTZSP0.env
```

создать новый:

```bash
sudo install -d -o root -g root -m 700 /etc/mikroclear /var/lib/mikroclear
sudo cp -a /etc/mikrocata/mikrocataTZSP0.env /etc/mikroclear/mikroclear.env
sudo sed -i 's/^MIKROCATA_/MIKROCLEAR_/' /etc/mikroclear/mikroclear.env
sudo sed -i 's#^MIKROCLEAR_STATE_DIR=.*#MIKROCLEAR_STATE_DIR="/var/lib/mikroclear"#' /etc/mikroclear/mikroclear.env
sudo chmod 600 /etc/mikroclear/mikroclear.env
```

После изменения:

```bash
sudo systemctl restart mikroclear.service
sudo systemctl status mikroclear.service --no-pager --lines=25
```
