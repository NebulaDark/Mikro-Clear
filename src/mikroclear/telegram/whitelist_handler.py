"""Telegram workflow for persistent managed whitelist exceptions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from mikroclear.bot.audit import BotAuditLog
from mikroclear.bot.menu import MenuView
from mikroclear.bot.modules.exceptions import build_exceptions_view
from mikroclear.bot.settings import BotSettings
from mikroclear.routeros.address_list import remove_from_address_list
from mikroclear.state.dynamic_whitelist import is_managed_private_ipv4
from mikroclear.telegram.formatting import escape_html_safe
from mikroclear.telegram.whitelist_actions import (
    WhitelistActionStore,
    WhitelistActionStoreError,
    append_managed_exception_button,
    build_whitelist_confirm_keyboard,
    parse_whitelist_callback,
)


@dataclass(frozen=True)
class WhitelistMutationResult:
    outcome: str
    managed: bool
    removed: bool
    changed: bool = False


class TelegramWhitelistHandler:
    def __init__(
        self,
        settings: Any,
        *,
        bot_settings: BotSettings,
        store: Any,
        policy: Any,
        actions: WhitelistActionStore,
        audit: BotAuditLog,
        get_router_client: Callable[[], Any],
        log: Callable[[str], None],
        action_ttl_seconds: int | None = None,
    ) -> None:
        self.settings = settings
        self.bot_settings = bot_settings
        self.store = store
        self.policy = policy
        self.actions = actions
        self.audit = audit
        self.get_router_client = get_router_client
        self.log = log
        self.action_ttl_seconds = int(
            action_ttl_seconds
            if action_ttl_seconds is not None
            else getattr(settings, "telegram_unblock_ttl_seconds", 300)
        )

    def extend_alert_keyboard(
        self,
        reply_markup: dict[str, Any],
        event: dict[str, Any],
        wanted_ip: str,
        action_type: str,
        now: int,
    ) -> dict[str, Any]:
        """Append an add action without modifying existing alert rows."""

        address = str(wanted_ip)
        chat_id = str(getattr(self.settings, "telegram_chatid", ""))
        if not (
            isinstance(event, dict)
            and is_managed_private_ipv4(address)
            and action_type in {"BLOCKED", "UPDATED"}
            and self._control_enabled()
            and bool(getattr(self.settings, "telegram_unblock_enable", False))
            and chat_id in self.bot_settings.admin_chat_ids
        ):
            return reply_markup
        if self.store.contains(address):
            return self._result_markup(
                reply_markup,
                address=address,
                retry_token=None,
            )
        if self.policy.contains(address):
            return reply_markup

        alert = event.get("alert") or {}
        sid = (
            str(alert.get("signature_id", "N/A"))
            if isinstance(alert, dict)
            else "N/A"
        )
        try:
            token = self.actions.create(
                kind="add_request",
                address=address,
                list_name=str(self.settings.block_list_name),
                sid=sid,
                chat_id=chat_id,
                user_id="",
                now=int(now),
                ttl_seconds=self.action_ttl_seconds,
            )
        except Exception as exc:
            self.log(
                "TELEGRAM WHITELIST ACTION CREATE FAILED: "
                f"{type(exc).__name__}"
            )
            return reply_markup
        return append_managed_exception_button(
            reply_markup,
            address=address,
            token=token,
        )

    def menu_view(
        self,
        *,
        page: int,
        chat_id: str,
        user_id: str,
        now: int,
    ) -> MenuView:
        return build_exceptions_view(
            self.policy.system_entries,
            self.store.snapshot(),
            page=page,
            page_size=8,
            remove_token_factory=lambda address: self.actions.create(
                kind="remove_confirm",
                address=address,
                list_name=str(self.settings.block_list_name),
                chat_id=str(chat_id),
                user_id=str(user_id),
                now=int(now),
                ttl_seconds=self.action_ttl_seconds,
            ),
        )

    def handle_callback(
        self,
        callback: dict[str, Any],
        auth: Any,
        answer_callback: Callable[[str, str, bool], Any],
        send_message: Callable[..., Any],
        edit_message: Callable[..., Any],
        edit_reply_markup: Callable[..., Any],
        telegram_token: str,
        timeout: int,
        now: int,
    ) -> bool:
        parsed = parse_whitelist_callback(callback.get("data"))
        if parsed is None:
            return False

        action_name, token = parsed
        callback_id, chat_id, user_id, message_id, message_markup = (
            self._callback_context(callback)
        )
        if not auth.can_write(chat_id):
            self._record(
                "whitelist.callback",
                "denied",
                chat_id,
                user_id,
                "",
                action_name,
            )
            answer_callback(callback_id, "Unauthorized", True)
            return True
        if not self._control_enabled():
            self._record(
                "whitelist.callback",
                "denied",
                chat_id,
                user_id,
                "",
                "control disabled",
            )
            answer_callback(callback_id, "Функция недоступна", True)
            return True
        if action_name in {
            "add-request",
            "add-confirm",
            "retry-unblock",
        } and not bool(
            getattr(self.settings, "telegram_unblock_enable", False)
        ):
            self._record(
                "whitelist.callback",
                "denied",
                chat_id,
                user_id,
                "",
                "unblock disabled",
            )
            answer_callback(callback_id, "Разблокировка недоступна", True)
            return True

        expected_kinds = {
            "add-request": {"add_request", "add_confirm"},
            "remove-request": {"remove_confirm"},
            "add-confirm": {"add_confirm"},
            "remove-confirm": {"remove_confirm"},
            "retry-unblock": {"retry_unblock"},
            "cancel": {"add_confirm", "remove_confirm"},
        }[action_name]
        payload = self._peek(
            token,
            now=now,
            chat_id=chat_id,
            user_id=user_id,
        )
        if payload is None or payload.get("kind") not in expected_kinds:
            self._stale(
                callback_id,
                chat_id,
                user_id,
                answer_callback,
                action_name,
            )
            return True
        address = str(payload.get("address", ""))
        if not is_managed_private_ipv4(address):
            self._record(
                f"whitelist.{action_name}",
                "invalid",
                chat_id,
                user_id,
                address,
            )
            answer_callback(
                callback_id,
                "Недопустимый адрес исключения",
                True,
            )
            return True

        answer_callback(callback_id, "", False)

        if action_name == "add-request":
            return self._handle_add_request(
                token,
                payload=payload,
                chat_id=chat_id,
                user_id=user_id,
                message_id=message_id,
                message_markup=message_markup,
                send_message=send_message,
                telegram_token=telegram_token,
                timeout=timeout,
                now=now,
            )
        if action_name == "remove-request":
            return self._handle_remove_request(
                token,
                payload=payload,
                chat_id=chat_id,
                message_id=message_id,
                send_message=send_message,
                edit_message=edit_message,
                telegram_token=telegram_token,
                timeout=timeout,
                now=now,
            )
        if action_name == "cancel":
            return self._handle_cancel(
                token,
                chat_id=chat_id,
                user_id=user_id,
                send_message=send_message,
                telegram_token=telegram_token,
                timeout=timeout,
                now=now,
            )

        payload = self._consume(
            token,
            now=now,
            chat_id=chat_id,
            user_id=user_id,
        )
        if payload is None or payload.get("kind") not in expected_kinds:
            self._deliver_factual_message(
                send_message,
                telegram_token=telegram_token,
                chat_id=chat_id,
                text="Запрос истёк или уже использован",
                timeout=timeout,
                log_prefix="TELEGRAM WHITELIST CONSUME RACE DELIVERY FAILED",
            )
            return True

        if action_name == "add-confirm":
            result = self._execute_add(
                payload,
                chat_id=chat_id,
                user_id=user_id,
            )
            text, _alert = self._add_answer(result)
            if result.outcome in {"success", "partial"}:
                retry_token = (
                    self._create_retry(
                        payload,
                        chat_id=chat_id,
                        user_id=user_id,
                        now=now,
                    )
                    if result.outcome == "partial"
                    else None
                )
                self._deliver_alert_result(
                    payload,
                    address=address,
                    retry_token=retry_token,
                    result_text=text,
                    current_chat_id=chat_id,
                    current_message_id=message_id,
                    edit_reply_markup=edit_reply_markup,
                    send_message=send_message,
                    telegram_token=telegram_token,
                    timeout=timeout,
                )
            else:
                self._deliver_factual_message(
                    send_message,
                    telegram_token=telegram_token,
                    chat_id=chat_id,
                    text=text,
                    timeout=timeout,
                    log_prefix=(
                        "TELEGRAM WHITELIST ADD RESULT SEND FAILED"
                    ),
                )
            return True

        if action_name == "retry-unblock":
            result = self._execute_retry(
                payload,
                chat_id=chat_id,
                user_id=user_id,
            )
            text, _alert = self._retry_answer(result)
            retry_token = (
                self._create_retry(
                    payload,
                    chat_id=chat_id,
                    user_id=user_id,
                    now=now,
                )
                if result.outcome == "partial"
                else None
            )
            if result.outcome in {"success", "partial"}:
                self._deliver_alert_result(
                    payload,
                    address=address,
                    retry_token=retry_token,
                    result_text=text,
                    current_chat_id=chat_id,
                    current_message_id=message_id,
                    edit_reply_markup=edit_reply_markup,
                    send_message=send_message,
                    telegram_token=telegram_token,
                    timeout=timeout,
                )
            else:
                self._deliver_factual_message(
                    send_message,
                    telegram_token=telegram_token,
                    chat_id=chat_id,
                    text=text,
                    timeout=timeout,
                    log_prefix=(
                        "TELEGRAM WHITELIST RETRY RESULT SEND FAILED"
                    ),
                )
            return True

        self._execute_remove(
            payload,
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            send_message=send_message,
            edit_message=edit_message,
            telegram_token=telegram_token,
            timeout=timeout,
            now=now,
        )
        return True

    def _handle_add_request(
        self,
        token: str,
        *,
        payload: dict[str, Any],
        chat_id: str,
        user_id: str,
        message_id: Any,
        message_markup: Any,
        send_message: Callable[..., Any],
        telegram_token: str,
        timeout: int,
        now: int,
    ) -> bool:
        address = str(payload["address"])
        try:
            promoted = self.actions.promote_add_request(
                token,
                now=int(now),
                chat_id=chat_id,
                user_id=user_id,
                source_chat_id=chat_id,
                source_message_id=(
                    int(message_id)
                    if type(message_id) is int
                    else None
                ),
                source_reply_markup=message_markup,
            )
        except Exception as exc:
            self._record(
                "whitelist.add",
                "failure",
                chat_id,
                user_id,
                address,
                type(exc).__name__,
            )
            self._deliver_factual_message(
                send_message,
                telegram_token=telegram_token,
                chat_id=chat_id,
                text="Не удалось создать подтверждение",
                timeout=timeout,
                log_prefix=(
                    "TELEGRAM WHITELIST CONFIRM CREATE DELIVERY FAILED"
                ),
            )
            return True
        if promoted is None:
            self._deliver_factual_message(
                send_message,
                telegram_token=telegram_token,
                chat_id=chat_id,
                text="Запрос истёк или уже использован",
                timeout=timeout,
                log_prefix=(
                    "TELEGRAM WHITELIST PROMOTION RACE DELIVERY FAILED"
                ),
            )
            return True
        if self.store.contains(address):
            response = send_message(
                token=telegram_token,
                chat_id=chat_id,
                text="Адрес уже в исключениях",
                timeout=timeout,
            )
            if getattr(response, "ok", True) is False:
                self.log("TELEGRAM WHITELIST EXISTING RESULT SEND FAILED")
            return True
        response = send_message(
            token=telegram_token,
            chat_id=chat_id,
            text=(
                f"Добавить <code>{escape_html_safe(address)}</code> "
                "в постоянные исключения\n"
                f"и удалить из RouterOS "
                f"<code>{escape_html_safe(payload['list_name'])}</code>?"
            ),
            reply_markup=build_whitelist_confirm_keyboard(token),
            timeout=timeout,
        )
        if getattr(response, "ok", True) is False:
            self.log("TELEGRAM WHITELIST CONFIRM SEND FAILED")
        return True

    def _handle_remove_request(
        self,
        token: str,
        *,
        payload: dict[str, Any],
        chat_id: str,
        message_id: Any,
        send_message: Callable[..., Any],
        edit_message: Callable[..., Any],
        telegram_token: str,
        timeout: int,
        now: int,
    ) -> bool:
        address = str(payload["address"])
        if not self.store.contains(address):
            response = send_message(
                token=telegram_token,
                chat_id=chat_id,
                text="Исключение уже отсутствует",
                timeout=timeout,
            )
            if getattr(response, "ok", True) is False:
                self.log("TELEGRAM WHITELIST MISSING RESULT SEND FAILED")
            return True
        view = MenuView(
            (
                f"Удалить {escape_html_safe(address)} "
                "из управляемых исключений?\n\n"
                "Адрес не будет заблокирован немедленно."
            ),
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ Удалить исключение",
                            "callback_data": (
                                "whitelist:v1:remove-confirm:"
                                f"{token}"
                            ),
                        }
                    ],
                    [
                        {
                            "text": "❌ Отмена",
                            "callback_data": f"whitelist:v1:cancel:{token}",
                        }
                    ],
                ]
            },
        )
        self._edit_or_send(
            view,
            chat_id=chat_id,
            message_id=message_id,
            edit_message=edit_message,
            send_message=send_message,
            telegram_token=telegram_token,
            timeout=timeout,
        )
        return True

    def _handle_cancel(
        self,
        token: str,
        *,
        chat_id: str,
        user_id: str,
        send_message: Callable[..., Any],
        telegram_token: str,
        timeout: int,
        now: int,
    ) -> bool:
        payload = self._consume(
            token,
            now=now,
            chat_id=chat_id,
            user_id=user_id,
        )
        if payload is None:
            self._deliver_factual_message(
                send_message,
                telegram_token=telegram_token,
                chat_id=chat_id,
                text="Запрос истёк или уже использован",
                timeout=timeout,
                log_prefix="TELEGRAM WHITELIST CANCEL RACE DELIVERY FAILED",
            )
            return True
        address = str(payload.get("address", ""))
        self._record(
            "whitelist.cancel",
            "cancelled",
            chat_id,
            user_id,
            address,
        )
        self._deliver_factual_message(
            send_message,
            telegram_token=telegram_token,
            chat_id=chat_id,
            text="Отменено",
            timeout=timeout,
            log_prefix="TELEGRAM WHITELIST CANCEL RESULT SEND FAILED",
        )
        return True

    def _execute_add(
        self,
        payload: dict[str, Any],
        *,
        chat_id: str,
        user_id: str,
    ) -> WhitelistMutationResult:
        address = str(payload["address"])
        if self.bot_settings.dry_run:
            self._record(
                "whitelist.add",
                "dry-run",
                chat_id,
                user_id,
                address,
            )
            return WhitelistMutationResult(
                "dry-run",
                managed=False,
                removed=False,
            )
        try:
            changed = bool(self.store.add(address))
        except Exception as exc:
            self._record(
                "whitelist.add",
                "failure",
                chat_id,
                user_id,
                address,
                type(exc).__name__,
            )
            return WhitelistMutationResult(
                "failure",
                managed=False,
                removed=False,
            )
        self._record(
            "whitelist.add",
            "persisted",
            chat_id,
            user_id,
            address,
        )
        try:
            removed = self._remove_from_routeros(
                str(payload["list_name"]),
                address,
            )
        except Exception as exc:
            self._record(
                "whitelist.add",
                "partial",
                chat_id,
                user_id,
                address,
                type(exc).__name__,
            )
            return WhitelistMutationResult(
                "partial",
                managed=True,
                removed=False,
                changed=changed,
            )
        self._record(
            "whitelist.add",
            "success",
            chat_id,
            user_id,
            address,
            f"removed={int(removed)}",
        )
        return WhitelistMutationResult(
            "success",
            managed=True,
            removed=removed,
            changed=changed,
        )

    def _execute_retry(
        self,
        payload: dict[str, Any],
        *,
        chat_id: str,
        user_id: str,
    ) -> WhitelistMutationResult:
        address = str(payload["address"])
        if not self.store.contains(address):
            self._record(
                "whitelist.retry_unblock",
                "stale",
                chat_id,
                user_id,
                address,
                "managed exception missing",
            )
            return WhitelistMutationResult("stale", False, False)
        if self.bot_settings.dry_run:
            self._record(
                "whitelist.retry_unblock",
                "dry-run",
                chat_id,
                user_id,
                address,
            )
            return WhitelistMutationResult("dry-run", True, False)
        try:
            removed = self._remove_from_routeros(
                str(payload["list_name"]),
                address,
            )
        except Exception as exc:
            self._record(
                "whitelist.retry_unblock",
                "partial",
                chat_id,
                user_id,
                address,
                type(exc).__name__,
            )
            return WhitelistMutationResult("partial", True, False)
        self._record(
            "whitelist.retry_unblock",
            "success",
            chat_id,
            user_id,
            address,
            f"removed={int(removed)}",
        )
        return WhitelistMutationResult("success", True, removed)

    def _execute_remove(
        self,
        payload: dict[str, Any],
        *,
        chat_id: str,
        user_id: str,
        message_id: Any,
        send_message: Callable[..., Any],
        edit_message: Callable[..., Any],
        telegram_token: str,
        timeout: int,
        now: int,
    ) -> None:
        address = str(payload["address"])
        if self.bot_settings.dry_run:
            self._record(
                "whitelist.remove",
                "dry-run",
                chat_id,
                user_id,
                address,
            )
            text = "Dry-run: исключение не удалено"
        elif not self.store.contains(address):
            self._record(
                "whitelist.remove",
                "noop",
                chat_id,
                user_id,
                address,
            )
            text = "Исключение уже отсутствует"
        else:
            try:
                self.store.remove(address)
            except Exception as exc:
                self._record(
                    "whitelist.remove",
                    "failure",
                    chat_id,
                    user_id,
                    address,
                    type(exc).__name__,
                )
                self._deliver_factual_message(
                    send_message,
                    telegram_token=telegram_token,
                    chat_id=chat_id,
                    text="Не удалось удалить исключение",
                    timeout=timeout,
                    log_prefix=(
                        "TELEGRAM WHITELIST REMOVE RESULT SEND FAILED"
                    ),
                )
                return
            self._record(
                "whitelist.remove",
                "success",
                chat_id,
                user_id,
                address,
            )
            text = "Исключение удалено"

        if self.bot_settings.dry_run or text == "Исключение уже отсутствует":
            self._deliver_factual_message(
                send_message,
                telegram_token=telegram_token,
                chat_id=chat_id,
                text=text,
                timeout=timeout,
                log_prefix="TELEGRAM WHITELIST REMOVE RESULT SEND FAILED",
            )
            return
        delivery_failed = False
        try:
            view = self.menu_view(
                page=0,
                chat_id=chat_id,
                user_id=user_id,
                now=now,
            )
            response = self._edit_or_send(
                view,
                chat_id=chat_id,
                message_id=message_id,
                edit_message=edit_message,
                send_message=send_message,
                telegram_token=telegram_token,
                timeout=timeout,
            )
            if getattr(response, "ok", True) is False:
                delivery_failed = True
                self.log(
                    "TELEGRAM WHITELIST POST-REMOVE VIEW FAILED"
                )
        except Exception as exc:
            delivery_failed = True
            self.log(
                "TELEGRAM WHITELIST POST-REMOVE VIEW FAILED: "
                f"{type(exc).__name__}"
            )
        if delivery_failed:
            self._deliver_factual_message(
                send_message,
                telegram_token=telegram_token,
                chat_id=chat_id,
                text="Исключение удалено",
                timeout=timeout,
                log_prefix="TELEGRAM WHITELIST REMOVE RESULT SEND FAILED",
            )

    def _remove_from_routeros(self, list_name: str, address: str) -> bool:
        client = self.get_router_client()

        def remove_batch() -> bool:
            address_list, _address_list_v6, _resources = client.paths()
            return (
                remove_from_address_list(
                    address_list,
                    list_name,
                    address,
                )
                > 0
            )

        return bool(
            client.run_with_reconnect(
                "telegram managed whitelist unblock",
                remove_batch,
            )
        )

    def _create_retry(
        self,
        payload: dict[str, Any],
        *,
        chat_id: str,
        user_id: str,
        now: int,
    ) -> str | None:
        try:
            return self.actions.create(
                kind="retry_unblock",
                address=str(payload["address"]),
                list_name=str(payload["list_name"]),
                sid=str(payload.get("sid", "N/A")),
                chat_id=chat_id,
                user_id=user_id,
                now=int(now),
                ttl_seconds=self.action_ttl_seconds,
                source_chat_id=str(
                    payload.get("source_chat_id") or chat_id
                ),
                source_message_id=payload.get("source_message_id"),
                source_reply_markup=payload.get("source_reply_markup"),
            )
        except Exception as exc:
            self.log(
                "TELEGRAM WHITELIST RETRY TOKEN FAILED: "
                f"{type(exc).__name__}"
            )
            return None

    def _deliver_alert_result(
        self,
        payload: dict[str, Any],
        *,
        address: str,
        retry_token: str | None,
        result_text: str,
        current_chat_id: str,
        current_message_id: Any,
        edit_reply_markup: Callable[..., Any],
        send_message: Callable[..., Any],
        telegram_token: str,
        timeout: int,
    ) -> None:
        source_markup = payload.get("source_reply_markup")
        if not isinstance(source_markup, dict):
            source_markup = {"inline_keyboard": []}
        reply_markup = self._result_markup(
            source_markup,
            address=address,
            retry_token=retry_token,
        )
        source_chat_id = str(
            payload.get("source_chat_id") or current_chat_id
        )
        source_message_id = payload.get("source_message_id")
        if source_message_id is None:
            source_message_id = current_message_id
        edit_ok = False
        try:
            response = edit_reply_markup(
                token=telegram_token,
                chat_id=source_chat_id,
                message_id=source_message_id,
                reply_markup=reply_markup,
                timeout=timeout,
            )
            edit_ok = getattr(response, "ok", True) is not False
        except Exception as exc:
            self.log(
                "TELEGRAM WHITELIST POST-MUTATION MARKUP FAILED: "
                f"{type(exc).__name__}"
            )
        if edit_ok:
            return
        self.log("TELEGRAM WHITELIST POST-MUTATION MARKUP FAILED")
        try:
            response = send_message(
                token=telegram_token,
                chat_id=current_chat_id,
                text=result_text,
                reply_markup=reply_markup,
                timeout=timeout,
            )
            if getattr(response, "ok", True) is False:
                self.log("TELEGRAM WHITELIST RESULT SEND FAILED")
        except Exception as exc:
            self.log(
                "TELEGRAM WHITELIST RESULT SEND FAILED: "
                f"{type(exc).__name__}"
            )

    def _deliver_factual_message(
        self,
        send_message: Callable[..., Any],
        *,
        telegram_token: str,
        chat_id: str,
        text: str,
        timeout: int,
        log_prefix: str,
    ) -> None:
        try:
            response = send_message(
                token=telegram_token,
                chat_id=chat_id,
                text=text,
                timeout=timeout,
            )
            if getattr(response, "ok", True) is False:
                self.log(log_prefix)
        except Exception as exc:
            self.log(f"{log_prefix}: {type(exc).__name__}")

    @staticmethod
    def _result_markup(
        source_markup: dict[str, Any],
        *,
        address: str,
        retry_token: str | None,
    ) -> dict[str, Any]:
        preserved = []
        for row in source_markup.get("inline_keyboard", []):
            if any(
                str(button.get("callback_data", "")).startswith(
                    "whitelist:v1:"
                )
                for button in row
                if isinstance(button, dict)
            ):
                continue
            preserved.append(list(row))
        preserved.append(
            [
                {
                    "text": f"✅ В исключениях {address}",
                    "callback_data": "menu:v1:exceptions",
                }
            ]
        )
        if retry_token is not None:
            preserved.append(
                [
                    {
                        "text": "🔄 Повторить разблокировку",
                        "callback_data": (
                            "whitelist:v1:retry-unblock:"
                            f"{retry_token}"
                        ),
                    }
                ]
            )
        return {"inline_keyboard": preserved}

    @staticmethod
    def _add_answer(
        result: WhitelistMutationResult,
    ) -> tuple[str, bool]:
        if result.outcome == "failure":
            return "Не удалось сохранить исключение", True
        if result.outcome == "partial":
            return (
                "Исключение сохранено, разблокировка не выполнена",
                True,
            )
        if result.outcome == "dry-run":
            return (
                "Dry-run: исключение не добавлено, адрес не разблокирован",
                False,
            )
        if not result.changed and not result.removed:
            return "Адрес уже в исключениях; блокировка не найдена", False
        if not result.changed:
            return "Адрес уже в исключениях; адрес разблокирован", False
        if not result.removed:
            return "Исключение добавлено; блокировка не найдена", False
        return "Исключение добавлено, адрес разблокирован", False

    @staticmethod
    def _retry_answer(
        result: WhitelistMutationResult,
    ) -> tuple[str, bool]:
        if result.outcome == "stale":
            return "Управляемое исключение уже отсутствует", True
        if result.outcome == "dry-run":
            return "Dry-run: адрес не разблокирован", False
        if result.outcome == "partial":
            return "Разблокировка не выполнена", True
        if result.removed:
            return "Адрес разблокирован", False
        return "Блокировка уже отсутствует", False

    def _control_enabled(self) -> bool:
        return bool(
            getattr(
                self.settings,
                "telegram_whitelist_control_enable",
                False,
            )
            and "whitelist_control" in self.bot_settings.modules
        )

    def _peek(
        self,
        token: str,
        *,
        now: int,
        chat_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        try:
            return self.actions.peek(
                token,
                now=int(now),
                chat_id=chat_id,
                user_id=user_id,
            )
        except (WhitelistActionStoreError, OSError) as exc:
            self.log(
                "TELEGRAM WHITELIST ACTION READ FAILED: "
                f"{type(exc).__name__}"
            )
            return None

    def _consume(
        self,
        token: str,
        *,
        now: int,
        chat_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        try:
            return self.actions.consume(
                token,
                now=int(now),
                chat_id=chat_id,
                user_id=user_id,
            )
        except (WhitelistActionStoreError, OSError) as exc:
            self.log(
                "TELEGRAM WHITELIST ACTION CONSUME FAILED: "
                f"{type(exc).__name__}"
            )
            return None

    def _stale(
        self,
        callback_id: str,
        chat_id: str,
        user_id: str,
        answer_callback: Callable[[str, str, bool], Any],
        action_name: str,
    ) -> None:
        self._record(
            f"whitelist.{action_name}",
            "stale",
            chat_id,
            user_id,
            "",
        )
        answer_callback(
            callback_id,
            "Запрос истёк или уже использован",
            True,
        )

    def _record(
        self,
        action: str,
        outcome: str,
        chat_id: str,
        user_id: str,
        target: str,
        detail: str = "",
    ) -> None:
        self.audit.record(
            action,
            outcome,
            chat_id,
            user_id,
            target,
            detail,
        )

    @staticmethod
    def _callback_context(
        callback: dict[str, Any],
    ) -> tuple[str, str, str, Any, Any]:
        callback_id = str(callback.get("id", ""))
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        user = callback.get("from") or {}
        return (
            callback_id,
            str(chat.get("id", "")),
            str(user.get("id", "")),
            message.get("message_id"),
            message.get("reply_markup"),
        )

    @staticmethod
    def _edit_or_send(
        view: MenuView,
        *,
        chat_id: str,
        message_id: Any,
        edit_message: Callable[..., Any],
        send_message: Callable[..., Any],
        telegram_token: str,
        timeout: int,
    ) -> Any:
        if message_id not in (None, ""):
            response = edit_message(
                token=telegram_token,
                chat_id=chat_id,
                message_id=message_id,
                text=view.text,
                reply_markup=view.reply_markup,
                timeout=timeout,
            )
            if getattr(response, "ok", True) is not False:
                return response
        return send_message(
            token=telegram_token,
            chat_id=chat_id,
            text=view.text,
            reply_markup=view.reply_markup,
            timeout=timeout,
        )


__all__ = ["TelegramWhitelistHandler", "WhitelistMutationResult"]
