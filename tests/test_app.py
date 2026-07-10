import sys
import types
import importlib
import builtins
import os
from unittest import TestCase
from unittest.mock import Mock, patch


def fake_pyinotify_module() -> types.SimpleNamespace:
    return types.SimpleNamespace(ProcessEvent=object)


class AppEntrypointTests(TestCase):
    def test_import_app_does_not_import_legacy_runtime(self):
        original_app = sys.modules.pop("mikroclear.app", None)
        original_legacy = sys.modules.pop("mikroclear.legacy", None)
        original_legacy_runtime = sys.modules.pop("mikroclear.legacy_runtime", None)
        try:
            app = importlib.import_module("mikroclear.app")

            self.assertEqual(app.__all__, ["build_service", "main"])
            self.assertNotIn("mikroclear.legacy", sys.modules)
            self.assertNotIn("mikroclear.legacy_runtime", sys.modules)
        finally:
            if original_app is not None:
                sys.modules["mikroclear.app"] = original_app
            else:
                sys.modules.pop("mikroclear.app", None)
            if original_legacy is not None:
                sys.modules["mikroclear.legacy"] = original_legacy
            else:
                sys.modules.pop("mikroclear.legacy", None)
            if original_legacy_runtime is not None:
                sys.modules["mikroclear.legacy_runtime"] = original_legacy_runtime
            else:
                sys.modules.pop("mikroclear.legacy_runtime", None)

    def test_build_service_does_not_import_legacy_runtime(self):
        original_app = sys.modules.pop("mikroclear.app", None)
        original_legacy_runtime = sys.modules.pop("mikroclear.legacy_runtime", None)
        real_import = builtins.__import__

        def import_without_legacy_runtime(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "mikroclear.legacy_runtime" or (
                name == "mikroclear" and "legacy_runtime" in tuple(fromlist or ())
            ):
                raise AssertionError("app.build_service must not load the retired runtime module")
            return real_import(name, globals, locals, fromlist, level)

        try:
            with patch.dict(sys.modules, {"pyinotify": fake_pyinotify_module()}):
                app = importlib.import_module("mikroclear.app")
                with patch.object(builtins, "__import__", side_effect=import_without_legacy_runtime):
                    service = app.build_service()

            self.assertEqual(type(service).__name__, "MikroClearService")
            self.assertNotIn("mikroclear.legacy_runtime", sys.modules)
        finally:
            if original_app is not None:
                sys.modules["mikroclear.app"] = original_app
            else:
                sys.modules.pop("mikroclear.app", None)
            if original_legacy_runtime is not None:
                sys.modules["mikroclear.legacy_runtime"] = original_legacy_runtime
            else:
                sys.modules.pop("mikroclear.legacy_runtime", None)

    def test_app_main_builds_and_runs_runtime_service(self):
        with patch.dict(sys.modules, {"pyinotify": fake_pyinotify_module()}):
            from mikroclear import app

        service = types.SimpleNamespace(run=Mock(return_value=9))
        with patch.object(app, "build_service", return_value=service) as build_service:
            self.assertEqual(app.main(), 9)

        build_service.assert_called_once_with()
        service.run.assert_called_once_with()

    def test_app_main_does_not_call_legacy_main(self):
        with patch.dict(sys.modules, {"pyinotify": fake_pyinotify_module()}):
            from mikroclear import app
            from mikroclear import legacy

        service = types.SimpleNamespace(run=Mock(return_value=13))
        with (
            patch.object(app, "build_service", return_value=service),
            patch.object(legacy, "main", return_value=99) as legacy_main,
        ):
            self.assertEqual(app.main(), 13)

        legacy_main.assert_not_called()
        service.run.assert_called_once_with()

    def test_build_service_uses_runtime_service(self):
        with patch.dict(sys.modules, {"pyinotify": fake_pyinotify_module()}):
            from mikroclear import app

            service = app.build_service()

        self.assertEqual(type(service).__name__, "MikroClearService")
        self.assertTrue(hasattr(service, "run"))

    def test_build_service_wires_notifier_poller_and_handlers(self):
        with patch.dict(sys.modules, {"pyinotify": fake_pyinotify_module()}):
            from mikroclear import app
            from mikroclear.telegram.mangle_handler import TelegramMangleHandler
            from mikroclear.telegram.notify import TelegramNotifier
            from mikroclear.telegram.polling import TelegramUpdatePoller
            from mikroclear.telegram.unblock_handler import TelegramUnblockHandler

            service = app.build_service()

        providers = service.deps.get_router_client.__self__
        self.assertIsInstance(providers.notifier, TelegramNotifier)
        self.assertIs(providers.pipeline.send_telegram.__self__, providers.notifier)
        self.assertIs(providers.pipeline.send_telegram.__func__, providers.notifier.send_alert.__func__)
        self.assertEqual(type(providers.unblock_handler).__name__, TelegramUnblockHandler.__name__)
        self.assertEqual(type(providers.mangle_handler).__name__, TelegramMangleHandler.__name__)
        self.assertEqual(type(providers.poller).__name__, TelegramUpdatePoller.__name__)
        self.assertIs(providers.poller.bot_settings, providers.bot_settings)
        self.assertIs(providers.poller.mangle_handler, providers.mangle_handler)
        self.assertIs(providers.poller.handle_unblock_action.__self__, providers.unblock_handler)
        self.assertIs(
            providers.poller.handle_unblock_action.__func__,
            providers.unblock_handler.handle_unblock_action.__func__,
        )
        self.assertIs(providers.poller.send_system_notification.__self__, providers.notifier)
        self.assertIs(
            providers.poller.send_system_notification.__func__,
            providers.notifier.send_system_notification.__func__,
        )
        providers.asset_resolver.resolve = lambda ip: {"name": "i5", "source": "dhcp", "mac": "", "comment": ""}
        formatted_peer = providers.format_peer_with_asset("192.168.10.9")
        self.assertEqual(formatted_peer, "<code>192.168.10.9</code> - <b>i5</b>")
        self.assertNotIn("dhcp", formatted_peer)

    def test_build_status_snapshot_uses_runtime_bot_settings_when_environment_changes(self):
        env = {
            "MIKROCLEAR_BOT_DRY_RUN": "false",
            "MIKROCLEAR_BOT_MODULES": "status,asset_resolver",
        }
        with (
            patch.dict(sys.modules, {"pyinotify": fake_pyinotify_module()}),
            patch.dict(os.environ, env, clear=True),
        ):
            from mikroclear import app

            service = app.build_service()

        providers = service.deps.get_router_client.__self__
        with patch.dict(os.environ, {}, clear=True):
            snapshot = providers.build_status_snapshot()

        self.assertIs(snapshot.bot_settings, providers.bot_settings)
        self.assertFalse(snapshot.bot_settings.dry_run)
        self.assertEqual(snapshot.bot_settings.modules, ("status", "asset_resolver"))

    def test_build_service_is_import_safe_when_pyinotify_is_unavailable(self):
        original_legacy = sys.modules.pop("mikroclear.legacy", None)
        try:
            with patch.dict(sys.modules, {"pyinotify": None}):
                from mikroclear import app

                service = app.build_service()

            self.assertEqual(type(service).__name__, "MikroClearService")
            self.assertTrue(hasattr(service, "run"))
        finally:
            sys.modules.pop("mikroclear.legacy", None)
            if original_legacy is not None:
                sys.modules["mikroclear.legacy"] = original_legacy

    def test_legacy_main_is_compatibility_wrapper_for_app_main(self):
        with patch.dict(sys.modules, {"pyinotify": fake_pyinotify_module()}):
            from mikroclear import app
            from mikroclear import legacy

        with patch.object(app, "main", return_value=11) as app_main:
            self.assertEqual(legacy.main(), 11)

        app_main.assert_called_once_with()
