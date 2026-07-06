import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

from mikroclear.bot.auth import BotAuth
from mikroclear.bot.mangle_control import (
    build_mangle_confirm_keyboard,
    build_mangle_keyboard,
    format_mangle_status,
)
from mikroclear.bot.settings import BotSettings
from mikroclear.routeros.mangle import MangleRule
from mikroclear.settings import Settings
from mikroclear.telegram.mangle_handler import TelegramMangleHandler


class FakeWhere:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def where(self, *args):
        return self.rows


class FakeMangleResource:
    def __init__(self, rows):
        self.rows = rows
        self.updated = []

    def select(self, *keys):
        return FakeWhere(self.rows)

    def update(self, rule_id, **kwargs):
        self.updated.append((rule_id, kwargs))


class FakeApi:
    def __init__(self, rows):
        self.mangle = FakeMangleResource(rows)

    def path(self, name):
        if name != "/ip/firewall/mangle":
            raise AssertionError(name)
        return self.mangle


class FakeClient:
    def __init__(self, rows):
        self.api = FakeApi(rows)

    def ensure_connected(self):
        return self.api

    def run_with_reconnect(self, operation_name, func):
        return func()


def settings(tmp: str, **overrides):
    return Settings(
        enable_telegram=True,
        telegram_token="token",
        telegram_chatid="chat-1",
        state_dir=tmp,
        mangle_control_enable=True,
        mangle_comment_prefix="MC:",
        mangle_allowed_chains=("prerouting", "forward", "output"),
        mangle_allowed_actions=("mark-routing", "mark-connection", "mark-packet", "accept"),
        **overrides,
    )


def rows(disabled="false"):
    return [
        {
            ".id": "*1",
            "comment": "MC:AI-Tunnel",
            "chain": "prerouting",
            "action": "mark-routing",
            "disabled": disabled,
            "packets": "4516",
            "bytes": "3615163",
        }
    ]


class MangleControlFormattingTests(TestCase):
    def test_format_status_shows_enabled_disabled_packets_and_bytes(self):
        text = format_mangle_status(
            [
                MangleRule("*1", "AI-Tunnel", "MC:AI-Tunnel", "prerouting", "mark-routing", False, 4516, 3615163),
                MangleRule("*2", "TV", "MC:TV", "forward", "accept", True, 0, 0),
            ]
        )

        self.assertIn("<b>Mangle Rules</b>", text)
        self.assertIn("✅ AI-Tunnel", text)
        self.assertIn("❌ TV", text)
        self.assertIn("Packets: 4516", text)
        self.assertIn("Bytes: 3615163", text)

    def test_build_keyboard_uses_enable_disable_request_tokens_and_refresh(self):
        keyboard = build_mangle_keyboard(
            [
                MangleRule("*1", "AI-Tunnel", "MC:AI-Tunnel", "prerouting", "mark-routing", False),
                MangleRule("*2", "TV", "MC:TV", "forward", "accept", True),
            ],
            token_factory=lambda rule, action: f"tok-{rule.name}-{action}",
        )

        buttons = keyboard["inline_keyboard"]
        self.assertEqual(buttons[0][0]["text"], "Disable AI-Tunnel")
        self.assertEqual(buttons[0][0]["callback_data"], "mangle:request:tok-AI-Tunnel-disable")
        self.assertEqual(buttons[1][0]["text"], "Enable TV")
        self.assertEqual(buttons[1][0]["callback_data"], "mangle:request:tok-TV-enable")
        self.assertEqual(buttons[-1][0]["text"], "Refresh")
        self.assertEqual(buttons[-1][0]["callback_data"], "mangle:refresh")

    def test_confirm_keyboard(self):
        keyboard = build_mangle_confirm_keyboard("tok123")

        buttons = keyboard["inline_keyboard"][0]
        self.assertEqual(buttons[0]["callback_data"], "mangle:confirm:tok123")
        self.assertEqual(buttons[1]["callback_data"], "mangle:cancel:tok123")


