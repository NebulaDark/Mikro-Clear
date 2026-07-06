"""Runtime status snapshot builder."""

from typing import Any, Callable

from mikroclear.bot.modules.status import StatusSnapshot
from mikroclear.bot.settings import BotSettings


def build_status_snapshot(
    *,
    settings: Any,
    router_client: Any,
    service_start_time: float,
    now: Callable[[], float],
    bot_settings_factory: Callable[[], BotSettings] = BotSettings.from_env,
) -> StatusSnapshot:
    connected_at = float(getattr(router_client, "connected_at", 0.0) or 0.0)
    connected = bool(getattr(router_client, "api", None))
    connected_seconds = int(now() - connected_at) if connected and connected_at else 0
    return StatusSnapshot(
        uptime_seconds=int(now() - service_start_time),
        routeros_connected=connected,
        routeros_connected_seconds=connected_seconds,
        eve_path=settings.filepath,
        block_list_name=settings.block_list_name,
        monitor_only=settings.monitor_only,
        telegram_unblock_enabled=settings.telegram_unblock_enable,
        state_dir=settings.state_dir,
        bot_settings=bot_settings_factory(),
    )


__all__ = ["build_status_snapshot"]
