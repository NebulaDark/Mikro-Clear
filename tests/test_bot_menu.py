import unittest

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.menu import (
    LAUNCHER_LABEL,
    build_launcher_markup,
    build_root_view,
    build_status_menu_view,
    default_menu_registry,
    parse_menu_callback,
)
from mikroclear.bot.settings import BotSettings
from mikroclear.settings import Settings


class BotMenuTests(unittest.TestCase):
    def test_launcher_is_single_persistent_reply_button(self):
        self.assertEqual(
            build_launcher_markup(),
            {
                "keyboard": [[{"text": "🛡 Mikro-Clear"}]],
                "is_persistent": True,
                "resize_keyboard": True,
            },
        )
        self.assertEqual(LAUNCHER_LABEL, "🛡 Mikro-Clear")

    def test_registry_filters_by_permission_module_and_feature(self):
        auth = BotAuth(
            BotSettings(
                admin_chat_ids=("admin",),
                allowed_chat_ids=("reader",),
                modules=("status", "mangle_control", "whitelist_control"),
            )
        )
        self.assertEqual(
            [
                item.item_id
                for item in default_menu_registry().visible(
                    chat_id="reader",
                    auth=auth,
                    settings=Settings(
                        mangle_control_enable=True,
                        telegram_whitelist_control_enable=True,
                    ),
                    bot_settings=auth.settings,
                )
            ],
            ["status"],
        )
        self.assertEqual(
            [
                item.item_id
                for item in default_menu_registry().visible(
                    chat_id="admin",
                    auth=auth,
                    settings=Settings(
                        mangle_control_enable=True,
                        telegram_whitelist_control_enable=True,
                    ),
                    bot_settings=auth.settings,
                )
            ],
            ["status", "mangle_control", "whitelist_control"],
        )

    def test_registry_filters_disabled_features_and_modules(self):
        auth = BotAuth(
            BotSettings(
                admin_chat_ids=("admin",),
                modules=("status", "mangle_control"),
            )
        )

        visible = default_menu_registry().visible(
            chat_id="admin",
            auth=auth,
            settings=Settings(
                mangle_control_enable=False,
                telegram_whitelist_control_enable=True,
            ),
            bot_settings=auth.settings,
        )

        self.assertEqual([item.item_id for item in visible], ["status"])

    def test_menu_callback_parser_accepts_only_versioned_known_routes(self):
        accepted = {
            "menu:v1:root": "root",
            "menu:v1:status": "status",
            "menu:v1:status:general": "status:general",
            "menu:v1:status:mangle": "status:mangle",
            "menu:v1:mangle": "mangle",
            "menu:v1:exceptions": "exceptions",
            "menu:v1:exceptions:0": "exceptions:0",
            "menu:v1:exceptions:17": "exceptions:17",
        }
        for data, route in accepted.items():
            with self.subTest(data=data):
                self.assertEqual(parse_menu_callback(data), route)

        for data in (
            None,
            "",
            "menu:v2:root",
            "menu:v1:",
            "menu:v1:unknown",
            "menu:v1:exceptions:-1",
            "menu:v1:exceptions:1x",
            "prefix-menu:v1:root",
        ):
            with self.subTest(data=data):
                self.assertIsNone(parse_menu_callback(data))

    def test_root_view_uses_two_column_ordered_routes(self):
        items = default_menu_registry().items

        view = build_root_view(items)

        self.assertEqual(view.text, "<b>Mikro-Clear</b>")
        self.assertEqual(
            view.reply_markup,
            {
                "inline_keyboard": [
                    [
                        {"text": "📊 Статус", "callback_data": "menu:v1:status"},
                        {"text": "🔀 Mangle", "callback_data": "menu:v1:mangle"},
                    ],
                    [
                        {
                            "text": "🛡 Исключения",
                            "callback_data": "menu:v1:exceptions",
                        }
                    ],
                ]
            },
        )

    def test_status_menu_hides_optional_mangle_route(self):
        self.assertEqual(
            build_status_menu_view(show_mangle=False).reply_markup,
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "🛡 Общий статус",
                            "callback_data": "menu:v1:status:general",
                        }
                    ],
                    [{"text": "⬅️ Назад", "callback_data": "menu:v1:root"}],
                ]
            },
        )


if __name__ == "__main__":
    unittest.main()
