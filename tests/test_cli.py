import runpy
from pathlib import Path
import sys
import tomllib
import types
from unittest import TestCase
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def fake_pyinotify_module() -> types.SimpleNamespace:
    return types.SimpleNamespace(ProcessEvent=object)


class CliEntrypointTests(TestCase):
    def test_pyproject_declares_mikroclear_console_script(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            data["project"]["scripts"]["mikroclear"],
            "mikroclear.cli:main",
        )

    def test_cli_main_delegates_to_app_main(self):
        with patch.dict(sys.modules, {"pyinotify": fake_pyinotify_module()}):
            from mikroclear import cli

        with patch.object(cli.app, "main", return_value=7) as app_main:
            self.assertEqual(cli.main(), 7)

        app_main.assert_called_once_with()

    def test_python_module_entrypoint_delegates_to_cli_main(self):
        with (
            patch.dict(sys.modules, {"pyinotify": fake_pyinotify_module()}),
            patch("mikroclear.cli.main", return_value=0) as cli_main,
        ):
            with self.assertRaises(SystemExit) as exit_context:
                runpy.run_module("mikroclear", run_name="__main__")

        cli_main.assert_called_once_with()
        self.assertEqual(exit_context.exception.code, 0)
