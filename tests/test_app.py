import sys
import types
from unittest import TestCase
from unittest.mock import patch


def fake_pyinotify_module() -> types.SimpleNamespace:
    return types.SimpleNamespace(ProcessEvent=object)


class AppEntrypointTests(TestCase):
    def test_app_main_builds_and_runs_runtime_service(self):
        with patch.dict(sys.modules, {"pyinotify": fake_pyinotify_module()}):
            from mikroclear import app

        service = types.SimpleNamespace(run=lambda: 9)
        with patch.object(app, "build_service", return_value=service) as build_service:
            self.assertEqual(app.main(), 9)

        build_service.assert_called_once_with()

    def test_build_service_uses_runtime_service(self):
        with patch.dict(sys.modules, {"pyinotify": fake_pyinotify_module()}):
            from mikroclear import app
            from mikroclear.runtime import MikroClearService

            service = app.build_service()

        self.assertIsInstance(service, MikroClearService)
