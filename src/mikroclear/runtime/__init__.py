"""Runtime lifecycle helpers."""

from dataclasses import dataclass
import os
from typing import Any, Callable

from mikroclear.telegram.polling_worker import TelegramWorkerFatalError


@dataclass(frozen=True)
class RuntimeConfig:
    version: str = ""
    filepath: str = ""
    ignore_list_path: str = ""
    telegram_updates_interval_seconds: int = 5
    router_heartbeat_seconds: int = 60
    debug_mode: bool = False


@dataclass(frozen=True)
class RuntimeDependencies:
    signal_module: Any
    pyinotify_module: Any
    event_handler_factory: Callable[[], Any]
    ensure_dirs: Callable[[], None]
    print_startup_config: Callable[[], None]
    send_system_notification: Callable[[str, str], Any]
    seek_to_end: Callable[[str], None]
    get_router_client: Callable[[], Any]
    read_ignore_list: Callable[[str], None]
    start_telegram_worker: Callable[[], None]
    check_telegram_worker: Callable[[], None]
    process_telegram_updates: Callable[[], None]
    stop_telegram_worker: Callable[[], None]
    log: Callable[[str], None]
    debug_traceback: Callable[[], str]
    sleep: Callable[[int], None]
    time: Callable[[], float]


class MikroClearService:
    def __init__(self, config: RuntimeConfig, deps: RuntimeDependencies) -> None:
        self.config = config
        self.deps = deps
        self.shutdown_requested = False
        self.client: Any = None
        self.notifier: Any = None
        self.last_idle_heartbeat = 0.0
        self.last_telegram_updates_check = 0.0

    def on_signal(self, signum: int, frame: Any) -> None:
        self.shutdown_requested = True
        self.deps.log(f"Signal {signum} received, stopping gracefully...")

    def install_signal_handlers(self) -> None:
        self.deps.signal_module.signal(self.deps.signal_module.SIGTERM, self.on_signal)
        self.deps.signal_module.signal(self.deps.signal_module.SIGINT, self.on_signal)

    def startup(self) -> None:
        self.deps.ensure_dirs()
        self.deps.print_startup_config()
        self.deps.send_system_notification(f"Mikro-Clear v{self.config.version} started", "START")
        self.deps.seek_to_end(self.config.filepath)

        self.client = self.deps.get_router_client()
        self.client.connect()
        self.client.heartbeat(force=True)

        self.deps.read_ignore_list(self.config.ignore_list_path)
        self._start_file_watcher()
        self.deps.log(f"Monitoring {self.config.filepath} for Suricata alerts")
        self.deps.start_telegram_worker()

    def _start_file_watcher(self) -> None:
        directory_to_monitor = os.path.dirname(self.config.filepath) or "."
        watch_manager = self.deps.pyinotify_module.WatchManager()
        handler = self.deps.event_handler_factory()
        self.notifier = self.deps.pyinotify_module.Notifier(watch_manager, handler)
        mask = (
            self.deps.pyinotify_module.IN_CREATE
            | self.deps.pyinotify_module.IN_MODIFY
            | self.deps.pyinotify_module.IN_DELETE
            | self.deps.pyinotify_module.IN_MOVED_TO
        )
        watch_manager.add_watch(directory_to_monitor, mask, rec=False)

    def run_once(self) -> None:
        if self.notifier is None or self.client is None:
            raise RuntimeError("MikroClearService.startup() must be called before run_once()")

        self.deps.check_telegram_worker()
        self.notifier.process_events()
        if self.notifier.check_events(timeout=1000):
            self.notifier.read_events()

        self.deps.process_telegram_updates()

        now = self.deps.time()
        if now - self.last_idle_heartbeat >= self.config.router_heartbeat_seconds:
            self.last_idle_heartbeat = now
            self.client.heartbeat()

    def run(self) -> int:
        self.install_signal_handlers()
        self.startup()

        exit_code = 0
        try:
            while not self.shutdown_requested:
                try:
                    self.run_once()
                except TelegramWorkerFatalError as exc:
                    self.deps.log(f"Fatal Telegram polling worker error: {exc}")
                    exit_code = 1
                    break
                except KeyboardInterrupt:
                    break
                except Exception as exc:
                    self.deps.log(f"Unexpected error in main loop: {type(exc).__name__}: {exc}")
                    if self.config.debug_mode:
                        print(self.deps.debug_traceback(), flush=True)
                    self.deps.sleep(5)
        finally:
            self.shutdown()
        return exit_code

    def shutdown(self) -> None:
        self.deps.stop_telegram_worker()
        if self.notifier is not None:
            try:
                self.notifier.stop()
            except Exception:
                pass

        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass

        self.deps.send_system_notification(f"Mikro-Clear v{self.config.version} stopped", "STOP")
        self.deps.log("Stopped")


__all__ = ["MikroClearService", "RuntimeConfig", "RuntimeDependencies"]
