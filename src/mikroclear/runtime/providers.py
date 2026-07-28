"""Runtime dependency providers."""

from dataclasses import dataclass
from datetime import datetime as dt
import os
from pathlib import Path
from time import sleep, time
from typing import Any

from mikroclear.assets.resolver import AssetResolver, AssetResolverConfig
from mikroclear.bot.settings import BotSettings
from mikroclear.runtime import MikroClearService
from mikroclear.runtime.status_snapshot import build_status_snapshot
from mikroclear.routeros.client import RouterOSClient
from mikroclear.security import sanitize_exception_text
from mikroclear.settings import Settings
from mikroclear.state.address_list_store import add_saved_lists, save_lists
from mikroclear.state.dynamic_whitelist import DynamicWhitelistStore
from mikroclear.state.files import StateStoreConfig
from mikroclear.state.uptime import check_tik_uptime
from mikroclear.suricata.alert_logic import is_ip_in_whitelist, is_valid_ip
from mikroclear.suricata.eve_tailer import EveJsonTailer
from mikroclear.suricata.events import validate_event
from mikroclear.suricata.ignore_rules import IgnoreRules
from mikroclear.suricata.pipeline import AlertPipeline, AlertProcessorConfig
from mikroclear.suricata.whitelist_policy import WhitelistPolicy
from mikroclear.telegram.formatting import escape_html_safe
from mikroclear.telegram.notify import TelegramNotifier
from mikroclear.telegram.mangle_handler import TelegramMangleHandler
from mikroclear.telegram.polling import TelegramUpdatePoller
from mikroclear.telegram.polling_worker import TelegramPollingWorker
from mikroclear.telegram.unblock_handler import TelegramUnblockHandler


def log(message: str) -> None:
    print(f"[Mikro-Clear] {message}", flush=True)


