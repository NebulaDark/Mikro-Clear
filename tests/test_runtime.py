import types
from unittest import TestCase

from mikroclear.runtime import MikroClearService, RuntimeConfig, RuntimeDependencies


class FakeWatchManager:
    def __init__(self):
        self.watches = []

    def add_watch(self, path, mask, rec=False):
        self.watches.append((path, mask, rec))


class FakeNotifier:
    def __init__(self, watch_manager, handler):
        self.watch_manager = watch_manager
        self.handler = handler
        self.processed = 0
        self.stopped = False

    def process_events(self):
        self.processed += 1

    def check_events(self, timeout):
        return False

    def read_events(self):
        raise AssertionError("read_events should not be called")

    def stop(self):
        self.stopped = True


class FakeClient:
    def __init__(self, calls):
        self.calls = calls
        self.connected = False
        self.closed = False
        self.heartbeats = []

    def connect(self):
        self.connected = True

    def heartbeat(self, force=False):
        self.heartbeats.append(force)

    def close(self):
        self.closed = True
        self.calls.append(("client_close",))


class FakeClock:
    def __init__(self, values):
        self.values = list(values)

    def __call__(self):
        if len(self.values) == 1:
            return self.values[0]
        return self.values.pop(0)


class RuntimeServiceTests(TestCase):
    def make_dependencies(self, clock=None):
        calls = []
        client = FakeClient(calls)
        watch_manager = FakeWatchManager()
        notifier_box = {}

        def make_notifier(wm, handler):
            notifier = FakeNotifier(wm, handler)
            notifier_box["notifier"] = notifier
            return notifier

        deps = RuntimeDependencies(
            signal_module=types.SimpleNamespace(SIGTERM=15, SIGINT=2, signal=lambda signum, handler: calls.append(("signal", signum, handler))),
            pyinotify_module=types.SimpleNamespace(
                WatchManager=lambda: watch_manager,
                Notifier=make_notifier,
                IN_CREATE=1,
                IN_MODIFY=2,
                IN_DELETE=4,
                IN_MOVED_TO=8,
            ),
            event_handler_factory=lambda: object(),
            ensure_dirs=lambda: calls.append(("ensure_dirs",)),
            print_startup_config=lambda: calls.append(("print_startup_config",)),
            send_system_notification=lambda message, kind: calls.append(("send_system_notification", message, kind)),
            seek_to_end=lambda path: calls.append(("seek_to_end", path)),
            get_router_client=lambda: client,
            read_ignore_list=lambda path: calls.append(("read_ignore_list", path)),
            start_telegram_worker=lambda: calls.append(("start_telegram_worker",)),
            process_telegram_updates=lambda: calls.append(("process_telegram_updates",)),
            stop_telegram_worker=lambda: calls.append(("stop_telegram_worker",)),
            log=lambda message: calls.append(("log", message)),
            debug_traceback=lambda: "traceback",
            sleep=lambda seconds: calls.append(("sleep", seconds)),
            time=clock or FakeClock([0.0]),
        )
        return deps, calls, client, watch_manager, notifier_box

    def test_startup_sets_up_service_dependencies(self):
        deps, calls, client, watch_manager, notifier_box = self.make_dependencies()
        service = MikroClearService(
            RuntimeConfig(version="1.0", filepath="/var/log/eve.json", ignore_list_path="/state/ignore.conf"),
            deps,
        )

        service.startup()

        self.assertTrue(client.connected)
        self.assertEqual(client.heartbeats, [True])
        self.assertEqual(watch_manager.watches, [("/var/log", 15, False)])
        self.assertIn(("seek_to_end", "/var/log/eve.json"), calls)
        self.assertIn(("read_ignore_list", "/state/ignore.conf"), calls)
        self.assertIn(("send_system_notification", "Mikro-Clear v1.0 started", "START"), calls)
        self.assertIn(("start_telegram_worker",), calls)
        self.assertIn("notifier", notifier_box)

    def test_install_signal_handlers_registers_term_and_int(self):
        deps, calls, _client, _watch_manager, _notifier_box = self.make_dependencies()
        service = MikroClearService(RuntimeConfig(), deps)

        service.install_signal_handlers()

        self.assertEqual([item[:2] for item in calls], [("signal", 15), ("signal", 2)])

    def test_run_once_drains_telegram_and_processes_idle_heartbeat(self):
        deps, calls, client, _watch_manager, _notifier_box = self.make_dependencies(clock=FakeClock([10.0, 10.0]))
        service = MikroClearService(
            RuntimeConfig(telegram_updates_interval_seconds=5, router_heartbeat_seconds=5),
            deps,
        )
        service.startup()

        service.run_once()

        self.assertIn(("process_telegram_updates",), calls)
        self.assertEqual(client.heartbeats, [True, False])

    def test_shutdown_stops_notifier_closes_client_and_sends_stop_notification(self):
        deps, calls, client, _watch_manager, notifier_box = self.make_dependencies()
        service = MikroClearService(RuntimeConfig(version="1.0"), deps)
        service.startup()

        service.shutdown()

        self.assertTrue(notifier_box["notifier"].stopped)
        self.assertTrue(client.closed)
        self.assertLess(
            calls.index(("stop_telegram_worker",)),
            calls.index(("client_close",)),
        )
        self.assertIn(("send_system_notification", "Mikro-Clear v1.0 stopped", "STOP"), calls)
        self.assertIn(("log", "Stopped"), calls)