class TelegramMangleHandlerTests(TestCase):
    def auth(self):
        return BotAuth(BotSettings(admin_chat_ids=("chat-1",), allowed_chat_ids=("read-only",)), legacy_chat_id="")

    def test_mangle_unauthorized_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            send = Mock()
            handler = TelegramMangleHandler(settings(tmp), get_router_client=lambda: FakeClient(rows()), log=Mock())

            handled = handler.handle_message(
                text="/mangle",
                chat_id="unknown",
                auth=self.auth(),
                send_message=send,
                token="token",
                timeout=7,
            )

        self.assertTrue(handled)
        send.assert_not_called()

    def test_mangle_authorized_returns_status_and_keyboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            send = Mock()
            handler = TelegramMangleHandler(settings(tmp), get_router_client=lambda: FakeClient(rows()), log=Mock())

            handled = handler.handle_message(
                text="/mangle",
                chat_id="chat-1",
                auth=self.auth(),
                send_message=send,
                token="token",
                timeout=7,
            )

        self.assertTrue(handled)
        self.assertIn("Mangle Rules", send.call_args.kwargs["text"])
        self.assertEqual(send.call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]["text"], "Disable AI-Tunnel")

    def test_request_returns_confirm_keyboard_without_routeros_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(rows())
            send = Mock()
            answer = Mock()
            handler = TelegramMangleHandler(settings(tmp), get_router_client=lambda: client, log=Mock())
            token = handler.create_action_token("*1", "disable", "chat-1", "user-1", now=100)

            handled = handler.handle_callback(
                callback={"id": "cb-1", "data": f"mangle:request:{token}", "message": {"chat": {"id": "chat-1"}}, "from": {"id": "user-1"}},
                auth=self.auth(),
                answer_callback=answer,
                send_message=send,
                telegram_token="token",
                timeout=7,
                now=101,
            )

        self.assertTrue(handled)
        self.assertEqual(client.api.mangle.updated, [])
        self.assertIn("Confirm mangle change?", send.call_args.kwargs["text"])
        self.assertIn("Action: Disable", send.call_args.kwargs["text"])

    def test_confirm_updates_exactly_once_and_shows_refreshed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(rows())
            send = Mock()
            handler = TelegramMangleHandler(settings(tmp), get_router_client=lambda: client, log=Mock())
            token = handler.create_action_token("*1", "disable", "chat-1", "user-1", now=100)

            handled = handler.handle_callback(
                callback={"id": "cb-1", "data": f"mangle:confirm:{token}", "message": {"chat": {"id": "chat-1"}}, "from": {"id": "user-1"}},
                auth=self.auth(),
                answer_callback=Mock(),
                send_message=send,
                telegram_token="token",
                timeout=7,
                now=101,
            )
            repeated = handler.handle_callback(
                callback={"id": "cb-2", "data": f"mangle:confirm:{token}", "message": {"chat": {"id": "chat-1"}}, "from": {"id": "user-1"}},
                auth=self.auth(),
                answer_callback=Mock(),
                send_message=send,
                telegram_token="token",
                timeout=7,
                now=102,
            )

        self.assertTrue(handled)
        self.assertTrue(repeated)
        self.assertEqual(client.api.mangle.updated, [("*1", {"disabled": "yes"})])

    def test_cancel_and_expired_token_do_not_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(rows())
            handler = TelegramMangleHandler(settings(tmp), get_router_client=lambda: client, log=Mock())
            token = handler.create_action_token("*1", "enable", "chat-1", "user-1", now=100, ttl_seconds=1)

            handled = handler.handle_callback(
                callback={"id": "cb-1", "data": f"mangle:cancel:{token}", "message": {"chat": {"id": "chat-1"}}, "from": {"id": "user-1"}},
                auth=self.auth(),
                answer_callback=Mock(),
                send_message=Mock(),
                telegram_token="token",
                timeout=7,
                now=100,
            )
            expired = handler.handle_callback(
                callback={"id": "cb-2", "data": f"mangle:confirm:{token}", "message": {"chat": {"id": "chat-1"}}, "from": {"id": "user-1"}},
                auth=self.auth(),
                answer_callback=Mock(),
                send_message=Mock(),
                telegram_token="token",
                timeout=7,
                now=102,
            )

        self.assertTrue(handled)
        self.assertTrue(expired)
        self.assertEqual(client.api.mangle.updated, [])

    def test_refresh_returns_current_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            send = Mock()
            handler = TelegramMangleHandler(settings(tmp), get_router_client=lambda: FakeClient(rows("true")), log=Mock())

            handled = handler.handle_callback(
                callback={"id": "cb-1", "data": "mangle:refresh", "message": {"chat": {"id": "chat-1"}}, "from": {"id": "user-1"}},
                auth=self.auth(),
                answer_callback=Mock(),
                send_message=send,
                telegram_token="token",
                timeout=7,
                now=100,
            )

        self.assertTrue(handled)
        self.assertIn("❌ AI-Tunnel", send.call_args.kwargs["text"])
