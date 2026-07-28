import json
import types
import unittest
from unittest.mock import Mock, call

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.menu import MenuView, build_launcher_markup
from mikroclear.bot.modules.exceptions import build_exceptions_view
from mikroclear.bot.modules.status import StatusSnapshot
from mikroclear.bot.settings import BotSettings
from mikroclear.settings import Settings
from mikroclear.telegram.commands import RetryableTelegramDeliveryError
from mikroclear.telegram.menu_handler import TelegramMenuHandler


def status_snapshot() -> StatusSnapshot:
    return StatusSnapshot(
        uptime_seconds=10,
        routeros_connected=True,
        routeros_connected_seconds=5,
        eve_path="/tmp/eve.json",
        block_list_name="Suricata",
        monitor_only=False,
        telegram_unblock_enabled=True,
        state_dir="/tmp/state",
        bot_settings=BotSettings(),
    )


class FakeMangleMenu:
    def status_view(self):
        return MenuView("mangle status", {"inline_keyboard": []})

    def control_view(self, *, chat_id, user_id, update_id=""):
        return MenuView(
            f"mangle control {chat_id} {user_id} {update_id}",
            {"inline_keyboard": []},
        )


class SplitMangleMenu:
    def status_view(self):
        return MenuView(
            "Chain: prerouting\nPackets: 7",
            {
                "inline_keyboard": [
                    [{"text": "🔄 Обновить", "callback_data": "menu:v1:status:mangle"}],
                    [{"text": "⬅️ Назад", "callback_data": "menu:v1:status"}],
                ]
            },
        )

    def control_view(self, *, chat_id, user_id, update_id=""):
        return MenuView(
            "<b>Mangle</b>",
            {
                "inline_keyboard": [
                    [{"text": "✅ Site", "callback_data": "mangle:request:token"}],
                    [{"text": "🔄 Обновить", "callback_data": "mangle:refresh"}],
                    [{"text": "⬅️ Назад", "callback_data": "menu:v1:root"}],
                ]
            },
        )


class FakeWhitelistMenu:
    def menu_view(self, *, page, chat_id, user_id, now):
        return MenuView(
            f"exceptions page={page} chat={chat_id} user={user_id} now={now}",
            {"inline_keyboard": []},
        )


def make_handler(*, mangle=None, whitelist=None, settings=None, bot_settings=None):
    send = Mock(return_value=types.SimpleNamespace(ok=True, retryable=False))
    edit = Mock(return_value=types.SimpleNamespace(ok=True, retryable=False))
    resolved_settings = settings or Settings(
        mangle_control_enable=True,
        telegram_whitelist_control_enable=True,
    )
    resolved_bot_settings = bot_settings or BotSettings(
        admin_chat_ids=("admin",),
        allowed_chat_ids=("reader",),
        modules=("status", "mangle_control", "whitelist_control"),
    )
    handler = TelegramMenuHandler(
        resolved_settings,
        bot_settings=resolved_bot_settings,
        status_snapshot_factory=status_snapshot,
        mangle_handler=mangle,
        whitelist_handler=whitelist,
        log=Mock(),
    )
    handler.send = send
    handler.edit = edit
    return handler, send, edit


def handle_message(handler, **overrides):
    kwargs = {
        "text": "/start",
        "chat_id": "reader",
        "user_id": "u",
        "auth": BotAuth(handler.bot_settings),
        "send_message": handler.send,
        "token": "token",
        "timeout": 7,
        "update_id": "42",
    }
    kwargs.update(overrides)
    return handler.handle_message(**kwargs)


def callback(data, *, chat_id="reader", user_id="u", message_id=9):
    return {
        "id": "cb-1",
        "data": data,
        "from": {"id": user_id},
        "message": {"message_id": message_id, "chat": {"id": chat_id}},
    }


def handle_callback(handler, data, *, chat_id="reader", answer=None, now=100):
    answer_callback = answer or Mock()
    result = handler.handle_callback(
        callback=callback(data, chat_id=chat_id),
        auth=BotAuth(handler.bot_settings),
        answer_callback=answer_callback,
        send_message=handler.send,
        edit_message=handler.edit,
        telegram_token="token",
        timeout=7,
        now=now,
    )
    return result, answer_callback


