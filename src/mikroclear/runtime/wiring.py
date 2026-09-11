"""Runtime service wiring."""

from time import sleep, time
import signal
import traceback
from typing import Any

from mikroclear.runtime import MikroClearService, RuntimeConfig, RuntimeDependencies
from mikroclear.runtime.providers import RuntimeProviders, log
from mikroclear.settings import Settings
from mikroclear.suricata.event_handler import make_event_handler

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


def build_runtime_service(settings: Settings) -> MikroClearService:
    providers = RuntimeProviders(settings=settings, version=VERSION, service_start_time=time())

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
            restore_router_state=providers.restore_saved_lists_if_rebooted,
            read_ignore_list=providers.ignore_rules.load,
            start_telegram_worker=providers.polling_worker.start,
            check_telegram_worker=providers.polling_worker.check_health,
            process_telegram_updates=providers.polling_worker.drain_ready,
            stop_telegram_worker=providers.polling_worker.stop,
            log=log,
            debug_traceback=traceback.format_exc,
            sleep=sleep,
            time=time,
        ),
    )
    providers.service = service
    return service


__all__ = ["VERSION", "build_runtime_service"]
