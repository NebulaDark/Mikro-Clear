import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from unittest import TestCase

from mikroclear.telegram.unblock import build_unblock_keyboard
from mikroclear.telegram.whitelist_actions import (
    WhitelistActionStore,
    WhitelistActionStoreError,
    append_managed_exception_button,
    build_whitelist_confirm_keyboard,
    parse_whitelist_callback,
)


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