class TelegramMenuTests(unittest.TestCase):
    def test_start_sends_launcher_and_launcher_opens_inline_root(self):
        handler, send, _edit = make_handler()

        self.assertTrue(handle_message(handler))
        self.assertEqual(send.call_args.kwargs["reply_markup"], build_launcher_markup())
        self.assertTrue(handle_message(handler, text="🛡 Mikro-Clear"))
        self.assertIn(
            "menu:v1:status",
            json.dumps(send.call_args.kwargs["reply_markup"]),
        )
        self.assertNotIn(
            "menu:v1:mangle",
            json.dumps(send.call_args.kwargs["reply_markup"]),
        )

    def test_menu_command_restores_launcher_and_unknown_text_falls_through(self):
        handler, send, _edit = make_handler()

        self.assertTrue(handle_message(handler, text="/menu@MikroClearBot extra"))
        self.assertEqual(send.call_args.kwargs["reply_markup"], build_launcher_markup())
        self.assertFalse(handle_message(handler, text="/status"))
        self.assertEqual(send.call_count, 1)

    def test_unauthorized_launcher_messages_are_consumed_without_response(self):
        handler, send, _edit = make_handler()

        for text in ("/start", "/menu", "🛡 Mikro-Clear"):
            with self.subTest(text=text):
                self.assertTrue(
                    handle_message(handler, text=text, chat_id="unknown")
                )

        send.assert_not_called()

    def test_admin_root_includes_only_optional_adapters_that_exist(self):
        handler, send, _edit = make_handler(
            mangle=FakeMangleMenu(),
            whitelist=FakeWhitelistMenu(),
        )

        self.assertTrue(
            handle_message(
                handler,
                text="🛡 Mikro-Clear",
                chat_id="admin",
            )
        )

        markup = json.dumps(send.call_args.kwargs["reply_markup"])
        self.assertIn("menu:v1:status", markup)
        self.assertIn("menu:v1:mangle", markup)
        self.assertIn("menu:v1:exceptions", markup)

    def test_callback_answers_before_editing_current_message(self):
        events = []
        handler, _send, edit = make_handler(mangle=FakeMangleMenu())
        answer = Mock(side_effect=lambda *_args: events.append("answer"))
        edit.side_effect = lambda **_kwargs: (
            events.append("edit")
            or types.SimpleNamespace(ok=True, retryable=False)
        )

        handled, _answer = handle_callback(
            handler,
            "menu:v1:status",
            answer=answer,
        )

        self.assertTrue(handled)
        self.assertEqual(events, ["answer", "edit"])
        answer.assert_called_once_with("cb-1", "", False)
        self.assertEqual(edit.call_args.kwargs["message_id"], 9)
        self.assertEqual(edit.call_args.kwargs["text"], "<b>Статус</b>")
        self.assertIn(
            "menu:v1:status:mangle",
            json.dumps(edit.call_args.kwargs["reply_markup"]),
        )

    def test_general_status_reuses_existing_snapshot_formatter(self):
        handler, _send, edit = make_handler()

        handled, _answer = handle_callback(handler, "menu:v1:status:general")

        self.assertTrue(handled)
        self.assertIn("Mikro-Clear status", edit.call_args.kwargs["text"])
        self.assertEqual(
            edit.call_args.kwargs["reply_markup"],
            {
                "inline_keyboard": [
                    [{"text": "⬅️ Назад", "callback_data": "menu:v1:status"}]
                ]
            },
        )

    def test_callbacks_delegate_to_optional_adapters(self):
        mangle = FakeMangleMenu()
        whitelist = FakeWhitelistMenu()
        handler, _send, edit = make_handler(mangle=mangle, whitelist=whitelist)

        self.assertTrue(
            handle_callback(
                handler,
                "menu:v1:status:mangle",
                chat_id="reader",
            )[0]
        )
        self.assertEqual(edit.call_args.kwargs["text"], "mangle status")

        self.assertTrue(
            handle_callback(
                handler,
                "menu:v1:mangle",
                chat_id="admin",
            )[0]
        )
        self.assertEqual(
            edit.call_args.kwargs["text"],
            "mangle control admin u ",
        )

        self.assertTrue(
            handle_callback(
                handler,
                "menu:v1:exceptions:3",
                chat_id="admin",
                now=123,
            )[0]
        )
        self.assertEqual(
            edit.call_args.kwargs["text"],
            "exceptions page=3 chat=admin user=u now=123",
        )

    def test_status_and_control_routes_keep_mangle_surfaces_separate(self):
        handler, _send, edit = make_handler(mangle=SplitMangleMenu())

        self.assertTrue(
            handle_callback(
                handler,
                "menu:v1:status:mangle",
                chat_id="reader",
            )[0]
        )
        self.assertIn("Chain: prerouting", edit.call_args.kwargs["text"])
        self.assertNotIn(
            "mangle:request:",
            json.dumps(edit.call_args.kwargs["reply_markup"]),
        )

        self.assertTrue(
            handle_callback(
                handler,
                "menu:v1:mangle",
                chat_id="admin",
            )[0]
        )
        self.assertNotIn("Chain:", edit.call_args.kwargs["text"])
        self.assertIn(
            "mangle:request:",
            json.dumps(edit.call_args.kwargs["reply_markup"]),
        )

    def test_absent_adapter_returns_exact_unavailable_answer(self):
        handler, send, edit = make_handler()

        handled, answer = handle_callback(
            handler,
            "menu:v1:mangle",
            chat_id="admin",
        )

        self.assertTrue(handled)
        answer.assert_called_once_with("cb-1", "Функция недоступна", True)
        send.assert_not_called()
        edit.assert_not_called()

    def test_callback_rechecks_authorization_and_current_feature_flags(self):
        handler, send, edit = make_handler(
            mangle=FakeMangleMenu(),
            settings=Settings(mangle_control_enable=False),
        )

        handled, answer = handle_callback(
            handler,
            "menu:v1:status",
            chat_id="unknown",
        )
        self.assertTrue(handled)
        answer.assert_called_once_with("cb-1", "Unauthorized", True)

        handled, answer = handle_callback(
            handler,
            "menu:v1:mangle",
            chat_id="admin",
        )
        self.assertTrue(handled)
        answer.assert_called_once_with("cb-1", "Функция недоступна", True)
        send.assert_not_called()
        edit.assert_not_called()

    def test_root_callback_is_available_without_status_module(self):
        handler, _send, edit = make_handler(
            mangle=FakeMangleMenu(),
            bot_settings=BotSettings(
                admin_chat_ids=("admin",),
                modules=("mangle_control",),
            ),
        )

        handled, answer = handle_callback(
            handler,
            "menu:v1:root",
            chat_id="admin",
        )

        self.assertTrue(handled)
        answer.assert_called_once_with("cb-1", "", False)
        self.assertEqual(edit.call_args.kwargs["text"], "<b>Mikro-Clear</b>")
        self.assertIn(
            "menu:v1:mangle",
            json.dumps(edit.call_args.kwargs["reply_markup"]),
        )

    def test_non_retryable_edit_failure_falls_back_to_send(self):
        handler, send, edit = make_handler()
        edit.return_value = types.SimpleNamespace(ok=False, retryable=False)

        handled, _answer = handle_callback(handler, "menu:v1:root")

        self.assertTrue(handled)
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs["chat_id"], "reader")
        self.assertEqual(send.call_args.kwargs["text"], "<b>Mikro-Clear</b>")

    def test_retryable_edit_failure_is_not_converted_to_send(self):
        handler, send, edit = make_handler()
        edit.return_value = types.SimpleNamespace(
            ok=False,
            retryable=True,
            response_text="temporary",
        )

        with self.assertRaises(RetryableTelegramDeliveryError):
            handle_callback(handler, "menu:v1:root")

        send.assert_not_called()

    def test_unknown_callback_falls_through_without_authorization_answer(self):
        handler, send, edit = make_handler()
        answer = Mock()

        handled, _answer = handle_callback(
            handler,
            "mangle:refresh",
            chat_id="unknown",
            answer=answer,
        )

        self.assertFalse(handled)
        answer.assert_not_called()
        send.assert_not_called()
        edit.assert_not_called()


