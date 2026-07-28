import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import types
from unittest import TestCase
from unittest.mock import Mock

from mikroclear.bot.audit import BotAuditLog
from mikroclear.bot.auth import BotAuth
from mikroclear.bot.settings import BotSettings
from mikroclear.settings import Settings
from mikroclear.state.dynamic_whitelist import DynamicWhitelistStore
from mikroclear.suricata.whitelist_policy import WhitelistPolicy
from mikroclear.telegram.unblock import build_unblock_keyboard
from mikroclear.telegram.whitelist_actions import (
    WhitelistActionStore,
    WhitelistActionStoreError,
    append_managed_exception_button,
    build_whitelist_confirm_keyboard,
    parse_whitelist_callback,
)
from mikroclear.telegram.whitelist_handler import TelegramWhitelistHandler


class TelegramWhitelistActionTests(TestCase):
    def test_two_store_instances_allow_exactly_one_concurrent_consume(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "actions.json")
            creator = WhitelistActionStore(
                path,
                token_factory=lambda: "consume123",
            )
            token = creator.create(
                kind="add_confirm",
                address="192.168.98.200",
                list_name="Suricata",
                chat_id="chat-1",
                user_id="user-1",
                now=100,
                ttl_seconds=300,
            )
            first = WhitelistActionStore(path)
            second = WhitelistActionStore(path)
            first_at_write = threading.Event()
            second_has_read = threading.Event()
            original_first_write = first._write_state
            original_second_read = second._read_state

            def pause_first_write(state):
                first_at_write.set()
                second_has_read.wait(0.25)
                original_first_write(state)

            def observe_second_read():
                state = original_second_read()
                second_has_read.set()
                return state

            first._write_state = pause_first_write
            second._read_state = observe_second_read
            results = []
            errors = []

            def consume(store):
                try:
                    results.append(
                        store.consume(
                            token,
                            now=101,
                            chat_id="chat-1",
                            user_id="user-1",
                        )
                    )
                except BaseException as exc:
                    errors.append(exc)

            second_thread = threading.Thread(
                target=lambda: (
                    first_at_write.wait(),
                    consume(second),
                ),
            )
            first_thread = threading.Thread(target=consume, args=(first,))
            second_thread.start()
            first_thread.start()
            first_thread.join(2)
            second_thread.join(2)

            self.assertFalse(first_thread.is_alive())
            self.assertFalse(second_thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(
                sum(payload is not None for payload in results),
                1,
            )

    def test_two_store_instances_preserve_both_concurrent_creates(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "actions.json")
            first = WhitelistActionStore(
                path,
                token_factory=lambda: "created01",
            )
            second = WhitelistActionStore(
                path,
                token_factory=lambda: "created02",
            )
            first_at_write = threading.Event()
            second_has_read = threading.Event()
            original_first_write = first._write_state
            original_second_read = second._read_state

            def pause_first_write(state):
                first_at_write.set()
                second_has_read.wait(0.25)
                original_first_write(state)

            def observe_second_read():
                state = original_second_read()
                second_has_read.set()
                return state

            first._write_state = pause_first_write
            second._read_state = observe_second_read
            errors = []

            def create(store, address):
                try:
                    store.create(
                        kind="add_confirm",
                        address=address,
                        list_name="Suricata",
                        chat_id="chat-1",
                        user_id="user-1",
                        now=100,
                        ttl_seconds=300,
                    )
                except BaseException as exc:
                    errors.append(exc)

            second_thread = threading.Thread(
                target=lambda: (
                    first_at_write.wait(),
                    create(second, "192.168.98.201"),
                ),
            )
            first_thread = threading.Thread(
                target=create,
                args=(first, "192.168.98.200"),
            )
            second_thread.start()
            first_thread.start()
            first_thread.join(2)
            second_thread.join(2)

            self.assertFalse(first_thread.is_alive())
            self.assertFalse(second_thread.is_alive())
            self.assertEqual(errors, [])
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(persisted), {"created01", "created02"})

    def test_action_token_is_single_use_expiring_and_requester_bound(self):
        with TemporaryDirectory() as tmp:
            actions = WhitelistActionStore(
                Path(tmp, "actions.json"),
                token_factory=lambda: "token123",
            )
            token = actions.create(
                kind="add_confirm",
                address="192.168.98.200",
                list_name="Suricata",
                chat_id="chat-1",
                user_id="user-1",
                now=100,
                ttl_seconds=300,
                source_chat_id="chat-1",
                source_message_id=77,
                source_reply_markup={"inline_keyboard": []},
            )

            self.assertEqual(token, "token123")
            self.assertIsNone(
                actions.consume(
                    token,
                    now=101,
                    chat_id="chat-1",
                    user_id="other",
                )
            )
            self.assertIsNotNone(
                actions.consume(
                    token,
                    now=101,
                    chat_id="chat-1",
                    user_id="user-1",
                )
            )
            self.assertIsNone(
                actions.consume(
                    token,
                    now=102,
                    chat_id="chat-1",
                    user_id="user-1",
                )
            )

    def test_add_request_accepts_clicking_user_but_remains_chat_bound(self):
        with TemporaryDirectory() as tmp:
            actions = WhitelistActionStore(
                Path(tmp, "actions.json"),
                token_factory=lambda: "request1",
            )
            token = actions.create(
                kind="add_request",
                address="10.0.0.8",
                list_name="Suricata",
                chat_id="chat-1",
                user_id="",
                now=100,
                ttl_seconds=300,
            )

            self.assertIsNone(
                actions.consume(
                    token,
                    now=101,
                    chat_id="other",
                    user_id="admin-1",
                )
            )
            self.assertEqual(
                actions.consume(
                    token,
                    now=101,
                    chat_id="chat-1",
                    user_id="admin-1",
                )["kind"],
                "add_request",
            )

    def test_expired_token_is_removed_without_consuming_other_tokens(self):
        tokens = iter(("expired1", "current1"))
        with TemporaryDirectory() as tmp:
            actions = WhitelistActionStore(
                Path(tmp, "actions.json"),
                token_factory=lambda: next(tokens),
            )
            expired = actions.create(
                kind="add_confirm",
                address="172.16.0.8",
                list_name="Suricata",
                chat_id="chat-1",
                user_id="user-1",
                now=100,
                ttl_seconds=1,
            )
            current = actions.create(
                kind="remove_confirm",
                address="192.168.1.8",
                list_name="Suricata",
                chat_id="chat-1",
                user_id="user-1",
                now=100,
                ttl_seconds=300,
            )

            self.assertIsNone(
                actions.peek(
                    expired,
                    now=101,
                    chat_id="chat-1",
                    user_id="user-1",
                )
            )
            self.assertIsNotNone(
                actions.peek(
                    current,
                    now=101,
                    chat_id="chat-1",
                    user_id="user-1",
                )
            )

    def test_cancel_is_bound_single_use_and_persists_private_payload(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "actions.json")
            actions = WhitelistActionStore(path, token_factory=lambda: "cancel12")
            token = actions.create(
                kind="remove_confirm",
                address="192.168.98.200",
                list_name="Suricata",
                sid="2402000",
                chat_id="chat-1",
                user_id="user-1",
                now=100,
                ttl_seconds=300,
                source_chat_id="chat-1",
                source_message_id=77,
                source_reply_markup={"inline_keyboard": []},
            )

            payload = json.loads(path.read_text(encoding="utf-8"))[token]
            self.assertEqual(
                set(payload),
                {
                    "kind",
                    "address",
                    "list_name",
                    "sid",
                    "chat_id",
                    "user_id",
                    "created_at",
                    "expires_at",
                    "source_chat_id",
                    "source_message_id",
                    "source_reply_markup",
                },
            )
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            lock_path = path.with_name(f"{path.name}.lock")
            self.assertEqual(os.stat(lock_path).st_mode & 0o777, 0o600)
            self.assertFalse(
                actions.cancel(
                    token,
                    now=101,
                    chat_id="chat-1",
                    user_id="other",
                )
            )
            self.assertTrue(
                actions.cancel(
                    token,
                    now=101,
                    chat_id="chat-1",
                    user_id="user-1",
                )
            )
            self.assertFalse(
                actions.cancel(
                    token,
                    now=102,
                    chat_id="chat-1",
                    user_id="user-1",
                )
            )

    def test_rejects_non_rfc1918_and_invalid_requester_payloads(self):
        invalid_cases = (
            {"address": "8.8.8.8"},
            {"address": "192.168.0.0/24"},
            {"kind": "unknown"},
            {"chat_id": ""},
            {"kind": "add_confirm", "user_id": ""},
        )
        for overrides in invalid_cases:
            with self.subTest(overrides=overrides), TemporaryDirectory() as tmp:
                values = {
                    "kind": "add_confirm",
                    "address": "192.168.98.200",
                    "list_name": "Suricata",
                    "chat_id": "chat-1",
                    "user_id": "user-1",
                    "now": 100,
                    "ttl_seconds": 300,
                }
                values.update(overrides)
                actions = WhitelistActionStore(
                    Path(tmp, "actions.json"),
                    token_factory=lambda: "invalid1",
                )
                with self.assertRaises(ValueError):
                    actions.create(**values)

    def test_malformed_persisted_state_fails_closed(self):
        malformed_documents = (
            "{",
            json.dumps({"token123": {}}),
        )
        for document in malformed_documents:
            with self.subTest(document=document), TemporaryDirectory() as tmp:
                path = Path(tmp, "actions.json")
                path.write_text(document, encoding="utf-8")
                actions = WhitelistActionStore(path)

                with self.assertRaises(WhitelistActionStoreError):
                    actions.peek(
                        "token123",
                        now=101,
                        chat_id="chat-1",
                        user_id="user-1",
                    )

    def test_token_collision_fails_without_replacing_existing_action(self):
        with TemporaryDirectory() as tmp:
            actions = WhitelistActionStore(
                Path(tmp, "actions.json"),
                token_factory=lambda: "collision123",
            )
            actions.create(
                kind="add_confirm",
                address="192.168.98.200",
                list_name="Suricata",
                chat_id="chat-1",
                user_id="user-1",
                now=100,
                ttl_seconds=300,
            )

            with self.assertRaisesRegex(ValueError, "collision"):
                actions.create(
                    kind="add_confirm",
                    address="192.168.98.201",
                    list_name="Suricata",
                    chat_id="chat-1",
                    user_id="user-1",
                    now=101,
                    ttl_seconds=300,
                )

            payload = actions.peek(
                "collision123",
                now=102,
                chat_id="chat-1",
                user_id="user-1",
            )
            self.assertEqual(payload["address"], "192.168.98.200")

    def test_parse_whitelist_callback_accepts_only_approved_namespace(self):
        approved = {
            "add-request",
            "add-confirm",
            "remove-request",
            "remove-confirm",
            "retry-unblock",
            "cancel",
        }
        for action in approved:
            with self.subTest(action=action):
                self.assertEqual(
                    parse_whitelist_callback(
                        f"whitelist:v1:{action}:token123"
                    ),
                    (action, "token123"),
                )

        for data in (
            "whitelist:v2:add-request:token123",
            "whitelist:v1:add:token123",
            "whitelist:v1:add-request:short",
            "whitelist:v1:add-request:token123:extra",
            None,
        ):
            with self.subTest(data=data):
                self.assertIsNone(parse_whitelist_callback(data))

    def test_longest_callback_accepts_24_byte_token_below_telegram_limit(self):
        token = "A" * 24
        callback = f"whitelist:v1:remove-confirm:{token}"

        self.assertEqual(
            parse_whitelist_callback(callback),
            ("remove-confirm", token),
        )
        self.assertEqual(len(callback.encode("utf-8")), 52)
        self.assertLessEqual(len(callback.encode("utf-8")), 64)
        self.assertIsNone(
            parse_whitelist_callback(
                f"whitelist:v1:remove-confirm:{token}A"
            )
        )

    def test_append_exception_action_keeps_existing_rows(self):
        existing = build_unblock_keyboard(
            "192.168.98.200",
            "unblock-token",
        )

        markup = append_managed_exception_button(
            existing,
            address="192.168.98.200",
            token="whitelist-token",
        )

        rows = markup["inline_keyboard"]
        self.assertEqual(
            rows[0][0]["text"],
            "🔓 Unblock 192.168.98.200",
        )
        self.assertEqual(
            [button["text"] for button in rows[1]],
            ["AbuseIPDB", "VirusTotal"],
        )
        self.assertEqual(
            rows[2][0]["text"],
            "🛡 Добавить в исключения 192.168.98.200",
        )
        self.assertEqual(
            rows[2][0]["callback_data"],
            "whitelist:v1:add-request:whitelist-token",
        )
        self.assertEqual(len(existing["inline_keyboard"]), 2)

    def test_build_confirm_keyboard_uses_approved_add_and_cancel_callbacks(self):
        markup = build_whitelist_confirm_keyboard("token123")

        self.assertEqual(
            markup,
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ Добавить и разблокировать",
                            "callback_data": "whitelist:v1:add-confirm:token123",
                        }
                    ],
                    [
                        {
                            "text": "❌ Отмена",
                            "callback_data": "whitelist:v1:cancel:token123",
                        }
                    ],
                ]
            },
        )