@dataclass
class RuntimeProviders:
    settings: Settings
    version: str
    service_start_time: float
    router_client: RouterOSClient | None = None
    service: MikroClearService | None = None

    def __post_init__(self) -> None:
        self.dynamic_whitelist = DynamicWhitelistStore(
            Path(self.settings.dynamic_whitelist_file)
        )
        self.whitelist_policy = WhitelistPolicy(
            self.settings.whitelist_ips,
            self.dynamic_whitelist,
        )
        self.bot_settings = BotSettings.from_env()
        self.ignore_rules = IgnoreRules(log=log, debug_log=self.debug_log)
        self.tailer = EveJsonTailer(
            add_on_start=self.settings.add_on_start,
            shutdown_requested=self.shutdown_requested,
            log=log,
            debug_log=self.debug_log,
            sleep=sleep,
        )
        self.asset_resolver = AssetResolver(
            AssetResolverConfig(
                enable=self.settings.asset_resolver_enable,
                private_only=self.settings.asset_resolver_private_only,
                dhcp_enable=self.settings.asset_resolver_dhcp_enable,
                ptr_enable=self.settings.asset_resolver_ptr_enable,
                cache_ttl=self.settings.asset_resolver_cache_ttl,
            ),
            get_router_client=self.get_router_client,
            debug_log=self.debug_log,
            now=time,
        )
        self.notifier = TelegramNotifier(
            self.settings,
            peer_formatter=self.format_peer_with_asset,
            log=log,
            debug_log=self.debug_log,
            sanitize_exception_text=sanitize_exception_text,
            now=time,
        )
        self.unblock_handler = TelegramUnblockHandler(
            self.settings,
            get_router_client=self.get_router_client,
            log=log,
        )
        self.mangle_handler = TelegramMangleHandler(
            self.settings,
            get_router_client=self.get_router_client,
            log=log,
        )
        self.pipeline = AlertPipeline(
            client_factory=self.get_router_client,
            config=self.alert_processor_config(),
            validate_event=self.validate_event,
            ignore_predicate=self.ignore_rules.matches,
            send_telegram=self.notifier.send_alert,
            save_restore=self.save_restore_lists,
            save_interval=self.settings.save_interval,
            now=time,
            log=log,
            debug_log=self.debug_log,
        )
        self.poller = TelegramUpdatePoller(
            self.settings,
            bot_settings=self.bot_settings,
            status_snapshot_factory=self.build_status_snapshot,
            handle_unblock_action=self.unblock_handler.handle_unblock_action,
            answer_callback=self.unblock_handler.answer_telegram_callback,
            send_system_notification=self.notifier.send_system_notification,
            log=log,
            now=time,
            mangle_handler=self.mangle_handler,
        )
        self.polling_worker = TelegramPollingWorker(
            self.poller,
            long_poll_seconds=self.settings.telegram_long_poll_seconds,
            log=log,
        )

    def debug_log(self, message: str) -> None:
        if self.settings.debug_mode:
            timestamp = dt.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp} Mikro-Clear-DEBUG] {message}", flush=True)

    def shutdown_requested(self) -> bool:
        return bool(self.service and self.service.shutdown_requested)

    def ensure_dirs(self) -> None:
        for path in (
            self.settings.save_lists_location,
            self.settings.save_lists_location_v6,
            self.settings.uptime_bookmark,
            self.settings.ignore_list_location,
            self.settings.telegram_lock_file,
        ):
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)

    def print_startup_config(self) -> None:
        settings = self.settings
        log(f"Starting Mikro-Clear v{self.version}")
        log(f"eve.json: {settings.filepath}")
        log(f"RouterOS API: {settings.router_ip}:{settings.port} {'SSL' if settings.use_ssl else 'plain'}")
        log(f"CA file: {settings.ca_file if settings.use_ssl else 'N/A'}")
        log(f"Address-list: {settings.block_list_name}, timeout={settings.timeout}, monitor_only={settings.monitor_only}")
        log(f"Save interval: {settings.save_interval}s, heartbeat={settings.router_heartbeat_seconds}s")
        log(
            f"Asset resolver: {'enabled' if settings.asset_resolver_enable else 'disabled'}, "
            f"dhcp={'enabled' if settings.asset_resolver_dhcp_enable else 'disabled'}, "
            f"ptr={'enabled' if settings.asset_resolver_ptr_enable else 'disabled'}, "
            f"private_only={settings.asset_resolver_private_only}, ttl={settings.asset_resolver_cache_ttl}s"
        )
        log(f"Interfaces: {settings.listen_interfaces}, severities={settings.severity}")
        log(f"Telegram: {'enabled' if settings.enable_telegram else 'disabled'}")
        log(f"Debug: {'enabled' if settings.debug_mode else 'disabled'}")

    def get_router_client(self) -> RouterOSClient:
        if self.router_client is None:
            self.router_client = RouterOSClient(
                self.settings,
                log=log,
                send_system_notification=self.notifier.send_system_notification,
                sleep=sleep,
                time=time,
            )
        return self.router_client

    def alert_processor_config(self) -> AlertProcessorConfig:
        return AlertProcessorConfig(
            severities=self.settings.severity,
            listen_interfaces=self.settings.listen_interfaces,
            whitelist_ips=self.settings.whitelist_ips,
            whitelist_provider=self.whitelist_policy.snapshot,
            block_list_name=self.settings.block_list_name,
            timeout=self.settings.timeout,
            monitor_only=self.settings.monitor_only,
            enable_ipv6=self.settings.enable_ipv6,
            comment_time_format=self.settings.comment_time_format,
        )

    def state_store_config(self) -> StateStoreConfig:
        return StateStoreConfig(
            save_lists_location=self.settings.save_lists_location,
            save_lists_location_v6=self.settings.save_lists_location_v6,
            uptime_bookmark=self.settings.uptime_bookmark,
            save_lists=self.settings.save_lists,
            block_list_name=self.settings.block_list_name,
            timeout=self.settings.timeout,
            whitelist_ips=self.whitelist_policy.snapshot(),
        )

    def save_restore_lists(self, client: Any) -> None:
        address_list, address_list_v6, resources = client.paths()
        config = self.state_store_config()

        if check_tik_uptime(resources, config=config, debug_log=self.debug_log):
            log("Router reboot detected - restoring saved lists")
            self.notifier.send_system_notification("Router reboot detected - restoring saved address lists", "RESTORE")
            add_saved_lists(address_list, config=config, debug_log=self.debug_log)
            if self.settings.enable_ipv6 and address_list_v6 is not None:
                add_saved_lists(address_list_v6, config=config, is_v6=True, debug_log=self.debug_log)

        save_lists(address_list, config=config, debug_log=self.debug_log)

        if self.settings.enable_ipv6 and address_list_v6 is not None:
            save_lists(address_list_v6, config=config, is_v6=True, debug_log=self.debug_log)

    def validate_event(self, event: Any) -> dict[str, Any] | None:
        validated = validate_event(event)
        if validated is not None:
            return validated

        if not isinstance(event, dict):
            self.debug_log(f"Skipping non-dict event: {type(event)}")
            return None

        alert = event.get("alert")
        if not isinstance(alert, dict):
            self.debug_log("Skipping event without alert dict")
            return None

        if "signature_id" not in alert:
            self.debug_log("Skipping event without alert.signature_id")
            return None

        src_ip = event.get("src_ip")
        dest_ip = event.get("dest_ip")
        if not is_valid_ip(src_ip) or not is_valid_ip(dest_ip):
            self.debug_log(f"Skipping event with invalid src/dest IP: {src_ip} -> {dest_ip}")
            return None

        return None

    def format_peer_with_asset(self, ip_text: Any) -> str:
        if not ip_text:
            return "<code>N/A</code>"

        asset = self.asset_resolver.resolve(str(ip_text))
        name = asset.get("name", "")
        mac = asset.get("mac", "")
        comment = asset.get("comment", "")

        if not name:
            return f"<code>{escape_html_safe(ip_text)}</code>"

        result = f"<code>{escape_html_safe(ip_text)}</code> - <b>{escape_html_safe(name)}</b>"

        details = []
        if mac:
            details.append(f"MAC: <code>{escape_html_safe(mac)}</code>")
        if comment and comment != name:
            details.append(f"Comment: <code>{escape_html_safe(comment)}</code>")
        if details:
            result += "\n  " + "\n  ".join(details)
        return result

    def build_status_snapshot(self) -> Any:
        return build_status_snapshot(
            settings=self.settings,
            router_client=self.router_client,
            service_start_time=self.service_start_time,
            now=time,
            bot_settings_factory=lambda: self.bot_settings,
        )


__all__ = ["RuntimeProviders", "log"]
