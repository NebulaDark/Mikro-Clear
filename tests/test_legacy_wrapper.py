from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class LegacyWrapperTests(TestCase):
    def test_legacy_py_is_thin_compatibility_wrapper(self):
        legacy_path = ROOT / "src" / "mikroclear" / "legacy.py"
        runtime_path = ROOT / "src" / "mikroclear" / "legacy_runtime.py"

        self.assertTrue(runtime_path.exists())
        self.assertLessEqual(len(legacy_path.read_text(encoding="utf-8").splitlines()), 80)

    def test_legacy_wrapper_preserves_runtime_symbols(self):
        from mikroclear import legacy

        self.assertTrue(hasattr(legacy, "EventHandler"))
        self.assertTrue(hasattr(legacy, "RouterOSClient"))
        self.assertTrue(hasattr(legacy, "get_router_client"))
        self.assertTrue(hasattr(legacy, "process_telegram_updates"))
        self.assertTrue(hasattr(legacy, "_ensure_private_runtime_file"))

    def test_legacy_main_delegates_to_app_main(self):
        from mikroclear import legacy

        with patch("mikroclear.app.main", return_value=17) as app_main:
            self.assertEqual(legacy.main(), 17)

        app_main.assert_called_once_with()

    def test_legacy_cleanup_plan_is_recorded(self):
        plan = ROOT / "docs" / "superpowers" / "plans" / "2026-07-05-legacy-cleanup-plan.md"

        text = plan.read_text(encoding="utf-8")
        self.assertIn("legacy.py", text)
        self.assertIn("legacy_runtime.py", text)
        self.assertIn("thin compatibility wrapper", text)
