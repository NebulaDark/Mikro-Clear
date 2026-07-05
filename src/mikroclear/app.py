"""Top-level Mikro-Clear service orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import os
import signal
from time import sleep, time
import traceback
from typing import Any

import requests

from mikroclear.assets.resolver import AssetResolver, AssetResolverConfig
from mikroclear.bot.modules.status import StatusSnapshot
from mikroclear.bot.settings import BotSettings
from mikroclear.events import validate_event
from mikroclear.runtime import MikroClearService, RuntimeConfig, RuntimeDependencies
from mikroclear.routeros.client import RouterOSClient, remove_from_address_list
from mikroclear.security import sanitize_exception_text
from mikroclear.settings import Settings, load_settings
from mikroclear.state.address_list_store import StateStoreConfig, add_saved_lists, save_lists
from mikroclear.state.files import ensure_private_runtime_file
from mikroclear.state.uptime import check_tik_uptime
from mikroclear.suricata.alert_logic import is_ip_in_whitelist, is_valid_ip
from mikroclear.suricata.event_handler import make_event_handler
from mikroclear.suricata.eve_tailer import EveJsonTailer
from mikroclear.suricata.ignore_rules import IgnoreRules
from mikroclear.suricata.pipeline import AlertPipeline, AlertProcessorConfig
from mikroclear.telegram.formatting import escape_html_safe, format_system_message
from mikroclear.telegram.notify import TelegramNotifier
from mikroclear.telegram.polling import TelegramUpdatePoller
from mikroclear.telegram.unblock import UnblockCallbackResult

VERSION = "3.1.1-TZSP0-ASSET-RESOLVER"


try:
    import pyinotify  # type: ignore
except Exception:  # pragma: no cover - import-safe package entrypoint fallback
    class _MissingPyinotify:
        ProcessEvent = object
        IN_CREATE = 0
        IN_MODIFY = 0
        IN_DELETE = 0
        IN_MOVED_TO = 0

        def WatchManager(self) -> Any:
            raise RuntimeError("pyinotify is required to run Mikro-Clear on production Linux")

        def Notifier(self, watch_manager: Any, handler: Any) -> Any:
            raise RuntimeError("pyinotify is required to run Mikro-Clear on production Linux")

    pyinotify = _MissingPyinotify()  # type: ignore


def log(message: str) -> None:
    print(f"[Mikro-Clear] {message}", flush=True)


@dataclass
class RuntimeProviders:
    settings: Settings
    service_start_time: float
    router_client: RouterOSClient | None = None
    service: MikroClearService | None = None

    def __post_init__(self) -> None:
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
            status_snapshot_factory=self.build_status_snapshot,
            handle_unblock_action=self.handle_unblock_action,
            answer_callback=self.answer_telegram_callback,
            send_system_notification=self.notifier.send_system_notification,
            log=log,
            now=time,
        )

    def debug_log(self, message: str) -> None:
        if self.settings.debug_mode:
            from datetime import datetime as dt

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
        log(f"Starting Mikro-Clear v{VERSION}")
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
            whitelist_ips=self.settings.whitelist_ips,
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
        source = asset.get("source", "")
        mac = asset.get("mac", "")
        comment = asset.get("comment", "")

        if not name:
            return f"<code>{escape_html_safe(ip_text)}</code>"

        result = f"<code>{escape_html_safe(ip_text)}</code> - <b>{escape_html_safe(name)}</b>"
        if source:
            result += f" <code>{escape_html_safe(source)}</code>"

        details = []
        if mac:
            details.append(f"MAC: <code>{escape_html_safe(mac)}</code>")
        if comment and comment != name:
            details.append(f"Comment: <code>{escape_html_safe(comment)}</code>")
        if details:
            result += "\n  " + "\n  ".join(details)
        return result

    def handle_unblock_action(self, action: dict[str, Any]) -> UnblockCallbackResult:
        wanted_ip = str(action.get("wanted_ip", ""))
        list_name = str(action.get("list_name") or self.settings.block_list_name)
        if not is_valid_ip(wanted_ip):
            log(f"TELEGRAM UNBLOCK INVALID: {wanted_ip or '<empty>'} from {list_name}")
            return UnblockCallbackResult("Invalid unblock target", False, True)
        if is_ip_in_whitelist(wanted_ip, self.settings.whitelist_ips):
            log(f"TELEGRAM UNBLOCK REFUSED: {wanted_ip} is whitelisted")
            return UnblockCallbackResult(f"Refusing to unblock whitelisted target {wanted_ip}", False, True)

        client = self.get_router_client()

        def remove_batch() -> bool:
            address_list, address_list_v6, _resources = client.paths()
            target_list = address_list_v6 if ":" in wanted_ip and address_list_v6 is not None else address_list
            return remove_from_address_list(target_list, wanted_ip, list_name) > 0

        try:
            removed = client.run_with_reconnect("telegram unblock", remove_batch)
        except Exception as exc:
            log(f"TELEGRAM UNBLOCK FAILED: {wanted_ip} from {list_name} - {type(exc).__name__}: {exc}")
            return UnblockCallbackResult(f"Could not unblock {wanted_ip}", False, True)

        if removed:
            log(f"TELEGRAM UNBLOCKED: {wanted_ip} from {list_name} - SID:{action.get('sid', 'N/A')}")
            return UnblockCallbackResult(f"Unblocked {wanted_ip}", True)
        log(f"TELEGRAM UNBLOCK NOOP: {wanted_ip} not found in {list_name}")
        return UnblockCallbackResult(f"{wanted_ip} was not found in {list_name}", False)

    def answer_telegram_callback(self, callback_id: str, text: str, alert: bool = False) -> None:
        if not self.settings.telegram_token or not callback_id:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.settings.telegram_token}/answerCallbackQuery",
                data={"callback_query_id": callback_id, "text": text, "show_alert": "true" if alert else "false"},
                timeout=self.settings.telegram_timeout,
            )
        except Exception as exc:
            log(f"Error answering Telegram callback: {sanitize_exception_text(exc, self.settings.telegram_token)}")

    def build_status_snapshot(self) -> StatusSnapshot:
        client = self.router_client
        connected_at = float(getattr(client, "connected_at", 0.0) or 0.0)
        connected = bool(getattr(client, "api", None))
        connected_seconds = int(time() - connected_at) if connected and connected_at else 0
        return StatusSnapshot(
            uptime_seconds=int(time() - self.service_start_time),
            routeros_connected=connected,
            routeros_connected_seconds=connected_seconds,
            eve_path=self.settings.filepath,
            block_list_name=self.settings.block_list_name,
            monitor_only=self.settings.monitor_only,
            telegram_unblock_enabled=self.settings.telegram_unblock_enable,
            state_dir=self.settings.state_dir,
            bot_settings=BotSettings.from_env(),
        )


def build_service() -> MikroClearService:
    settings = load_settings()
    providers = RuntimeProviders(settings=settings, service_start_time=time())

    handler_type = make_event_handler(
        pyinotify,
        filepath=settings.filepath,
        tailer=providers.tailer,
        process_alerts=providers.pipeline.process_alerts,
        log=log,
        debug_traceback=traceback.format_exc,
        debug_enabled=lambda: settings.debug_mode,
    )

    service = MikroClearService(
        RuntimeConfig(
            version=VERSION,
            filepath=settings.filepath,
            ignore_list_path=settings.ignore_list_location,
            telegram_updates_interval_seconds=settings.telegram_updates_interval_seconds,
            router_heartbeat_seconds=settings.router_heartbeat_seconds,
            debug_mode=settings.debug_mode,
        ),
        RuntimeDependencies(
            signal_module=signal,
            pyinotify_module=pyinotify,
            event_handler_factory=handler_type,
            ensure_dirs=providers.ensure_dirs,
            print_startup_config=providers.print_startup_config,
            send_system_notification=providers.notifier.send_system_notification,
            seek_to_end=providers.tailer.seek_to_end,
            get_router_client=providers.get_router_client,
            read_ignore_list=providers.ignore_rules.load,
            process_telegram_updates=providers.poller.process_updates,
            log=log,
            debug_traceback=traceback.format_exc,
            sleep=sleep,
            time=time,
        ),
    )
    providers.service = service
    return service


def main() -> int:
    return build_service().run()


__all__ = ["build_service", "main"]
