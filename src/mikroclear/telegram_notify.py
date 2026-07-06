"""Deprecated compatibility shim for Telegram notification helpers."""

from mikroclear.telegram.formatting import (
    default_peer_formatter,
    escape_html_safe,
    format_alert_message,
    format_system_message,
    sanitize_text,
)
from mikroclear.telegram.notify import TelegramNotifier, TelegramSendResult, send_telegram_message

__all__ = [
    "TelegramNotifier",
    "TelegramSendResult",
    "default_peer_formatter",
    "escape_html_safe",
    "format_alert_message",
    "format_system_message",
    "sanitize_text",
    "send_telegram_message",
]
