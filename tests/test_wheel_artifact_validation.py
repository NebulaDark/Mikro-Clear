import importlib.util
import io
from pathlib import Path
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from unittest import TestCase
import zipfile


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts" / "validate_wheel_artifact.py"
PLAN = ROOT / "docs" / "superpowers" / "plans" / "2026-07-05-wheel-artifact-validation.md"


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_wheel_artifact", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_wheel(path: Path, *, omit: set[str] | None = None, entry_points: str | None = None) -> None:
    omit = omit or set()
    entry_points = entry_points if entry_points is not None else "[console_scripts]\nmikroclear = mikroclear.cli:main\n"
    members = {
        "mikroclear/__main__.py": "from .cli import main\nraise SystemExit(main())\n",
        "mikroclear/cli.py": "from . import app\n\ndef main():\n    return app.main()\n",
        "mikroclear/app.py": "def main():\n    return 0\n",
        "mikroclear/runtime.py": "class MikroClearService:\n    pass\n",
        "mikro_clear-0.1.0.dist-info/entry_points.txt": entry_points,
    }
    with zipfile.ZipFile(path, "w") as wheel:
        for name, content in members.items():
            if name not in omit:
                wheel.writestr(name, content)


class WheelArtifactValidationTests(TestCase):
    def setUp(self):
        self.validator = load_validator()

    def test_valid_wheel_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "mikro_clear-0.1.0-py3-none-any.whl"
            write_wheel(wheel)

            result = self.validator.validate_wheel(wheel)

        self.assertTrue(result.ok)
        self.assertEqual(result.errors, ())

    def test_missing_runtime_module_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "mikro_clear-0.1.0-py3-none-any.whl"
            write_wheel(wheel, omit={"mikroclear/runtime.py"})

            result = self.validator.validate_wheel(wheel)

        self.assertFalse(result.ok)
        self.assertIn("missing required member: mikroclear/runtime.py", result.errors)

    def test_missing_console_script_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "mikro_clear-0.1.0-py3-none-any.whl"
            write_wheel(wheel, entry_points="[console_scripts]\nother = mikroclear.cli:main\n")

            result = self.validator.validate_wheel(wheel)

        self.assertFalse(result.ok)
        self.assertIn("missing console script: mikroclear = mikroclear.cli:main", result.errors)

    def test_cli_returns_zero_for_valid_wheel(self):
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "mikro_clear-0.1.0-py3-none-any.whl"
            write_wheel(wheel)

            with redirect_stdout(io.StringIO()):
                exit_code = self.validator.main([str(wheel)])

        self.assertEqual(exit_code, 0)

    def test_cli_returns_one_for_invalid_wheel(self):
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "mikro_clear-0.1.0-py3-none-any.whl"
            write_wheel(wheel, omit={"mikroclear/app.py"})

            with redirect_stderr(io.StringIO()):
                exit_code = self.validator.main([str(wheel)])

        self.assertEqual(exit_code, 1)

    def test_plan_documents_non_deploy_validation_commands(self):
        text = PLAN.read_text(encoding="utf-8")

        self.assertIn("No push, no deploy, no SELKS changes", text)
        self.assertIn("pip wheel --no-deps --no-build-isolation", text)
        self.assertIn("scripts/validate_wheel_artifact.py", text)
        self.assertIn("/tmp/mikroclear-wheel-validation", text)
