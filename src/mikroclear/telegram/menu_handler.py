"""Telegram boundary for persistent launcher and hierarchical menu navigation."""

from __future__ import annotations

from typing import Any, Callable, Protocol

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.gates import bot_module_enabled
from mikroclear.bot.menu import (
    LAUNCHER_LABEL,
    MenuItem,
    MenuRegistry,
    MenuView,
    build_launcher_markup,
    build_root_view,
    build_status_menu_view,
    default_menu_registry,
    parse_menu_callback,
)
from mikroclear.bot.modules.status import format_status
from mikroclear.bot.settings import BotSettings
from mikroclear.telegram.commands import raise_for_retryable_delivery


class MangleMenuAdapter(Protocol):
    def status_view(self) -> MenuView:
        raise NotImplementedError

    def control_view(
        self,
        *,
        chat_id: str,
        user_id: str,
        update_id: str = "",
    ) -> MenuView:
        raise NotImplementedError


class WhitelistMenuAdapter(Protocol):
    def menu_view(
        self,
        *,
        page: int,
        chat_id: str,
        user_id: str,
        now: int,
    ) -> MenuView:
        raise NotImplementedError


class TelegramMenuHandler:
    def __init__(
        self,
        settings: Any,
        *,
        bot_settings: BotSettings,
        status_snapshot_factory: Callable[[], Any],
        mangle_handler: MangleMenuAdapter | None = None,
        whitelist_handler: WhitelistMenuAdapter | None = None,
        registry: MenuRegistry | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.bot_settings = bot_settings
        self.status_snapshot_factory = status_snapshot_factory
        self.mangle_handler = mangle_handler
        self.whitelist_handler = whitelist_handler
        self.registry = registry or default_menu_registry()
        self.log = log or (lambda _message: None)

    def handle_message(
        self,
        *,
        text: Any,
        chat_id: str,
        user_id: str,
        auth: BotAuth,
        send_message: Callable[..., Any],
        token: str,
        timeout: int,
        update_id: str = "",
    ) -> bool:
        value = str(text or "").strip()
        command = _command_name(value)
        if command not in {"/start", "/menu"} and value != LAUNCHER_LABEL:
            return False
        if not auth.can_read(chat_id):
            self.log(
                f"Rejected Telegram menu request from unauthorized chat {chat_id}"
            )
            return True
        if not self.bot_settings.enable:
            return True

        if command in {"/start", "/menu"}:
            view = MenuView("<b>Mikro-Clear</b>", build_launcher_markup())
        else:
            view = self._root_view(chat_id=chat_id, auth=auth)
        self._send_view(
            view,
            send_message=send_message,
            token=token,
            chat_id=chat_id,
            timeout=timeout,
        )
        return True

    def handle_callback(
        self,
        *,
        callback: dict[str, Any],
        auth: BotAuth,
        answer_callback: Callable[[str, str, bool], Any],
        send_message: Callable[..., Any],
        edit_message: Callable[..., Any],
        telegram_token: str,
        timeout: int,
        now: int,
    ) -> bool:
        route = parse_menu_callback(callback.get("data"))
        if route is None:
            return False

        callback_id = str(callback.get("id", ""))
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        user = callback.get("from") or {}
        user_id = str(user.get("id", ""))

        requires_write = route == "mangle" or route.startswith("exceptions")
        authorized = (
            auth.can_write(chat_id) if requires_write else auth.can_read(chat_id)
        )
        if not authorized:
            answer_callback(callback_id, "Unauthorized", True)
            self.log(
                f"Rejected Telegram menu callback from unauthorized chat {chat_id}"
            )
            return True

        if not self._route_available(route):
            answer_callback(callback_id, "Функция недоступна", True)
            return True

        answer_callback(callback_id, "", False)
        view = self._view_for_route(
            route,
            chat_id=chat_id,
            user_id=user_id,
            auth=auth,
            now=now,
        )
        self._edit_or_send_view(
            view,
            message_id=message.get("message_id"),
            edit_message=edit_message,
            send_message=send_message,
            token=telegram_token,
            chat_id=chat_id,
            timeout=timeout,
        )
        return True

    def _available_items(
        self,
        *,
        chat_id: str,
        auth: BotAuth,
    ) -> tuple[MenuItem, ...]:
        visible = self.registry.visible(
            chat_id=chat_id,
            auth=auth,
            settings=self.settings,
            bot_settings=self.bot_settings,
        )
        return tuple(
            item
            for item in visible
            if not (
                item.item_id == "mangle_control"
                and self.mangle_handler is None
            )
            and not (
                item.item_id == "whitelist_control"
                and self.whitelist_handler is None
            )
        )

    def _root_view(self, *, chat_id: str, auth: BotAuth) -> MenuView:
        return build_root_view(
            self._available_items(chat_id=chat_id, auth=auth)
        )

    def _mangle_available(self) -> bool:
        return bool(
            self.mangle_handler is not None
            and bot_module_enabled(
                self.bot_settings,
                "mangle_control",
                feature_enabled=bool(self.settings.mangle_control_enable),
            )
        )

    def _whitelist_available(self) -> bool:
        return bool(
            self.whitelist_handler is not None
            and bot_module_enabled(
                self.bot_settings,
                "whitelist_control",
                feature_enabled=bool(
                    self.settings.telegram_whitelist_control_enable
                ),
            )
        )

    def _route_available(self, route: str) -> bool:
        if not self.bot_settings.enable:
            return False
        if route == "root":
            return True
        if route in {"status", "status:general"}:
            return bot_module_enabled(self.bot_settings, "status")
        if route in {"status:mangle", "mangle"}:
            return self._mangle_available()
        if route.startswith("exceptions"):
            return self._whitelist_available()
        return False

    def _view_for_route(
        self,
        route: str,
        *,
        chat_id: str,
        user_id: str,
        auth: BotAuth,
        now: int,
    ) -> MenuView:
        if route == "root":
            return self._root_view(chat_id=chat_id, auth=auth)
        if route == "status":
            return build_status_menu_view(show_mangle=self._mangle_available())
        if route == "status:general":
            return MenuView(
                format_status(self.status_snapshot_factory()),
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": "⬅️ Назад",
                                "callback_data": "menu:v1:status",
                            }
                        ]
                    ]
                },
            )
        if route == "status:mangle":
            assert self.mangle_handler is not None
            return self.mangle_handler.status_view()
        if route == "mangle":
            assert self.mangle_handler is not None
            return self.mangle_handler.control_view(
                chat_id=chat_id,
                user_id=user_id,
            )

        assert self.whitelist_handler is not None
        page = int(route.split(":", 1)[1]) if ":" in route else 0
        return self.whitelist_handler.menu_view(
            page=page,
            chat_id=chat_id,
            user_id=user_id,
            now=now,
        )

    @staticmethod
    def _send_view(
        view: MenuView,
        *,
        send_message: Callable[..., Any],
        token: str,
        chat_id: str,
        timeout: int,
    ) -> Any:
        response = send_message(
            token=token,
            chat_id=chat_id,
            text=view.text,
            reply_markup=view.reply_markup,
            timeout=timeout,
        )
        raise_for_retryable_delivery(response)
        return response

    @classmethod
    def _edit_or_send_view(
        cls,
        view: MenuView,
        *,
        message_id: Any,
        edit_message: Callable[..., Any],
        send_message: Callable[..., Any],
        token: str,
        chat_id: str,
        timeout: int,
    ) -> Any:
        if message_id not in (None, ""):
            response = edit_message(
                token=token,
                chat_id=chat_id,
                message_id=message_id,
                text=view.text,
                reply_markup=view.reply_markup,
                timeout=timeout,
            )
            raise_for_retryable_delivery(response)
            if getattr(response, "ok", True) is not False:
                return response
        return cls._send_view(
            view,
            send_message=send_message,
            token=token,
            chat_id=chat_id,
            timeout=timeout,
        )


def _command_name(text: Any) -> str:
    value = str(text or "").strip()
    if not value.startswith("/"):
        return ""
    return value.split()[0].split("@", 1)[0].lower()


__all__ = [
    "MangleMenuAdapter",
    "TelegramMenuHandler",
    "WhitelistMenuAdapter",
]
