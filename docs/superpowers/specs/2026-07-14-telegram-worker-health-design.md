# Telegram Polling Worker Health Design

Дата: 2026-07-14

Статус: утвержден вариант 1

## Контекст

При staged deploy коммита `5e01be5` SELKS загрузил новые runtime-модули, но
процесс `mikroclear.service` оставался с одним thread. Самостоятельный запуск
`TelegramPollingWorker` на том же хосте создавал thread успешно. Поскольку
systemd продолжал показывать `active/running`, состояние без Telegram consumer
не было обнаружено автоматически. Deploy был откатан к `43cbf17`.

## Цель

Сервис не должен оставаться в ложноположительном состоянии `active`, если
Telegram polling worker не запустился или завершился до штатного shutdown.
Причина завершения должна быть видна в журнале без bot token и Telegram
payload.

## Решение

`TelegramPollingWorker` получает явный lifecycle contract:

- `start()` записывает событие успешного запуска с именем worker, но без
  конфигурационных секретов;
- верхняя граница worker thread перехватывает неожиданное исключение,
  сохраняет sanitized fatal error и записывает его в журнал;
- штатный `stop()` помечает остановку как ожидаемую и не создаёт fatal state;
- `check_health()` ничего не делает до запуска и после штатной остановки, но
  выбрасывает отдельный `TelegramWorkerFatalError` с sanitized причиной, если
  запущенный worker умер;
- worker не перезапускает себя внутри процесса, чтобы не скрывать повторяемую
  ошибку и не создавать несколько consumers.

`MikroClearService.run_once()` вызывает `check_health()` перед обработкой
готовых updates. `run()` обрабатывает `TelegramWorkerFatalError` отдельно от
существующего generic transient exception path: сервис журналирует ошибку,
выполняет обычный `shutdown()` и возвращает код `1`. Unit с
`Restart=on-failure` после этого выполняет контролируемый restart. Остальные
ошибки main loop по-прежнему журналируются и повторяются после текущей
пятисекундной паузы.

Для этого runtime dependency `check_telegram_worker` передаётся из wiring рядом
с `start_telegram_worker` и `stop_telegram_worker`. Existing update ordering,
retry delays, acknowledgement и RouterOS main-thread boundary не меняются.

## Ошибки и журнал

- Fatal exception маскируется через существующий `sanitize_exception_text`.
- Журнал содержит тип исключения и sanitized message, но не update body,
  callback data или Telegram token.
- Ошибка запуска `Thread.start()` остаётся синхронной startup-ошибкой и также
  приводит к неуспешному завершению сервиса.
- Повторный health check возвращает ту же сохранённую причину до shutdown.

## Тестирование

TDD regression cases:

- неожиданное исключение из `fetch_updates()` завершает worker и становится
  доступно через `check_health()`;
- token в fatal exception маскируется;
- пустой успешный polling сохраняет живой worker;
- `check_health()` не ошибается до `start()` и после штатного `stop()`;
- runtime вызывает health check в каждом `run_once`;
- `TelegramWorkerFatalError` приводит к shutdown и результату `run() == 1`,
  тогда как generic main-loop exception сохраняет прежний retry path;
- wiring передаёт health method того же worker instance.

После focused tests выполняются полный `unittest discover`, `compileall`,
`git diff --check` и secret scan. Production acceptance требует двух threads
для `mikroclear.service`, marker запуска worker, `active/running`,
`NRestarts=0` после периода наблюдения и отсутствия fatal traceback.

## Deploy Boundary

Повторный deploy выполняется wheel-артефактом из committed HEAD с SHA-256,
backup и rollback wheel. Helper и sudoers устанавливаются отдельно только через
root; отсутствие этих файлов не маскируется как полный deploy.

## Критерии приёмки

- `active/running` больше не может сохраняться после необработанной смерти
  polling worker.
- Не возникает второй одновременный Telegram consumer внутри процесса.
- Fatal diagnostics не раскрывают token или Telegram payload.
- Runtime и worker regression tests проходят без live Telegram/RouterOS calls.
- Повторный SELKS deploy либо подтверждает живой worker, либо автоматически
  откатывается к подтверждённому rollback wheel.
