"""Top-level Mikro-Clear service orchestration."""

from __future__ import annotations

from time import sleep, time
import signal
import traceback

from mikroclear.runtime import MikroClearService, RuntimeConfig, RuntimeDependencies


def build_service() -> MikroClearService:
    from mikroclear import legacy_runtime as legacy

    return MikroClearService(
        RuntimeConfig(
            version=legacy.VERSION,
            filepath=legacy.FILEPATH,
            ignore_list_path=legacy.IGNORE_LIST_LOCATION,
            telegram_updates_interval_seconds=legacy.TELEGRAM_UPDATES_INTERVAL_SECONDS,
            router_heartbeat_seconds=legacy.ROUTER_HEARTBEAT_SECONDS,
            debug_mode=legacy.DEBUG_MODE,
        ),
        RuntimeDependencies(
            signal_module=signal,
            pyinotify_module=legacy.pyinotify,
            event_handler_factory=legacy.EventHandler,
            ensure_dirs=legacy.ensure_dirs,
            print_startup_config=legacy.print_startup_config,
            send_system_notification=legacy.send_system_notification,
            seek_to_end=legacy.seek_to_end,
            get_router_client=legacy.get_router_client,
            read_ignore_list=legacy.read_ignore_list,
            process_telegram_updates=legacy.process_telegram_updates,
            log=legacy.log,
            debug_traceback=traceback.format_exc,
            sleep=sleep,
            time=time,
        ),
    )


def main() -> int:
    return build_service().run()


__all__ = ["build_service", "main"]
