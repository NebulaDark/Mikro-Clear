"""Pure Telegram managed-exceptions menu rendering."""

from __future__ import annotations

from math import ceil
from typing import Callable, Iterable

from mikroclear.bot.menu import MenuView


def build_exceptions_view(
    system_entries: Iterable[str],
    managed_entries: Iterable[str],
    *,
    page: int,
    page_size: int = 8,
    remove_token_factory: Callable[[str], str],
) -> MenuView:
    """Render one deterministic page across system and managed entries."""

    if type(page_size) is not int or page_size <= 0:
        raise ValueError("exceptions page size must be positive")

    system = tuple(sorted(dict.fromkeys(str(value) for value in system_entries)))
    managed = tuple(sorted(dict.fromkeys(str(value) for value in managed_entries)))
    rows = tuple(("system", value) for value in system) + tuple(
        ("managed", value) for value in managed
    )
    page_count = max(1, ceil(len(rows) / page_size))
    current_page = min(max(0, int(page)), page_count - 1)
    start = current_page * page_size
    visible = rows[start : start + page_size]

    lines = ["<b>Исключения</b>"]
    visible_system = tuple(
        value for entry_type, value in visible if entry_type == "system"
    )
    visible_managed = tuple(
        value for entry_type, value in visible if entry_type == "managed"
    )
    if visible_system:
        lines.extend(
            (
                "",
                "Системные — только просмотр:",
                *(f"🔒 {value}" for value in visible_system),
            )
        )
    if visible_managed:
        lines.extend(
            (
                "",
                "Добавлены через Telegram:",
                *(f"🛡 {value}" for value in visible_managed),
            )
        )
    if not visible:
        lines.extend(("", "Список исключений пуст."))

    keyboard = [
        [
            {
                "text": f"🗑 {address}",
                "callback_data": (
                    "whitelist:v1:remove-request:"
                    f"{remove_token_factory(address)}"
                ),
            }
        ]
        for address in visible_managed
    ]
    navigation = []
    if current_page > 0:
        navigation.append(
            {
                "text": "⬅️",
                "callback_data": f"menu:v1:exceptions:{current_page - 1}",
            }
        )
    if current_page + 1 < page_count:
        navigation.append(
            {
                "text": "➡️",
                "callback_data": f"menu:v1:exceptions:{current_page + 1}",
            }
        )
    if navigation:
        keyboard.append(navigation)
    keyboard.extend(
        (
            [
                {
                    "text": "🔄 Обновить",
                    "callback_data": f"menu:v1:exceptions:{current_page}",
                }
            ],
            [{"text": "⬅️ Назад", "callback_data": "menu:v1:root"}],
        )
    )
    return MenuView("\n".join(lines), {"inline_keyboard": keyboard})


__all__ = ["build_exceptions_view"]
