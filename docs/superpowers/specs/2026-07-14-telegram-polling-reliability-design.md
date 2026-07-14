# Telegram Polling Reliability Design

Дата: 2026-07-14

Статус: утвержден средний вариант

## Цель

Исправить пункты 2-4 из code review инцидента Telegram-бота:

- не терять Telegram update при временной ошибке обработки или отправки ответа;
- отделить read-only диагностику от изменения `allowed_updates`;
- проверять фактический production-код и bot identity до замены бота;
- перейти с short polling на long polling без параллельного доступа к RouterOS.

Сокращение SELKS sudo/deploy-прав относится к отдельному пункту 1 и в эту
работу не входит.

## Ограничения

- Существующие команды deploy, restart и sudo не удаляются и не сужаются.
- Production SELKS не изменяется и сервис не перезапускается в рамках локальной
  реализации.
- Тесты не обращаются к реальным Telegram API и RouterOS.
- Telegram-команды и callback handlers продолжают выполняться последовательно
  в основном runtime-потоке.
- Текущие auth, admin allowlist, dry-run и audit semantics сохраняются.

## Архитектура

### Сетевой polling worker

Отдельный worker выполняет только `getUpdates` с положительным long-poll
timeout. Он не вызывает command, mangle или unblock handlers и поэтому не
создает конкурентный доступ к общему RouterOS client.

Полученный update передается в основной runtime-поток через очередь размером 1.
Worker не выполняет следующий `getUpdates`, пока основной поток не вернет
результат обработки текущего update. Updates из одного Telegram batch
обрабатываются строго по порядку.

Для long polling вводится
`MIKROCLEAR_TELEGRAM_LONG_POLL_SECONDS` с default 25 секунд. HTTP timeout равен
long-poll timeout плюс 5 секунд. Существующая
`MIKROCLEAR_TELEGRAM_UPDATES_INTERVAL_SECONDS` сохраняется для совместимости,
но больше не управляет частотой сетевых запросов.

### Подтверждение update

`update_offset` изменяется только после успешного завершения handler. До этого
worker не отправляет Telegram запрос с большим offset, поэтому update остается
неподтвержденным на стороне Telegram.

Результаты обработки делятся на три класса:

- success: handler завершился, offset можно увеличить;
- retryable failure: network error, HTTP 429 или HTTP 5xx; update получает не
  более 5 попыток с задержками 5, 10, 20 и 40 секунд;
- permanent failure: подтвержденная HTTP 4xx ошибка, кроме 429; ошибка
  журналируется с update ID, после чего update подтверждается, чтобы не
  блокировать очередь навсегда.

Неожиданное исключение handler использует тот же предел в 5 попыток. После
исчерпания попыток журналируется отдельное событие abandoned update без полного
содержимого сообщения. Это делает потерю видимой и не допускает бесконечного
poison-message loop.

Гарантия обработки остается at-least-once: crash после бизнес-действия, но до
ack может привести к повторной доставке. Существующие одноразовые callback
tokens остаются защитой write-операций от повторного исполнения.

### Отправка Telegram responses

Низкоуровневая отправка всегда возвращает типизированный результат и не
выпускает `requests` exception наружу без маскирования token. Результат содержит
`ok`, HTTP status, sanitized response text, `retry_after` и признак
retryability.

Command boundary передает retryable failure в polling lifecycle. Permanent
failure записывается в журнал один раз и считается обработанной командой.
Логирование не должно содержать bot token или полный Telegram update payload.

### Безопасная диагностика

`mikroclear-telegram-getupdates-probe` без аргументов становится read-only:

- читает `getMe` и `getWebhookInfo`;
- печатает SHA-256 fingerprint токена из env-файла;
- при работающем сервисе печатает fingerprint токена из process environment;
- показывает совпадение fingerprints и Telegram bot ID/username;
- не вызывает `getUpdates` и не меняет `allowed_updates`.

Явный режим `--reset-allowed-updates`:

- отказывается работать, пока `mikroclear.service` active;
- вызывает `getUpdates` с `allowed_updates=["message", "callback_query"]`;
- не печатает message text, callback data или token;
- выводит только count, update IDs и update types;
- повторно вызывает `getWebhookInfo` и показывает состояние после reset.

MCP получает отдельный mutation tool с `confirm=False` по умолчанию. Sudoers
сохраняет текущий read-only вызов и добавляет только точную команду helper с
`--reset-allowed-updates`; существующие права не удаляются.

### Проверка production artifact

Новый read-only MCP tool сравнивает локальный
`src/mikroclear/telegram/polling.py` с модулем, реально импортируемым через
`/opt/mikroclear-venv/bin/python`. Результат содержит пути, SHA-256 и diff при
расхождении. Это проверяет не только diagnostic marker, но и точные параметры
`allowed_updates` и offset handling.

Token fingerprints связывают env-файл, runtime process и Telegram `getMe` с
одной identity без раскрытия token. Новая bot identity используется только как
контрольный эксперимент после этих проверок, а не как первичное исправление.

## Runtime Lifecycle

На startup сервис запускает polling worker после инициализации зависимостей.
Каждый `run_once` обрабатывает готовый Telegram update в основном потоке и
возвращает worker outcome. На shutdown сначала останавливается worker, затем
закрываются file notifier и RouterOS client.

Остановка worker ограничена HTTP timeout. Новый сетевой запрос после сигнала
shutdown не начинается.

## Тестирование

Реализация выполняется через TDD. Обязательные regression cases:

- handler exception не увеличивает offset;
- retryable send failure не подтверждает update;
- permanent send failure не блокирует следующие updates;
- второй `getUpdates` не начинается до outcome первого update;
- updates одного batch сохраняют порядок;
- runtime запускает, обслуживает и останавливает worker;
- read-only probe не вызывает `getUpdates`;
- reset отказывается работать при active service;
- reset показывает post-reset state и не выводит payload;
- fingerprints различают config и runtime tokens без раскрытия secret;
- production polling comparison сообщает match и diff;
- MCP reset требует `confirm=True` и использует точную sudoers-команду.

После focused tests выполняются полный `unittest discover`, syntax compilation,
shell syntax check и secret scan существующими средствами проекта.

## Документация

Отчет `docs/ru/telegram-bot-incident-2026-07-14.md` обновляется:

- stop-test помечается как недостаточный без reset-before-send и post-readback;
- Telegram-side root cause остается гипотезой, а не подтвержденным выводом;
- новая bot identity переносится из основного решения в controlled experiment;
- добавляется точная operator sequence для read-only probe и explicit reset.

## Критерии приемки

- Telegram update не подтверждается до успешной или явно permanent обработки.
- Long polling не выполняет RouterOS handlers в отдельном потоке.
- Обычная диагностика не изменяет Telegram subscription state.
- Любая диагностическая mutation требует явного подтверждения и остановленного
  сервиса.
- Production code и token identity проверяются без раскрытия secrets.
- Все локальные тесты проходят без live Telegram/RouterOS traffic.
- Пункт 1 и сокращение текущих SELKS прав не реализуются.
