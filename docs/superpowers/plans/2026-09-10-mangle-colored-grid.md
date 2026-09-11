# Mangle Colored Grid Implementation Plan

**Goal:** Две колонки цветных правил по согласованной спецификации.

**Architecture:** Меняется только builder в `src/mikroclear/bot/mangle_control.py`.
Транспорт сохраняет дополнительные поля кнопок при JSON-сериализации.

**Tech Stack:** Python, unittest, Telegram inline keyboard JSON.

## Выполнение

1. В `tests/test_telegram_mangle_control.py` обновить проверку состояний:
   две кнопки в первой строке, `success`/`danger`, callback disable/enable;
   навигация `primary`. Проверить размеры строк для 0, 1, 2, 3, 5 правил,
   исходный порядок и ровно один вызов token_factory на правило.
2. Запустить `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m
   unittest tests.test_telegram_mangle_control.MangleControlFormattingTests`;
   подтвердить несовпадение сетки/отсутствие style.
3. Формировать список кнопок и строки срезами `buttons[i:i + 2]` при
   `range(0, len(buttons), 2)`. Задать `danger` при disabled, иначе `success`;
   добавить `primary` только в навигационные кнопки Mangle.
4. Повторить целевые тесты, затем `unittest discover -s tests` и
   `git diff --check`. Проверить отсутствие изменений callbacks и handlers.
5. Commit/push и PR с результатами проверок. Production не обновлять.