class RecordingStore:
    def __init__(self, events=None, addresses=()):
        self.events = events if events is not None else []
        self.addresses = set(addresses)
        self.add_calls = 0
        self.remove_calls = 0

    def snapshot(self):
        return tuple(sorted(self.addresses))

    def contains(self, address):
        return address in self.addresses

    def add(self, address):
        self.add_calls += 1
        self.events.append(f"store:add:{address}")
        changed = address not in self.addresses
        self.addresses.add(address)
        return changed

    def remove(self, address):
        self.remove_calls += 1
        self.events.append(f"store:remove:{address}")
        changed = address in self.addresses
        self.addresses.discard(address)
        return changed


class FailingStore(RecordingStore):
    def add(self, address):
        self.add_calls += 1
        self.events.append(f"store:add:{address}")
        raise OSError("disk full")


class RecordingAddressList:
    def __init__(self, owner):
        self.owner = owner

    def select(self, *_keys):
        return self

    def where(self, *_filters):
        return ([{".id": "*1"}] if self.owner.removed else [])

    def remove(self, _row_id):
        self.owner.events.append(
            f"router:remove:{self.owner.expected_address}"
        )


class RecordingRouter:
    def __init__(self, events=None, *, removed=1):
        self.events = events if events is not None else []
        self.removed = removed
        self.expected_address = "192.168.98.200"
        self.run_calls = 0
        self.address_list = RecordingAddressList(self)

    def paths(self):
        return self.address_list, None, ()

    def run_with_reconnect(self, operation_name, callback):
        self.run_calls += 1
        if operation_name != "telegram managed whitelist unblock":
            raise AssertionError(operation_name)
        return callback()


