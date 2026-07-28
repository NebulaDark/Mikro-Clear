"""Pure models and builders for Telegram menu navigation."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.settings import BotSettings
from mikroclear.settings import Settings


MENU_PREFIX = "menu:v1:"
LAUNCHER_LABEL = "🛡 Mikro-Clear"


@dataclass(frozen=True)
class MenuView:
    text: str
    reply_markup: dict[str, Any]


@dataclass(frozen=True)
class MenuItem:
    item_id: str
    label: str
    order: int
    permission: str
    module: str
    enabled: Callable[[Settings], bool]


@dataclass(frozen=True)
class MenuRegistry:
    items: tuple[MenuItem, ...]

    def visible(
        self,
        *,
        chat_id: str,
        auth: BotAuth,
        settings: Settings,
        bot_settings: BotSettings,
    ) -> tuple[MenuItem, ...]:
        visible = []
        for item in self.items:
            permitted = (
                auth.can_read(chat_id)
                if item.permission == "read"
                else auth.can_write(chat_id)
            )
            if (
                permitted
                and item.module in bot_settings.modules
                and item.enabled(settings)
            ):
                visible.append(item)
        return tuple(sorted(visible, key=lambda item: (item.order, item.item_id)))


def build_launcher_markup() -> dict[str, Any]:
    return {
        "keyboard": [[{"text": LAUNCHER_LABEL}]],
        "is_persistent": True,
        "resize_keyboard": True,
    }


def parse_menu_callback(data: Any) -> str | None:
    value = str(data or "")
    if not value.startswith(MENU_PREFIX):
        return None
    route = value[len(MENU_PREFIX) :]
    if route in {
        "root",
        "status",
        "status:general",
        "status:mangle",
        "mangle",
        "exceptions",
    }:
        return route
    return route if re.fullmatch(r"exceptions:[0-9]+", route) else None


def default_menu_registry() -> MenuRegistry:
    return MenuRegistry(
        (
            MenuItem(
                "status",
                "📊 Статус",
                10,
                "read",
                "status",
                lambda settings: True,
            ),
            MenuItem(
                "mangle_control",
                "🔀 Mangle",
                20,
                "admin",
                "mangle_control",
                lambda settings: settings.mangle_control_enable,
            ),
            MenuItem(
                "whitelist_control",
                "🛡 Исключения",
                30,
                "admin",
                "whitelist_control",
                lambda settings: settings.telegram_whitelist_control_enable,
            ),
        )
    )


def build_root_view(items: tuple[MenuItem, ...]) -> MenuView:
    routes = {
        "status": "status",
        "mangle_control": "mangle",
        "whitelist_control": "exceptions",
    }
    buttons = [
        {
            "text": item.label,
            "callback_data": f"{MENU_PREFIX}{routes[item.item_id]}",
        }
        for item in items
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    return MenuView("<b>Mikro-Clear</b>", {"inline_keyboard": rows})


def build_status_menu_view(*, show_mangle: bool) -> MenuView:
    rows = [
        [
            {
                "text": "🛡 Общий статус",
                "callback_data": "menu:v1:status:general",
            }
        ],
    ]
    if show_mangle:
        rows.append(
            [{"text": "🔀 Mangle", "callback_data": "menu:v1:status:mangle"}]
        )
    rows.append([{"text": "⬅️ Назад", "callback_data": "menu:v1:root"}])
    return MenuView("<b>Статус</b>", {"inline_keyboard": rows})


__all__ = [
    "LAUNCHER_LABEL",
    "MENU_PREFIX",
    "MenuItem",
    "MenuRegistry",
    "MenuView",
    "build_launcher_markup",
    "build_root_view",
    "build_status_menu_view",
    "default_menu_registry",
    "parse_menu_callback",
]
