import tempfile
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

import mikroclear.bot.mangle_control as mangle_control
from mikroclear.bot.audit import BotAuditLog
from mikroclear.bot.auth import BotAuth
from mikroclear.bot.mangle_control import (
    build_mangle_confirm_keyboard,
    build_mangle_keyboard,
    format_mangle_status,
)
from mikroclear.bot.settings import BotSettings
from mikroclear.routeros.mangle import MangleRule
from mikroclear.settings import Settings
from mikroclear.telegram.commands import RetryableTelegramDeliveryError
from mikroclear.telegram.mangle_handler import TelegramMangleHandler

build_mangle_control_keyboard = getattr(
    mangle_control,
    "build_mangle_control_keyboard",
    build_mangle_keyboard,
)


class FakeWhere:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def where(self, *args):
        return self.rows


class FakeMangleResource:
    def __init__(self, rows, *, update_error=None):
        self.rows = rows
        self.updated = []
        self.update_error = update_error

    def select(self, *keys):
        return FakeWhere(self.rows)

    def update(self, rule_id, **kwargs):
        if self.update_error is not None:
            raise self.update_error
        self.updated.append((rule_id, kwargs))
        for row in self.rows:
            if row.get(".id") == rule_id:
                row["disabled"] = kwargs["disabled"]


class FakeApi:
    def __init__(self, rows, *, update_error=None):
        self.mangle = FakeMangleResource(rows, update_error=update_error)

    def path(self, name):
        if name != "/ip/firewall/mangle":
            raise AssertionError(name)
        return self.mangle


class FakeClient:
    def __init__(self, rows, *, update_error=None):
        self.api = FakeApi(rows, update_error=update_error)

    def ensure_connected(self):
        return self.api

    def run_with_reconnect(self, operation_name, func):
        return func()


class FakeSendResult:
    def __init__(self, ok=True, response_text="ok"):
        self.ok = ok
        self.response_text = response_text


def settings(tmp: str, **overrides):
    values = {
        "enable_telegram": True,
        "telegram_token": "token",
        "telegram_chatid": "chat-1",
        "state_dir": tmp,
        "mangle_control_enable": True,
        "mangle_comment_prefix": "MC:",
    }
    values.update(overrides)
    return Settings(**values)


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


def live_bot_settings(tmp: str, *, dry_run: bool = False) -> BotSettings:
    return BotSettings(
        dry_run=dry_run,
        audit_log=str(Path(tmp, "bot-audit.log")),
    )


def make_handler(
    tmp: str,
    *,
    bot_settings: BotSettings | None = None,
    client: FakeClient | None = None,
    row_values=None,
):
    resolved_client = client or FakeClient(row_values or rows())
    resolved_bot_settings = bot_settings or live_bot_settings(tmp)
    edit = Mock(return_value=FakeSendResult())
    handler = TelegramMangleHandler(
        settings(tmp),
        bot_settings=resolved_bot_settings,
        audit=BotAuditLog(Path(resolved_bot_settings.audit_log)),
        get_router_client=lambda: resolved_client,
        log=Mock(),
    )
    handler.edit_message = edit
    return handler, resolved_client, edit


def mangle_callback(data: str, *, user_id: str = "user-1", message_id: int = 9):
    return {
        "id": "cb-1",
        "data": data,
        "message": {"message_id": message_id, "chat": {"id": "chat-1"}},
        "from": {"id": user_id},
    }


def last_rule_button(transport: Mock) -> dict[str, str]:
    return transport.call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]


def read_audit(path: str) -> list[dict[str, str]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
    ]