class FailingRouter(RecordingRouter):
    def run_with_reconnect(self, operation_name, callback):
        self.run_calls += 1
        raise ConnectionError("router unavailable")


class ForgedActions:
    def __init__(self, payload):
        self.payload = dict(payload)
        self.consume_calls = 0

    def consume(self, *_args, **_kwargs):
        self.consume_calls += 1
        return dict(self.payload)


def sample_event():
    return {"alert": {"signature_id": 2402000}}


def admin_auth():
    return BotAuth(
        BotSettings(admin_chat_ids=("chat-1",)),
        legacy_chat_id="",
    )


def callback(
    data,
    *,
    chat_id="chat-1",
    user_id="user-1",
    message_id=77,
    reply_markup=None,
):
    message = {
        "message_id": message_id,
        "chat": {"id": chat_id},
    }
    if reply_markup is not None:
        message["reply_markup"] = reply_markup
    return {
        "id": "cb-1",
        "data": data,
        "message": message,
        "from": {"id": user_id},
    }


def execute_callback(token):
    return callback(f"whitelist:v1:add-confirm:{token}")


def retry_callback(token):
    return callback(f"whitelist:v1:retry-unblock:{token}")


def read_audit(handler):
    lines = Path(handler.audit.path).read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


def last_answer(handler):
    args = handler.answer_callback.call_args.args
    return args[1], args[2]


