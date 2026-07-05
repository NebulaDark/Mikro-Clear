import sys
import types
from unittest import TestCase
from unittest.mock import patch


def fake_pyinotify_module() -> types.SimpleNamespace:
    return types.SimpleNamespace(ProcessEvent=object)


class AppEntrypointTests(TestCase):
    def test_app_main_keeps_legacy_runtime_fallback(self):
        with patch.dict(sys.modules, {"pyinotify": fake_pyinotify_module()}):
            from mikroclear import legacy
            from mikroclear.app import main

            with patch.object(legacy, "main", return_value=9) as legacy_main:
                self.assertEqual(main(), 9)

        legacy_main.assert_called_once_with()