class MangleControlFormattingTests(TestCase):
    def test_compact_keyboard_api_is_exported(self):
        self.assertTrue(hasattr(mangle_control, "build_mangle_control_keyboard"))

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

    def test_control_keyboard_uses_actual_state_icons(self):
        keyboard = build_mangle_control_keyboard(
            [
                MangleRule("*1", "Site", "MC:Site", "prerouting", "mark-routing", False),
                MangleRule("*2", "Backup", "MC:Backup", "prerouting", "mark-routing", True),
            ],
            token_factory=lambda rule, action: f"{rule.rule_id}-{action}",
        )

        buttons = keyboard["inline_keyboard"]
        self.assertEqual(buttons[0][0]["text"], "✅ Site")
        self.assertEqual(buttons[0][0]["callback_data"], "mangle:request:*1-disable")
        self.assertEqual(buttons[1][0]["text"], "❌ Backup")
        self.assertEqual(buttons[1][0]["callback_data"], "mangle:request:*2-enable")
        self.assertEqual(buttons[-2][0], {"text": "🔄 Обновить", "callback_data": "mangle:refresh"})
        self.assertEqual(buttons[-1][0], {"text": "⬅️ Назад", "callback_data": "menu:v1:root"})

    def test_legacy_keyboard_name_keeps_compact_contract(self):
        keyboard = build_mangle_keyboard(
            [MangleRule("*1", "Site", "MC:Site", "prerouting", "mark-routing", False)],
            token_factory=lambda _rule, _action: "token",
        )

        self.assertEqual(keyboard["inline_keyboard"][0][0]["text"], "✅ Site")

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
                user_id="user-1",
                auth=self.auth(),
                send_message=send,
                token="token",
                timeout=7,
            )

        self.assertTrue(handled)
        send.assert_not_called()

    def test_mangle_disabled_reports_to_authorized_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            send = Mock()
            handler = TelegramMangleHandler(
                settings(tmp, mangle_control_enable=False),
                get_router_client=lambda: FakeClient(rows()),
                log=Mock(),
            )

            handled = handler.handle_message(
                text="/mangle",
                chat_id="chat-1",
                user_id="user-1",
                auth=self.auth(),
                send_message=send,
                token="token",
                timeout=7,
            )

        self.assertTrue(handled)
        send.assert_called_once_with(token="token", chat_id="chat-1", text="Mangle control is disabled", timeout=7)

    def test_mangle_authorized_returns_status_and_keyboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            send = Mock()
            log = Mock()
            handler = TelegramMangleHandler(settings(tmp), get_router_client=lambda: FakeClient(rows()), log=log)

            handled = handler.handle_message(
                text="/mangle",
                chat_id="chat-1",
                user_id="user-1",
                auth=self.auth(),
                send_message=send,
                token="token",
                timeout=7,
            )
            state = json.loads(Path(tmp, "telegram-mangle-actions.json").read_text(encoding="utf-8"))

        self.assertTrue(handled)
        self.assertNotIn("Chain:", send.call_args.kwargs["text"])
        self.assertEqual(send.call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]["text"], "✅ AI-Tunnel")
        self.assertIn("Telegram /mangle received from chat chat-1", log.call_args_list[0].args[0])
        payload = next(iter(state.values()))
        self.assertEqual(payload["requester_user_id"], "user-1")

    def test_status_view_is_detailed_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler, _client, _edit = make_handler(tmp)

            view = handler.status_view()

        self.assertIn("Chain: prerouting", view.text)
        self.assertIn("Packets:", view.text)
        callbacks = json.dumps(view.reply_markup)
        self.assertNotIn("mangle:request:", callbacks)
        self.assertIn("menu:v1:status", callbacks)

    def test_control_view_is_compact_and_rereads_actual_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            row_values = rows("false")
            handler, _client, _edit = make_handler(tmp, row_values=row_values)

            enabled = handler.control_view(chat_id="chat-1", user_id="user-1")
            row_values[0]["disabled"] = "true"
            disabled = handler.control_view(chat_id="chat-1", user_id="user-1")

        self.assertNotIn("Chain:", enabled.text)
        self.assertEqual(
            enabled.reply_markup["inline_keyboard"][0][0]["text"],
            "✅ AI-Tunnel",
        )
        self.assertEqual(disabled.reply_markup["inline_keyboard"][0][0]["text"], "❌ AI-Tunnel")

    def test_mangle_status_send_failure_is_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Mock()
            send = Mock(return_value=FakeSendResult(ok=False, response_text="HTTP 403: forbidden"))
            handler = TelegramMangleHandler(settings(tmp), get_router_client=lambda: FakeClient(rows()), log=log)

            handled = handler.handle_message(
                text="/mangle",
                chat_id="chat-1",
                user_id="user-1",
                auth=self.auth(),
                send_message=send,
                token="token",
                timeout=7,
            )

        self.assertTrue(handled)
        self.assertTrue(any("TELEGRAM MANGLE STATUS SEND FAILED" in call.args[0] for call in log.call_args_list))

    def test_retrying_same_update_reuses_action_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated = iter(["token-one", "token-two"])
            send = Mock()
            handler = TelegramMangleHandler(
                settings(tmp),
                get_router_client=lambda: FakeClient(rows()),
                log=Mock(),
                token_factory=lambda: next(generated),
            )

            for _attempt in range(2):
                handler.handle_message(
                    text="/mangle",
                    chat_id="chat-1",
                    user_id="user-1",
                    update_id="99",
                    auth=self.auth(),
                    send_message=send,
                    token="token",
                    timeout=7,
                )

            state = json.loads(
                Path(tmp, "telegram-mangle-actions.json").read_text(encoding="utf-8")
            )

        self.assertEqual(list(state), ["token-one"])
        callback_values = [
            call.kwargs["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
            for call in send.call_args_list
        ]
        self.assertEqual(
            callback_values,
            ["mangle:request:token-one", "mangle:request:token-one"],
        )

    def test_request_returns_confirm_keyboard_without_routeros_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(rows())
            send = Mock()
            answer = Mock()
            handler = TelegramMangleHandler(
                settings(tmp),
                bot_settings=live_bot_settings(tmp),
                get_router_client=lambda: client,
                log=Mock(),
            )
            handler.edit_message = Mock(return_value=FakeSendResult())
            token = handler.create_action_token("*1", "disable", "chat-1", "user-1", now=100)

            handled = handler.handle_callback(
                callback=mangle_callback(f"mangle:request:{token}"),
                auth=self.auth(),
                answer_callback=answer,
                send_message=send,
                edit_message=handler.edit_message,
                telegram_token="token",
                timeout=7,
                now=101,
            )

        self.assertTrue(handled)
        self.assertEqual(client.api.mangle.updated, [])
        send.assert_not_called()
        self.assertIn("Confirm mangle change?", handler.edit_message.call_args.kwargs["text"])
        self.assertIn("Action: Disable", handler.edit_message.call_args.kwargs["text"])

    def test_confirmation_disabled_consumes_request_and_uses_same_mutation_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(rows("false"))
            bot_settings = live_bot_settings(tmp)
            edit = Mock(return_value=FakeSendResult())
            handler = TelegramMangleHandler(
                settings(tmp, mangle_require_confirmation=False),
                bot_settings=bot_settings,
                audit=BotAuditLog(Path(bot_settings.audit_log)),
                get_router_client=lambda: client,
                log=Mock(),
            )
            token = handler.create_action_token("*1", "disable", "chat-1", "user-1", now=100)

            handled = handler.handle_callback(
                callback=mangle_callback(f"mangle:request:{token}"),
                auth=self.auth(),
                answer_callback=Mock(),
                send_message=Mock(),
                edit_message=edit,
                telegram_token="token",
                timeout=7,
                now=101,
            )
            outcomes = [
                row["outcome"] for row in read_audit(bot_settings.audit_log)
            ]

        self.assertTrue(handled)
        self.assertEqual(client.api.mangle.updated, [("*1", {"disabled": "yes"})])
        self.assertEqual(last_rule_button(edit)["text"], "❌ AI-Tunnel")
        self.assertEqual(outcomes, ["attempted", "success"])

    def test_dry_run_does_not_update_routeros_and_keeps_actual_icon(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot_settings = live_bot_settings(tmp, dry_run=True)
            handler, client, edit = make_handler(
                tmp,
                bot_settings=bot_settings,
                row_values=rows("false"),
            )
            token = handler.create_action_token("*1", "disable", "chat-1", "user-1", now=100)

            handler.handle_callback(
                callback=mangle_callback(f"mangle:confirm:{token}"),
                auth=self.auth(),
                answer_callback=Mock(),
                send_message=Mock(),
                edit_message=edit,
                telegram_token="token",
                timeout=7,
                now=101,
            )
            outcomes = [
                row["outcome"] for row in read_audit(bot_settings.audit_log)
            ]

        self.assertEqual(client.api.mangle.updated, [])
        self.assertEqual(last_rule_button(edit)["text"], "✅ AI-Tunnel")
        self.assertEqual(outcomes, ["attempted", "dry-run"])

    def test_successful_change_edits_with_reread_routeros_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler, client, edit = make_handler(tmp, row_values=rows("false"))
            token = handler.create_action_token("*1", "disable", "chat-1", "user-1", now=100)

            handler.handle_callback(
                callback=mangle_callback(f"mangle:confirm:{token}"),
                auth=self.auth(),
                answer_callback=Mock(),
                send_message=Mock(),
                edit_message=edit,
                telegram_token="token",
                timeout=7,
                now=101,
            )

        self.assertEqual(client.api.mangle.updated, [("*1", {"disabled": "yes"})])
        self.assertEqual(last_rule_button(edit)["text"], "❌ AI-Tunnel")

    def test_routeros_failure_is_audited_without_local_icon_inversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(rows("false"), update_error=RuntimeError("router payload"))
            handler, _client, edit = make_handler(tmp, client=client)
            answer = Mock()
            token = handler.create_action_token("*1", "disable", "chat-1", "user-1", now=100)

            handler.handle_callback(
                callback=mangle_callback(f"mangle:confirm:{token}"),
                auth=self.auth(),
                answer_callback=answer,
                send_message=Mock(),
                edit_message=edit,
                telegram_token="token",
                timeout=7,
                now=101,
            )
            audit_rows = read_audit(handler.bot_settings.audit_log)

        self.assertEqual(client.api.mangle.updated, [])
        edit.assert_not_called()
        answer.assert_called_once_with("cb-1", "Could not update mangle rule", True)
        self.assertEqual([row["outcome"] for row in audit_rows], ["attempted", "failure"])
        self.assertNotIn("router payload", json.dumps(audit_rows))

    def test_stale_token_and_unauthorized_callback_are_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler, client, edit = make_handler(tmp)
            stale_answer = Mock()
            handler.handle_callback(
                callback=mangle_callback("mangle:confirm:missing"),
                auth=self.auth(),
                answer_callback=stale_answer,
                send_message=Mock(),
                edit_message=edit,
                telegram_token="token",
                timeout=7,
                now=101,
            )
            unauthorized_answer = Mock()
            handler.handle_callback(
                callback=mangle_callback("mangle:refresh", user_id="intruder"),
                auth=BotAuth(BotSettings()),
                answer_callback=unauthorized_answer,
                send_message=Mock(),
                edit_message=edit,
                telegram_token="token",
                timeout=7,
                now=102,
            )
            outcomes = [
                row["outcome"]
                for row in read_audit(handler.bot_settings.audit_log)
            ]

        stale_answer.assert_called_once_with("cb-1", "Mangle request expired or already used", True)
        unauthorized_answer.assert_called_once_with("cb-1", "Unauthorized", True)
        self.assertEqual(client.api.mangle.updated, [])
        self.assertEqual(outcomes, ["stale", "denied"])

    def test_non_retryable_edit_failure_falls_back_to_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler, _client, edit = make_handler(tmp, row_values=rows("true"))
            edit.return_value = FakeSendResult(ok=False)
            send = Mock(return_value=FakeSendResult())

            handled = handler.handle_callback(
                callback=mangle_callback("mangle:refresh"),
                auth=self.auth(),
                answer_callback=Mock(),
                send_message=send,
                edit_message=edit,
                telegram_token="token",
                timeout=7,
                now=100,
            )

        self.assertTrue(handled)
        self.assertEqual(last_rule_button(send)["text"], "❌ AI-Tunnel")

    def test_callback_disabled_rejects_without_routeros_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(rows())
            answer = Mock()
            handler = TelegramMangleHandler(
                settings(tmp, mangle_control_enable=False),
                get_router_client=lambda: client,
                log=Mock(),
            )

            handled = handler.handle_callback(
                callback={"id": "cb-1", "data": "mangle:refresh", "message": {"chat": {"id": "chat-1"}}, "from": {"id": "user-1"}},
                auth=self.auth(),
                answer_callback=answer,
                send_message=Mock(),
                telegram_token="token",
                timeout=7,
                now=101,
            )

        self.assertTrue(handled)
        answer.assert_called_once_with("cb-1", "Mangle control is disabled", True)
        self.assertEqual(client.api.mangle.updated, [])

    def test_request_from_different_user_is_rejected_without_confirm_keyboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(rows())
            send = Mock()
            answer = Mock()
            handler = TelegramMangleHandler(
                settings(tmp),
                bot_settings=live_bot_settings(tmp),
                get_router_client=lambda: client,
                log=Mock(),
            )
            token = handler.create_action_token("*1", "disable", "chat-1", "user-1", now=100)

            handled = handler.handle_callback(
                callback={"id": "cb-1", "data": f"mangle:request:{token}", "message": {"chat": {"id": "chat-1"}}, "from": {"id": "user-2"}},
                auth=self.auth(),
                answer_callback=answer,
                send_message=send,
                telegram_token="token",
                timeout=7,
                now=101,
            )

        self.assertTrue(handled)
        send.assert_not_called()
        answer.assert_called_once_with("cb-1", "Unauthorized", True)
        self.assertEqual(client.api.mangle.updated, [])

    def test_confirm_updates_exactly_once_and_shows_refreshed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(rows())
            send = Mock()
            handler = TelegramMangleHandler(
                settings(tmp),
                bot_settings=live_bot_settings(tmp),
                get_router_client=lambda: client,
                log=Mock(),
            )
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

    def test_confirm_keeps_success_when_post_write_status_delivery_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(rows())
            log = Mock()
            answer = Mock()
            handler = TelegramMangleHandler(
                settings(tmp),
                bot_settings=live_bot_settings(tmp),
                get_router_client=lambda: client,
                log=log,
            )
            token = handler.create_action_token(
                "*1",
                "disable",
                "chat-1",
                "user-1",
                now=100,
            )

            handled = handler.handle_callback(
                callback={"id": "cb-1", "data": f"mangle:confirm:{token}", "message": {"chat": {"id": "chat-1"}}, "from": {"id": "user-1"}},
                auth=self.auth(),
                answer_callback=answer,
                send_message=Mock(
                    side_effect=RetryableTelegramDeliveryError("temporary")
                ),
                telegram_token="token",
                timeout=7,
                now=101,
            )

        self.assertTrue(handled)
        self.assertEqual(client.api.mangle.updated, [("*1", {"disabled": "yes"})])
        answer.assert_called_once_with("cb-1", "Mangle rule updated", False)
        self.assertTrue(
            any("POST-WRITE STATUS FAILED" in call.args[0] for call in log.call_args_list)
        )

    def test_confirm_from_different_user_does_not_update_or_consume_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(rows())
            handler = TelegramMangleHandler(
                settings(tmp),
                bot_settings=live_bot_settings(tmp),
                get_router_client=lambda: client,
                log=Mock(),
            )
            token = handler.create_action_token("*1", "disable", "chat-1", "user-1", now=100)

            rejected = handler.handle_callback(
                callback={"id": "cb-1", "data": f"mangle:confirm:{token}", "message": {"chat": {"id": "chat-1"}}, "from": {"id": "user-2"}},
                auth=self.auth(),
                answer_callback=Mock(),
                send_message=Mock(),
                telegram_token="token",
                timeout=7,
                now=101,
            )
            accepted = handler.handle_callback(
                callback={"id": "cb-2", "data": f"mangle:confirm:{token}", "message": {"chat": {"id": "chat-1"}}, "from": {"id": "user-1"}},
                auth=self.auth(),
                answer_callback=Mock(),
                send_message=Mock(),
                telegram_token="token",
                timeout=7,
                now=102,
            )

        self.assertTrue(rejected)
        self.assertTrue(accepted)
        self.assertEqual(client.api.mangle.updated, [("*1", {"disabled": "yes"})])

    def test_cancel_and_expired_token_do_not_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(rows())
            handler = TelegramMangleHandler(
                settings(tmp),
                bot_settings=live_bot_settings(tmp),
                get_router_client=lambda: client,
                log=Mock(),
            )
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
        self.assertEqual(last_rule_button(send)["text"], "❌ AI-Tunnel")