def make_handler(
    tmp,
    *,
    store=None,
    router=None,
    actions=None,
    dry_run=False,
    control_enabled=True,
    unblock_enabled=True,
    admin_chat_ids=("chat-1",),
):
    resolved_store = store or RecordingStore()
    resolved_router = router or RecordingRouter()
    token_values = iter(
        (
            "request001",
            "confirm001",
            "remove001",
            "retry0001",
            "retry0002",
            "extra0001",
        )
    )
    resolved_actions = actions or WhitelistActionStore(
        Path(tmp, "actions.json"),
        token_factory=lambda: next(token_values),
    )
    settings = Settings(
        enable_telegram=True,
        telegram_token="token",
        telegram_chatid="chat-1",
        telegram_unblock_enable=unblock_enabled,
        telegram_whitelist_control_enable=control_enabled,
        telegram_unblock_ttl_seconds=300,
        block_list_name="Suricata",
    )
    bot_settings = BotSettings(
        dry_run=dry_run,
        admin_chat_ids=admin_chat_ids,
        modules=("whitelist_control",),
        audit_log=str(Path(tmp, "audit.jsonl")),
    )
    router_factory = Mock(return_value=resolved_router)
    handler = TelegramWhitelistHandler(
        settings,
        bot_settings=bot_settings,
        store=resolved_store,
        policy=WhitelistPolicy(("10.0.0.0/8",), resolved_store),
        actions=resolved_actions,
        audit=BotAuditLog(Path(bot_settings.audit_log)),
        get_router_client=router_factory,
        log=Mock(),
    )
    handler.router = router_factory
    handler.answer_callback = Mock()
    handler.send_message = Mock(
        return_value=types.SimpleNamespace(ok=True, retryable=False)
    )
    handler.edit_message = Mock(
        return_value=types.SimpleNamespace(ok=True, retryable=False)
    )
    handler.edit_markup = Mock(
        return_value=types.SimpleNamespace(ok=True, retryable=False)
    )
    return handler


