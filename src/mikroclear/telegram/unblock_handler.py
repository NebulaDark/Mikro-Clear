"""Telegram unblock action handling."""

from typing import Any, Callable

import requests

from mikroclear.routeros.address_list import remove_from_address_list
from mikroclear.security import sanitize_exception_text
from mikroclear.suricata.alert_logic import is_ip_in_whitelist, is_valid_ip
from mikroclear.telegram.unblock import UnblockCallbackResult


class TelegramUnblockHandler:
    def __init__(
        self,
        settings: Any,
        *,
        get_router_client: Callable[[], Any],
        log: Callable[[str], None],
        http_post: Callable[..., Any] = requests.post,
    ) -> None:
        self.settings = settings
        self.get_router_client = get_router_client
        self.log = log
        self.http_post = http_post

    def handle_unblock_action(self, action: dict[str, Any]) -> UnblockCallbackResult:
        wanted_ip = str(action.get("wanted_ip", ""))
        list_name = str(action.get("list_name") or self.settings.block_list_name)
        if not is_valid_ip(wanted_ip):
            self.log(f"TELEGRAM UNBLOCK INVALID: {wanted_ip or '<empty>'} from {list_name}")
            return UnblockCallbackResult("Invalid unblock target", False, True)
        if is_ip_in_whitelist(wanted_ip, self.settings.whitelist_ips):
            self.log(f"TELEGRAM UNBLOCK REFUSED: {wanted_ip} is whitelisted")
            return UnblockCallbackResult(f"Refusing to unblock whitelisted target {wanted_ip}", False, True)

        client = self.get_router_client()

        def remove_batch() -> bool:
            address_list, address_list_v6, _resources = client.paths()
            target_list = address_list_v6 if ":" in wanted_ip and address_list_v6 is not None else address_list
            return remove_from_address_list(target_list, wanted_ip, list_name) > 0

        try:
            removed = client.run_with_reconnect("telegram unblock", remove_batch)
        except Exception as exc:
            self.log(f"TELEGRAM UNBLOCK FAILED: {wanted_ip} from {list_name} - {type(exc).__name__}: {exc}")
            return UnblockCallbackResult(f"Could not unblock {wanted_ip}", False, True)

        if removed:
            self.log(f"TELEGRAM UNBLOCKED: {wanted_ip} from {list_name} - SID:{action.get('sid', 'N/A')}")
            return UnblockCallbackResult(f"Unblocked {wanted_ip}", True)
        self.log(f"TELEGRAM UNBLOCK NOOP: {wanted_ip} not found in {list_name}")
        return UnblockCallbackResult(f"{wanted_ip} was not found in {list_name}", False)

    def answer_telegram_callback(self, callback_id: str, text: str, alert: bool = False) -> None:
        if not self.settings.telegram_token or not callback_id:
            return
        try:
            self.http_post(
                f"https://api.telegram.org/bot{self.settings.telegram_token}/answerCallbackQuery",
                data={"callback_query_id": callback_id, "text": text, "show_alert": "true" if alert else "false"},
                timeout=self.settings.telegram_timeout,
            )
        except Exception as exc:
            self.log(f"Error answering Telegram callback: {sanitize_exception_text(exc, self.settings.telegram_token)}")


__all__ = ["TelegramUnblockHandler"]
