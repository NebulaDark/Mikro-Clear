# Завершение PR №4 — 2026-09-10

Ветка `feature/remove-legacy-fallback-and-hardening-plan` объединена с
`main` на `ec64e985a61cee92a7ed2ed35543fb3f86ed45eb` без переписывания истории.

## Результат

- Сохранены актуальные unit и тесты из main: обязательный env-файл,
  `User=mikroclear`, `Group=mikroclear`, `WorkingDirectory=/`, отсутствие
  legacy-путей в sandbox. Эти изменения уже были реализованы после открытия PR.
- Сохранена актуальная инструкция автономной установки и ссылки NebulaDark.
- Десять совместимых Python-обёрток помечены deprecated только в docstring.
  Импорты и экспортируемые объекты сохранены, runtime warnings не добавлены.
- Документы по env и пользователю службы приведены к текущему установщику.
  Устаревшие ручные chown/ACL/root-rollback команды заменены ссылкой на
  поддерживаемую установку и проверками чтения.
- Июльские план и отчёт явно помечены как исторические.

## Проверки

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m mikroclear --help
git diff --check
```

Результат: 499 тестов, OK; CLI help и проверка diff завершились успешно.
Дополнительно Python-файлы проверены через `compile()` без записи bytecode.
Сравнение AST десяти изменённых модулей с main после удаления docstring
подтвердило отсутствие изменений исполняемого кода. Unit, тесты и основная
инструкция установки совпадают с main.

## Границы результата

SELKS, RouterOS и Telegram не изменялись и не проверялись live.
Состояние Bot dry-run и фактическая установленная версия этим PR не
подтверждаются. Удаление Python-обёрток остаётся отдельным будущим изменением
с условиями из `compatibility-shim-deprecation.md`.
