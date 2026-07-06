# Compatibility shim deprecation

Дата: 2026-07-06.

Этот документ фиксирует текущий статус старых import paths после перехода на
canonical package ownership.

## Canonical paths

Новый production code должен импортировать только canonical modules:

```text
mikroclear.assets.resolver
mikroclear.state.files
mikroclear.state.address_list_store
mikroclear.state.uptime
mikroclear.suricata.alert_logic
mikroclear.suricata.events
mikroclear.suricata.eve_tailer
mikroclear.telegram.formatting
mikroclear.telegram.notify
mikroclear.telegram.polling
mikroclear.telegram.unblock
mikroclear.routeros.client
mikroclear.routeros.ssl_context
mikroclear.routeros.address_list
```

## Deprecated compatibility shims

Эти files остаются import-only wrappers и помечены как deprecated compatibility
shims:

```text
src/mikroclear/asset_resolver.py
src/mikroclear/state_store.py
src/mikroclear/eve_watcher.py
src/mikroclear/telegram_notify.py
src/mikroclear/telegram_polling.py
src/mikroclear/telegram_unblock.py
src/mikroclear/routeros_client.py
src/mikroclear/routeros_tls.py
src/mikroclear/alert_logic.py
src/mikroclear/events.py
```

В shims намеренно не добавлены runtime warnings: эти modules могут быть
импортированы в compatibility tests или emergency rollback context, и warnings
не должны шуметь в production logs.

## Audit result

Проверка:

```bash
rg -n "from mikroclear import (asset_resolver|state_store|eve_watcher|telegram_notify|telegram_polling|telegram_unblock|routeros_client|routeros_tls|alert_logic|events)|import mikroclear\\.(asset_resolver|state_store|eve_watcher|telegram_notify|telegram_polling|telegram_unblock|routeros_client|routeros_tls|alert_logic|events)" src tests docs README.md
```

Текущий допустимый результат:

- production code under `src/mikroclear/` не импортирует deprecated shims;
- совпадения остаются только в tests, которые проверяют compatibility behavior,
  и docs, которые описывают migration/rollback.

## Removal gate

Удалять shims можно только отдельным PR после stable window:

1. SELKS production прошел observation window после удаления legacy env fallback.
2. Rollback plan больше не требует старых Python import paths.
3. `src/mikrocata/*` больше не нужен внешним downstream imports.
4. Compatibility tests заменены на negative/import-removal checks.
5. Full tests и package import checks проходят.
