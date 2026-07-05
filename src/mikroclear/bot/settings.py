"""Settings for the Mikro-Clear Telegram control plane."""

from dataclasses import dataclass

from mikroclear.config import env_bool, env_csv, env_str


def parse_chat_ids(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class BotSettings:
    enable: bool = False
    dry_run: bool = True
    admin_chat_ids: tuple[str, ...] = ()
    allowed_chat_ids: tuple[str, ...] = ()
    modules: tuple[str, ...] = ("status", "asset_resolver", "mangle_control", "parental_control")
    audit_log: str = "/var/lib/mikroclear/bot-audit.log"

    @classmethod
    def from_env(cls) -> "BotSettings":
        return cls(
            enable=env_bool("MIKROCLEAR_BOT_ENABLE", False),
            dry_run=env_bool("MIKROCLEAR_BOT_DRY_RUN", True),
            admin_chat_ids=parse_chat_ids(env_str("MIKROCLEAR_BOT_ADMIN_CHAT_IDS", "")),
            allowed_chat_ids=parse_chat_ids(env_str("MIKROCLEAR_BOT_ALLOWED_CHAT_IDS", "")),
            modules=env_csv(
                "MIKROCLEAR_BOT_MODULES",
                ("status", "asset_resolver", "mangle_control", "parental_control"),
            ),
            audit_log=env_str("MIKROCLEAR_BOT_AUDIT_LOG", "/var/lib/mikroclear/bot-audit.log"),
        )


__all__ = ["BotSettings", "parse_chat_ids"]