def create_action(
    handler,
    *,
    kind="add_confirm",
    address="192.168.98.200",
    now=100,
    ttl_seconds=300,
    source_reply_markup=None,
):
    return handler.actions.create(
        kind=kind,
        address=address,
        list_name="Suricata",
        sid="2402000",
        chat_id="chat-1",
        user_id="user-1",
        now=now,
        ttl_seconds=ttl_seconds,
        source_chat_id="chat-1",
        source_message_id=77,
        source_reply_markup=source_reply_markup
        or build_unblock_keyboard(address, "unblock-token"),
    )


def dispatch_whitelist_callback(handler, callback_value, *, now=101, auth=None):
    return handler.handle_callback(
        callback=callback_value,
        auth=auth or admin_auth(),
        answer_callback=handler.answer_callback,
        send_message=handler.send_message,
        edit_message=handler.edit_message,
        edit_reply_markup=handler.edit_markup,
        telegram_token="token",
        timeout=7,
        now=now,
    )


class TelegramWhitelistHandlerTests(TestCase):
    def test_add_persists_before_routeros_remove_and_updates_only_markup(self):
        with TemporaryDirectory() as tmp:
            events = []
            store = RecordingStore(events)
            router = RecordingRouter(events, removed=1)
            handler = make_handler(
                tmp,
                store=store,
                router=router,
                dry_run=False,
            )
            token = create_action(handler)

            handled = dispatch_whitelist_callback(
                handler,
                execute_callback(token),
            )

            self.assertTrue(handled)
            self.assertEqual(
                events[:2],
                [
                    "store:add:192.168.98.200",
                    "router:remove:192.168.98.200",
                ],
            )
            self.assertTrue(store.contains("192.168.98.200"))
            self.assertIn(
                "✅ В исключениях 192.168.98.200",
                json.dumps(
                    handler.edit_markup.call_args.kwargs,
                    ensure_ascii=False,
                ),
            )
            handler.edit_message.assert_not_called()
            self.assertEqual(read_audit(handler)["outcome"], "success")
            self.assertEqual(
                last_answer(handler),
                ("Исключение добавлено, адрес разблокирован", False),
            )

    def test_persistence_failure_never_calls_routeros(self):
        with TemporaryDirectory() as tmp:
            store = FailingStore()
            handler = make_handler(tmp, store=store, router=RecordingRouter())
            token = create_action(handler)

            dispatch_whitelist_callback(handler, execute_callback(token))

            handler.router.assert_not_called()
            self.assertEqual(store.snapshot(), ())
            self.assertEqual(read_audit(handler)["outcome"], "failure")
            self.assertEqual(
                last_answer(handler),
                ("Не удалось сохранить исключение", True),
            )

    def test_routeros_failure_keeps_exception_and_offers_removal_only_retry(self):
        with TemporaryDirectory() as tmp:
            store = DynamicWhitelistStore(Path(tmp, "whitelist.json"))
            router = FailingRouter()
            handler = make_handler(tmp, store=store, router=router)
            token = create_action(handler)

            dispatch_whitelist_callback(handler, execute_callback(token))

            self.assertTrue(store.contains("192.168.98.200"))
            markup = handler.edit_markup.call_args.kwargs["reply_markup"]
            text = json.dumps(markup, ensure_ascii=False)
            self.assertIn("✅ В исключениях 192.168.98.200", text)
            self.assertIn("🔄 Повторить разблокировку", text)
            self.assertEqual(read_audit(handler)["outcome"], "partial")
            self.assertEqual(
                last_answer(handler),
                ("Исключение сохранено, разблокировка не выполнена", True),
            )

    def test_dry_run_changes_neither_store_nor_routeros(self):
        with TemporaryDirectory() as tmp:
            handler = make_handler(tmp, dry_run=True)
            token = create_action(handler)

            dispatch_whitelist_callback(handler, execute_callback(token))

            self.assertEqual(handler.store.snapshot(), ())
            handler.router.assert_not_called()
            self.assertEqual(read_audit(handler)["outcome"], "dry-run")
            self.assertEqual(
                last_answer(handler),
                (
                    "Dry-run: исключение не добавлено, адрес не разблокирован",
                    False,
                ),
            )

    def test_remove_only_changes_managed_store(self):
        with TemporaryDirectory() as tmp:
            store = RecordingStore(addresses=("192.168.98.200",))
            handler = make_handler(tmp, store=store)
            token = create_action(handler, kind="remove_confirm")

            dispatch_whitelist_callback(
                handler,
                callback(f"whitelist:v1:remove-confirm:{token}"),
            )

            self.assertFalse(handler.store.contains("192.168.98.200"))
            handler.router.assert_not_called()
            self.assertEqual(store.add_calls, 0)
            self.assertEqual(store.remove_calls, 1)
            self.assertEqual(read_audit(handler)["outcome"], "success")
            self.assertEqual(
                last_answer(handler),
                ("Исключение удалено", False),
            )

    def test_alert_extension_requires_private_ip_admin_and_both_features(self):
        cases = (
            ("192.168.98.200", True, True, ("chat-1",), "BLOCKED", True),
            ("8.8.8.8", True, True, ("chat-1",), "BLOCKED", False),
            ("192.168.98.200", False, True, ("chat-1",), "BLOCKED", False),
            ("192.168.98.200", True, False, ("chat-1",), "BLOCKED", False),
            ("192.168.98.200", True, True, ("other",), "BLOCKED", False),
            ("192.168.98.200", True, True, ("chat-1",), "MONITOR", False),
        )
        for address, control, unblock, admins, action_type, expected in cases:
            with self.subTest(
                address=address,
                control=control,
                action_type=action_type,
            ), TemporaryDirectory() as tmp:
                handler = make_handler(
                    tmp,
                    control_enabled=control,
                    unblock_enabled=unblock,
                    admin_chat_ids=admins,
                )
                markup = handler.extend_alert_keyboard(
                    build_unblock_keyboard(address, "unblock-token"),
                    event=sample_event(),
                    wanted_ip=address,
                    action_type=action_type,
                    now=100,
                )
                self.assertEqual(
                    "Добавить в исключения"
                    in json.dumps(markup, ensure_ascii=False),
                    expected,
                )

    def test_execute_rechecks_admin_and_feature_flags_before_consume(self):
        for case in ("admin", "control", "unblock"):
            with self.subTest(case=case), TemporaryDirectory() as tmp:
                handler = make_handler(tmp)
                token = create_action(handler)
                if case == "admin":
                    auth = BotAuth(BotSettings(), legacy_chat_id="")
                else:
                    auth = admin_auth()
                    object.__setattr__(
                        handler.settings,
                        (
                            "telegram_whitelist_control_enable"
                            if case == "control"
                            else "telegram_unblock_enable"
                        ),
                        False,
                    )

                dispatch_whitelist_callback(
                    handler,
                    execute_callback(token),
                    auth=auth,
                )

                self.assertEqual(handler.store.snapshot(), ())
                handler.router.assert_not_called()
                self.assertEqual(read_audit(handler)["outcome"], "denied")
                self.assertIsNotNone(
                    handler.actions.peek(
                        token,
                        now=102,
                        chat_id="chat-1",
                        user_id="user-1",
                    )
                )
                expected_answer = {
                    "admin": ("Unauthorized", True),
                    "control": ("Функция недоступна", True),
                    "unblock": ("Разблокировка недоступна", True),
                }[case]
                self.assertEqual(last_answer(handler), expected_answer)

    def test_execute_rejects_public_address_from_forged_token(self):
        with TemporaryDirectory() as tmp:
            store = RecordingStore()
            actions = ForgedActions(
                {
                    "kind": "add_confirm",
                    "address": "8.8.8.8",
                    "list_name": "Suricata",
                    "sid": "1",
                    "chat_id": "chat-1",
                    "user_id": "user-1",
                    "source_chat_id": "chat-1",
                    "source_message_id": 77,
                    "source_reply_markup": {"inline_keyboard": []},
                }
            )
            handler = make_handler(tmp, store=store, actions=actions)

            dispatch_whitelist_callback(
                handler,
                execute_callback("forged001"),
            )

            self.assertEqual(store.snapshot(), ())
            self.assertEqual(store.add_calls, 0)
            handler.router.assert_not_called()
            self.assertEqual(
                last_answer(handler),
                ("Недопустимый адрес исключения", True),
            )

    def test_expired_and_replayed_tokens_do_not_mutate(self):
        with TemporaryDirectory() as tmp:
            store = RecordingStore()
            handler = make_handler(tmp, store=store)
            expired = create_action(handler, now=100, ttl_seconds=1)

            dispatch_whitelist_callback(
                handler,
                execute_callback(expired),
                now=101,
            )
            self.assertEqual(store.snapshot(), ())
            self.assertEqual(store.add_calls, 0)
            self.assertEqual(store.remove_calls, 0)
            handler.router.assert_not_called()
            valid = create_action(handler, now=200)
            dispatch_whitelist_callback(
                handler,
                execute_callback(valid),
                now=201,
            )
            store_events_after_success = list(store.events)
            router_calls_after_success = handler.router.call_count
            dispatch_whitelist_callback(
                handler,
                execute_callback(valid),
                now=202,
            )

            self.assertEqual(
                store.events,
                store_events_after_success,
            )
            self.assertEqual(
                handler.router.call_count,
                router_calls_after_success,
            )
            self.assertEqual(
                last_answer(handler),
                ("Запрос истёк или уже использован", True),
            )
            outcomes = [
                json.loads(line)["outcome"]
                for line in Path(handler.audit.path)
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(outcomes[0], "stale")
            self.assertEqual(outcomes[-1], "stale")

    def test_cancel_consumes_token_without_mutation(self):
        with TemporaryDirectory() as tmp:
            store = RecordingStore()
            handler = make_handler(tmp, store=store)
            token = create_action(handler)

            dispatch_whitelist_callback(
                handler,
                callback(f"whitelist:v1:cancel:{token}"),
            )

            self.assertEqual(store.snapshot(), ())
            self.assertEqual(store.add_calls, 0)
            self.assertEqual(store.remove_calls, 0)
            handler.router.assert_not_called()
            self.assertIsNone(
                handler.actions.peek(
                    token,
                    now=102,
                    chat_id="chat-1",
                    user_id="user-1",
                )
            )
            self.assertEqual(read_audit(handler)["outcome"], "cancelled")
            self.assertEqual(last_answer(handler), ("Отменено", False))

    def test_add_existing_address_is_idempotent(self):
        with TemporaryDirectory() as tmp:
            store = RecordingStore(addresses=("192.168.98.200",))
            router = RecordingRouter(removed=0)
            handler = make_handler(tmp, store=store, router=router)
            token = create_action(handler)

            dispatch_whitelist_callback(handler, execute_callback(token))

            self.assertEqual(store.snapshot(), ("192.168.98.200",))
            self.assertEqual(store.add_calls, 1)
            self.assertEqual(router.run_calls, 1)
            self.assertEqual(read_audit(handler)["outcome"], "success")
            self.assertEqual(
                last_answer(handler),
                ("Адрес уже в исключениях; блокировка не найдена", False),
            )

    def test_remove_missing_address_is_idempotent(self):
        with TemporaryDirectory() as tmp:
            store = RecordingStore()
            handler = make_handler(tmp, store=store)
            token = create_action(handler, kind="remove_confirm")

            dispatch_whitelist_callback(
                handler,
                callback(f"whitelist:v1:remove-confirm:{token}"),
            )

            self.assertEqual(store.snapshot(), ())
            self.assertEqual(store.remove_calls, 0)
            handler.router.assert_not_called()
            self.assertEqual(read_audit(handler)["outcome"], "noop")
            self.assertEqual(
                last_answer(handler),
                ("Исключение уже отсутствует", False),
            )

    def test_retry_unblock_never_rewrites_or_removes_store(self):
        with TemporaryDirectory() as tmp:
            store = RecordingStore(addresses=("192.168.98.200",))
            router = RecordingRouter(removed=1)
            handler = make_handler(tmp, store=store, router=router)
            token = create_action(handler, kind="retry_unblock")

            dispatch_whitelist_callback(handler, retry_callback(token))

            self.assertEqual(store.snapshot(), ("192.168.98.200",))
            self.assertEqual(store.add_calls, 0)
            self.assertEqual(store.remove_calls, 0)
            self.assertEqual(router.run_calls, 1)
            self.assertEqual(read_audit(handler)["outcome"], "success")
            self.assertEqual(
                last_answer(handler),
                ("Адрес разблокирован", False),
            )

    def test_post_mutation_edit_failure_sends_result_without_second_mutation(self):
        with TemporaryDirectory() as tmp:
            store = RecordingStore()
            router = RecordingRouter(removed=1)
            handler = make_handler(tmp, store=store, router=router)
            handler.edit_markup.return_value = types.SimpleNamespace(
                ok=False,
                retryable=False,
            )
            token = create_action(handler)

            dispatch_whitelist_callback(handler, execute_callback(token))

            self.assertEqual(store.add_calls, 1)
            self.assertEqual(router.run_calls, 1)
            handler.send_message.assert_called_once()
            self.assertIn(
                "Исключение добавлено",
                handler.send_message.call_args.kwargs["text"],
            )
            self.assertEqual(read_audit(handler)["outcome"], "success")
            self.assertEqual(
                last_answer(handler),
                ("Исключение добавлено, адрес разблокирован", False),
            )

    def test_add_request_binds_confirm_to_clicker_and_preserves_alert_source(self):
        with TemporaryDirectory() as tmp:
            handler = make_handler(tmp)
            markup = handler.extend_alert_keyboard(
                build_unblock_keyboard(
                    "192.168.98.200",
                    "unblock-token",
                ),
                event=sample_event(),
                wanted_ip="192.168.98.200",
                action_type="BLOCKED",
                now=100,
            )
            request_data = markup["inline_keyboard"][-1][0]["callback_data"]

            dispatch_whitelist_callback(
                handler,
                callback(
                    request_data,
                    reply_markup=markup,
                ),
            )

            confirm_markup = handler.send_message.call_args.kwargs[
                "reply_markup"
            ]
            confirm_data = confirm_markup["inline_keyboard"][0][0][
                "callback_data"
            ]
            _prefix, token = confirm_data.rsplit(":", 1)
            payload = handler.actions.peek(
                token,
                now=102,
                chat_id="chat-1",
                user_id="user-1",
            )
            self.assertEqual(payload["kind"], "add_confirm")
            self.assertEqual(payload["source_message_id"], 77)
            self.assertEqual(payload["source_reply_markup"], markup)
            self.assertEqual(handler.store.snapshot(), ())
            handler.router.assert_not_called()

    def test_remove_request_is_read_only_until_confirmation(self):
        with TemporaryDirectory() as tmp:
            store = RecordingStore(addresses=("192.168.98.200",))
            handler = make_handler(tmp, store=store)
            view = handler.menu_view(
                page=0,
                chat_id="chat-1",
                user_id="user-1",
                now=100,
            )
            remove_data = next(
                button["callback_data"]
                for row in view.reply_markup["inline_keyboard"]
                for button in row
                if button["callback_data"].startswith(
                    "whitelist:v1:remove-request:"
                )
            )

            dispatch_whitelist_callback(
                handler,
                callback(remove_data),
            )

            self.assertEqual(store.snapshot(), ("192.168.98.200",))
            handler.router.assert_not_called()
            self.assertIn(
                "Удалить 192.168.98.200",
                handler.edit_message.call_args.kwargs["text"],
            )
