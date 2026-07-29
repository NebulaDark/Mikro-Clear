"""Effective execution gates for Telegram bot modules."""

from __future__ import annotations

from typing import Any


def bot_module_enabled(
    bot_settings: Any,
    module: str,
    *,
    feature_enabled: bool = True,
) -> bool:
    """Return the single effective gate for a bot module."""

    return bool(
        getattr(bot_settings, "enable", False)
        and module in tuple(getattr(bot_settings, "modules", ()))
        and feature_enabled
    )


__all__ = ["bot_module_enabled"]