class ExceptionsMenuViewTests(unittest.TestCase):
    def test_exceptions_view_separates_system_and_managed_entries(self):
        view = build_exceptions_view(
            system_entries=("10.0.0.0/8", "1.1.1.1"),
            managed_entries=("192.168.98.200",),
            page=0,
            page_size=8,
            remove_token_factory=lambda _address: "remove1234",
        )

        self.assertIn("Системные — только просмотр", view.text)
        self.assertIn("🔒 10.0.0.0/8", view.text)
        self.assertIn("Добавлены через Telegram", view.text)
        self.assertIn("🛡 192.168.98.200", view.text)
        self.assertIn(
            "whitelist:v1:remove-request:",
            json.dumps(view.reply_markup),
        )

    def test_exceptions_view_paginates_managed_entries(self):
        managed = tuple(f"10.0.0.{index}" for index in range(1, 18))

        view = build_exceptions_view(
            (),
            managed,
            page=1,
            page_size=8,
            remove_token_factory=lambda value: value,
        )

        callbacks = json.dumps(view.reply_markup)
        self.assertIn("menu:v1:exceptions:0", callbacks)
        self.assertIn("menu:v1:exceptions:2", callbacks)

    def test_pagination_counts_system_and_managed_rows_together(self):
        system = tuple(f"10.{index}.0.0/16" for index in range(9))

        view = build_exceptions_view(
            system,
            ("192.168.98.200",),
            page=1,
            page_size=8,
            remove_token_factory=lambda value: value,
        )

        self.assertIn("🔒 10.8.0.0/16", view.text)
        self.assertIn("🛡 192.168.98.200", view.text)


if __name__ == "__main__":
    unittest.main()
