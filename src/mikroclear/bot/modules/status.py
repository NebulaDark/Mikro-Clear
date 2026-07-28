"""Read-only Mikro-Clear status command."""

from dataclasses import dataclass

from mikroclear.bot.settings import BotSettings
from mikroclear.security import mask_telegram_bot_token


@dataclass(frozen=True)
class StatusSnapshot:
    uptime_seconds: int
    routeros_connected: bool
    routeros_connected_seconds: int
    eve_path: str
    block_list_name: str
    monitor_only: bool
    telegram_unblock_enabled: bool
    state_dir: str
    bot_settings: BotSettings
    telegram_whitelist_control_enabled: bool = False
    dynamic_whitelist_file: str = ""
    managed_whitelist_count: int = 0


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def on_off(value: bool) -> str:
    return "on" if value else "off"


def format_status(snapshot: StatusSnapshot) -> str:
    if snapshot.routeros_connected:
        routeros = f"connected for {format_duration(snapshot.routeros_connected_seconds)}"
    else:
        routeros = "disconnected"

    lines = [
        "Mikro-Clear status",
        f"uptime: {format_duration(snapshot.uptime_seconds)}",
        f"routeros: {routeros}",
        f"eve: {snapshot.eve_path}",
        f"address-list: {snapshot.block_list_name}",
        f"monitor-only: {on_off(snapshot.monitor_only)}",
        f"telegram unblock: {on_off(snapshot.telegram_unblock_enabled)}",
        "telegram whitelist control: "
        f"{on_off(snapshot.telegram_whitelist_control_enabled)}",
        f"managed whitelist: {snapshot.managed_whitelist_count}",
        f"whitelist store: {snapshot.dynamic_whitelist_file}",
        f"bot dry-run: {on_off(snapshot.bot_settings.dry_run)}",
        f"modules: {', '.join(snapshot.bot_settings.modules)}",
        f"state-dir: {snapshot.state_dir}",
    ]
    return mask_telegram_bot_token("\n".join(lines))


__all__ = ["StatusSnapshot", "format_duration", "format_status"]
