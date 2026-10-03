"""Presentation helpers for the parental-control Telegram menu."""

from typing import Any

from mikroclear.bot.menu import MenuView
from mikroclear.telegram.formatting import escape_html_safe


def build_parental_view(states: list[Any]) -> MenuView:
    rows = []
    lines = ["👨‍👩‍👧 <b>Родительский контроль</b>", ""]
    for index, state in enumerate(states):
        device = state.device
        name = device.name or device.ip
        label = "🔴 BLOCKED" if state.blocked else "🟢 ALLOWED"
        lines.extend([f"📱 {escape_html_safe(name)}", f"IP: <code>{escape_html_safe(device.ip)}</code>", f"YouTube: {label}", ""])
        rows.append([{"text": f"📱 {name}", "callback_data": f"parental:v1:youtube:request:{index}:noop"}])
        rows.append([{"text": "🔓 Разрешить YouTube" if state.blocked else "🔒 Заблокировать YouTube", "callback_data": f"parental:v1:youtube:request:{index}:{'allow' if state.blocked else 'block'}"}])
    rows.extend([
        [{"text": "🔄 Обновить", "callback_data": "parental:v1:refresh"}],
        [{"text": "⬅️ Назад", "callback_data": "menu:v1:root"}],
    ])
    return MenuView("\n".join(lines).strip(), {"inline_keyboard": rows})


def build_parental_confirmation(device: Any, action: str, token: str) -> MenuView:
    verb = "BLOCK" if action == "block" else "ALLOW"
    text = (
        "<b>Подтвердить изменение?</b>\n\n"
        f"Device: {escape_html_safe(device.name or device.ip)}\n"
        f"IP: <code>{escape_html_safe(device.ip)}</code>\n"
        f"Action: {verb} YouTube"
    )
    return MenuView(text, {"inline_keyboard": [[
        {"text": "✅ Confirm", "callback_data": f"parental:v1:youtube:confirm:{token}"},
        {"text": "❌ Cancel", "callback_data": f"parental:v1:youtube:cancel:{token}"},
    ]]})


def build_parental_error_view(*, mutation: bool, device: Any = None, ip: str = "") -> MenuView:
    if mutation:
        device_name = getattr(device, "name", "") or ip
        device_ip = getattr(device, "ip", "") or ip
        text = (
            "❌ <b>Не удалось применить политику YouTube</b>\n\n"
            f"Устройство: {escape_html_safe(device_name)}\n"
            f"IP: <code>{escape_html_safe(device_ip)}</code>\n\n"
            "Изменение не подтверждено.\n"
            "Обновите состояние и повторите попытку."
        )
    else:
        text = (
            "⚠️ <b>Не удалось получить состояние Parental Control</b>\n\n"
            "Попробуйте обновить данные позже."
        )
    return MenuView(text, {"inline_keyboard": [
        [{"text": "🔄 Обновить", "callback_data": "parental:v1:refresh"}],
        [{"text": "⬅️ Назад", "callback_data": "menu:v1:root"}],
    ]})


__all__ = ["build_parental_confirmation", "build_parental_error_view", "build_parental_view"]
