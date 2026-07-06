"""Telegram presentation helpers for RouterOS mangle control."""

from html import escape
from typing import Callable

from mikroclear.routeros.mangle import MangleRule


def format_mangle_status(rules: list[MangleRule]) -> str:
    if not rules:
        return "<b>Mangle Rules</b>\n\nNo managed rules found."

    parts = ["<b>Mangle Rules</b>"]
    for rule in rules:
        icon = "❌" if rule.disabled else "✅"
        parts.append(
            "\n".join(
                [
                    f"{icon} {escape(rule.name)}",
                    f"Chain: {escape(rule.chain)}",
                    f"Action: {escape(rule.action)}",
                    f"Packets: {rule.packets}",
                    f"Bytes: {rule.bytes}",
                ]
            )
        )
    return "\n\n".join(parts)


def build_mangle_keyboard(
    rules: list[MangleRule],
    *,
    token_factory: Callable[[MangleRule, str], str],
) -> dict[str, object]:
    rows: list[list[dict[str, str]]] = []
    for rule in rules:
        action = "enable" if rule.disabled else "disable"
        label = "Enable" if rule.disabled else "Disable"
        token = token_factory(rule, action)
        rows.append([{"text": f"{label} {rule.name}", "callback_data": f"mangle:request:{token}"}])
    rows.append([{"text": "Refresh", "callback_data": "mangle:refresh"}])
    return {"inline_keyboard": rows}


def build_mangle_confirm_keyboard(token: str) -> dict[str, object]:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Confirm", "callback_data": f"mangle:confirm:{token}"},
                {"text": "❌ Cancel", "callback_data": f"mangle:cancel:{token}"},
            ]
        ]
    }


__all__ = ["build_mangle_confirm_keyboard", "build_mangle_keyboard", "format_mangle_status"]
