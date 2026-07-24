"""Typed runtime settings."""

from dataclasses import dataclass
import os

from mikroclear.config import env_bool, env_csv, env_int, env_str


@dataclass(frozen=True)
class Settings:
    username: str = "mikrocata2selks"
    password: str = ""
    router_ip: str = "192.168.10.1"
    router_tls_server_name: str = "192.168.10.1"
    use_ssl: bool = True
    port: int = 8729
    allow_self_signed_certs: bool = False
    ca_file: str = "/etc/mikroclear/certs/mikrotik-ca.crt"
    router_connect_retry_seconds: int = 30
    socket_timeout_seconds: int = 20
    router_heartbeat_seconds: int = 60
    router_reconnect_sleep_seconds: int = 2
    router_connect_notify_enable: bool = False
    block_list_name: str = "Suricata"
    timeout: str = "1d"
    monitor_only: bool = False
    enable_telegram: bool = False
    telegram_token: str = ""
    telegram_chatid: str = ""
    telegram_timeout: int = 10
    telegram_cooldown_seconds: int = 2
    telegram_system_cooldown_seconds: int = 300
    telegram_unblock_enable: bool = True
    telegram_unblock_ttl_seconds: int = 24 * 3600
    telegram_updates_interval_seconds: int = 5
    telegram_long_poll_seconds: int = 25
    wan_ip: str = ""
    local_ip_prefix: str = "192.168.0.0/16"
    default_whitelist: tuple[str, ...] = ()
    whitelist_ips: tuple[str, ...] = ()
    enable_ipv6: bool = False
    severity: tuple[str, ...] = ("1", "2")
    listen_interfaces: tuple[str, ...] = ("tzsp0",)
    add_on_start: bool = False
    debug_mode: bool = False
    comment_time_format: str = "%-d %b %Y %H:%M:%S.%f"
    selks_container_data_suricata_log: str = "/opt/SELKS/docker/containers-data/suricata/logs/"
    filepath: str = "/opt/SELKS/docker/containers-data/suricata/logs/eve.json"
    state_dir: str = "/var/lib/mikroclear"
    save_lists_location: str = "/var/lib/mikroclear/savelists-tzsp0.json"
    save_lists_location_v6: str = "/var/lib/mikroclear/savelists-tzsp0_v6.json"
    uptime_bookmark: str = "/var/lib/mikroclear/uptime-tzsp0.bookmark"
    ignore_list_location: str = "/var/lib/mikroclear/ignore-tzsp0.conf"
    telegram_lock_file: str = "/var/lib/mikroclear/telegram-rate-limit.lock"
    telegram_unblock_state_file: str = "/var/lib/mikroclear/telegram-unblock-actions.json"
    save_lists: tuple[str, ...] = ("Suricata",)
    save_interval: int = 300
    asset_resolver_enable: bool = True
    asset_resolver_private_only: bool = True
    asset_resolver_dhcp_enable: bool = True
    asset_resolver_ptr_enable: bool = True
    asset_resolver_cache_ttl: int = 3600
    mangle_control_enable: bool = False
    mangle_comment_prefix: str = "MC:"
    mangle_allowed_chains: tuple[str, ...] = ("prerouting",)
    mangle_allowed_actions: tuple[str, ...] = ("mark-routing",)
    mangle_require_confirmation: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        username = env_str("MIKROCLEAR_ROUTER_USERNAME", "mikrocata2selks")
        password = env_str("MIKROCLEAR_ROUTER_PASSWORD", "")
        router_ip = env_str("MIKROCLEAR_ROUTER_IP", "192.168.10.1")
        router_tls_server_name = env_str("MIKROCLEAR_ROUTER_TLS_SERVER_NAME", router_ip)
        use_ssl = env_bool("MIKROCLEAR_USE_SSL", True)
        port = env_int("MIKROCLEAR_ROUTER_PORT", 8729 if use_ssl else 8728)

        block_list_name = env_str("MIKROCLEAR_BLOCK_LIST_NAME", "Suricata")
        wan_ip = env_str("MIKROCLEAR_WAN_IP", "")
        local_ip_prefix = env_str("MIKROCLEAR_LOCAL_IP_PREFIX", "192.168.0.0/16")
        default_whitelist = tuple(
            item
            for item in (
                wan_ip,
                local_ip_prefix,
                "127.0.0.1",
                "1.1.1.1",
                "8.8.8.8",
                "fe80:",
                "10.0.0.0/8",
                "172.16.0.0/12",
            )
            if item
        )

        log_dir = env_str(
            "MIKROCLEAR_SURICATA_LOG_DIR",
            "/opt/SELKS/docker/containers-data/suricata/logs/",
        )
        filepath = os.path.abspath(
            env_str(
                "MIKROCLEAR_EVE_JSON",
                os.path.join(log_dir, "eve.json"),
            )
        )
        state_dir = os.path.abspath(env_str("MIKROCLEAR_STATE_DIR", "/var/lib/mikroclear"))

        return cls(
            username=username,
            password=password,
            router_ip=router_ip,
            router_tls_server_name=router_tls_server_name,
            use_ssl=use_ssl,
            port=port,
            allow_self_signed_certs=env_bool("MIKROCLEAR_ALLOW_SELF_SIGNED_CERTS", False),
            ca_file=env_str("MIKROCLEAR_CA_FILE", "/etc/mikroclear/certs/mikrotik-ca.crt"),
            router_connect_retry_seconds=env_int("MIKROCLEAR_ROUTER_CONNECT_RETRY_SECONDS", 30),
            socket_timeout_seconds=env_int("MIKROCLEAR_SOCKET_TIMEOUT_SECONDS", 20),
            router_heartbeat_seconds=env_int("MIKROCLEAR_ROUTER_HEARTBEAT_SECONDS", 60),
            router_reconnect_sleep_seconds=env_int("MIKROCLEAR_ROUTER_RECONNECT_SLEEP_SECONDS", 2),
            router_connect_notify_enable=env_bool("MIKROCLEAR_ROUTER_CONNECT_NOTIFY_ENABLE", False),
            block_list_name=block_list_name,
            timeout=env_str("MIKROCLEAR_BLOCK_TIMEOUT", "1d"),
            monitor_only=env_bool("MIKROCLEAR_MONITOR_ONLY", False),
            enable_telegram=env_bool("MIKROCLEAR_TELEGRAM_ENABLE", False),
            telegram_token=env_str("MIKROCLEAR_TELEGRAM_TOKEN", ""),
            telegram_chatid=env_str("MIKROCLEAR_TELEGRAM_CHATID", ""),
            telegram_timeout=env_int("MIKROCLEAR_TELEGRAM_TIMEOUT", 10),
            telegram_cooldown_seconds=env_int("MIKROCLEAR_TELEGRAM_COOLDOWN_SECONDS", 2),
            telegram_system_cooldown_seconds=env_int("MIKROCLEAR_TELEGRAM_SYSTEM_COOLDOWN_SECONDS", 300),
            telegram_unblock_enable=env_bool("MIKROCLEAR_TELEGRAM_UNBLOCK_ENABLE", True),
            telegram_unblock_ttl_seconds=env_int("MIKROCLEAR_TELEGRAM_UNBLOCK_TTL_SECONDS", 24 * 3600),
            telegram_updates_interval_seconds=env_int("MIKROCLEAR_TELEGRAM_UPDATES_INTERVAL_SECONDS", 5),
            telegram_long_poll_seconds=env_int("MIKROCLEAR_TELEGRAM_LONG_POLL_SECONDS", 25),
            wan_ip=wan_ip,
            local_ip_prefix=local_ip_prefix,
            default_whitelist=default_whitelist,
            whitelist_ips=env_csv("MIKROCLEAR_WHITELIST_IPS", default_whitelist),
            enable_ipv6=env_bool("MIKROCLEAR_ENABLE_IPV6", False),
            severity=env_csv("MIKROCLEAR_SEVERITY", ("1", "2")),
            listen_interfaces=env_csv("MIKROCLEAR_LISTEN_INTERFACES", ("tzsp0",)),
            add_on_start=env_bool("MIKROCLEAR_ADD_ON_START", False),
            debug_mode=env_bool("MIKROCLEAR_DEBUG", False),
            comment_time_format=env_str("MIKROCLEAR_COMMENT_TIME_FORMAT", "%-d %b %Y %H:%M:%S.%f"),
            selks_container_data_suricata_log=log_dir,
            filepath=filepath,
            state_dir=state_dir,
            save_lists_location=os.path.abspath(
                env_str("MIKROCLEAR_SAVE_LISTS_LOCATION", os.path.join(state_dir, "savelists-tzsp0.json"))
            ),
            save_lists_location_v6=os.path.abspath(
                env_str("MIKROCLEAR_SAVE_LISTS_LOCATION_V6", os.path.join(state_dir, "savelists-tzsp0_v6.json"))
            ),
            uptime_bookmark=os.path.abspath(
                env_str("MIKROCLEAR_UPTIME_BOOKMARK", os.path.join(state_dir, "uptime-tzsp0.bookmark"))
            ),
            ignore_list_location=os.path.abspath(
                env_str("MIKROCLEAR_IGNORE_LIST_LOCATION", os.path.join(state_dir, "ignore-tzsp0.conf"))
            ),
            telegram_lock_file=os.path.abspath(
                env_str("MIKROCLEAR_TELEGRAM_LOCK_FILE", os.path.join(state_dir, "telegram-rate-limit.lock"))
            ),
            telegram_unblock_state_file=os.path.abspath(
                env_str(
                    "MIKROCLEAR_TELEGRAM_UNBLOCK_STATE_FILE",
                    os.path.join(state_dir, "telegram-unblock-actions.json"),
                )
            ),
            save_lists=env_csv("MIKROCLEAR_SAVE_LISTS", (block_list_name,)),
            save_interval=env_int("MIKROCLEAR_SAVE_INTERVAL", 300),
            asset_resolver_enable=env_bool("MIKROCLEAR_ASSET_RESOLVER_ENABLE", True),
            asset_resolver_private_only=env_bool("MIKROCLEAR_ASSET_RESOLVER_PRIVATE_ONLY", True),
            asset_resolver_dhcp_enable=env_bool("MIKROCLEAR_ASSET_RESOLVER_DHCP_ENABLE", True),
            asset_resolver_ptr_enable=env_bool("MIKROCLEAR_ASSET_RESOLVER_PTR_ENABLE", True),
            asset_resolver_cache_ttl=env_int("MIKROCLEAR_ASSET_RESOLVER_CACHE_TTL", 3600),
            mangle_control_enable=env_bool("MIKROCLEAR_MANGLE_CONTROL_ENABLE", False),
            mangle_comment_prefix=env_str("MIKROCLEAR_MANGLE_COMMENT_PREFIX", "MC:"),
            mangle_allowed_chains=env_csv("MIKROCLEAR_MANGLE_ALLOWED_CHAINS", ("prerouting",)),
            mangle_allowed_actions=env_csv("MIKROCLEAR_MANGLE_ALLOWED_ACTIONS", ("mark-routing",)),
            mangle_require_confirmation=env_bool("MIKROCLEAR_MANGLE_REQUIRE_CONFIRMATION", True),
        )


def load_settings() -> Settings:
    return Settings.from_env()


__all__ = ["Settings", "load_settings"]
