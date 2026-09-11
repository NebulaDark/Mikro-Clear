from unittest import TestCase
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectStructureTests(TestCase):
    def test_canonical_runtime_modules_are_importable(self):
        import mikroclear.app
        import mikroclear.assets.resolver
        import mikroclear.bot.auth
        import mikroclear.bot.dispatcher
        import mikroclear.bot.mangle_control
        import mikroclear.bot.modules.status
        import mikroclear.bot.settings
        import mikroclear.logging
        import mikroclear.runtime
        import mikroclear.runtime.providers
        import mikroclear.runtime.status_snapshot
        import mikroclear.runtime.wiring
        import mikroclear.settings
        import mikroclear.state.address_list_store
        import mikroclear.state.files
        import mikroclear.state.uptime
        import mikroclear.suricata.eve_tailer
        import mikroclear.telegram.formatting
        import mikroclear.telegram.notify
        import mikroclear.telegram.mangle_handler
        import mikroclear.telegram.polling
        import mikroclear.telegram.unblock
        import mikroclear.routeros.mangle

        self.assertEqual(mikroclear.app.__all__, ["build_service", "main"])
        self.assertEqual(mikroclear.settings.__all__, ["Settings", "load_settings"])

    def test_canonical_modules_do_not_import_old_top_level_shims(self):
        forbidden = {
            "src/mikroclear/assets/resolver.py": ("mikroclear.asset_resolver",),
            "src/mikroclear/state/files.py": ("mikroclear.state_store",),
            "src/mikroclear/state/address_list_store.py": ("mikroclear.state_store",),
            "src/mikroclear/state/uptime.py": ("mikroclear.state_store",),
            "src/mikroclear/suricata/eve_tailer.py": ("mikroclear.eve_watcher",),
            "src/mikroclear/telegram/formatting.py": ("mikroclear.telegram.notify",),
            "src/mikroclear/routeros/address_list.py": ("mikroclear.routeros.client",),
        }

        failures = []
        for relative, forbidden_imports in forbidden.items():
            text = (ROOT / relative).read_text(encoding="utf-8")
            for forbidden_import in forbidden_imports:
                if forbidden_import in text:
                    failures.append(f"{relative} imports {forbidden_import}")

        self.assertEqual(failures, [])

    def test_legacy_import_paths_are_removed(self):
        import importlib

        for module_name in ("mikrocata", "mikroclear.state_store", "mikroclear.alert_logic"):
            with self.assertRaises(ModuleNotFoundError):
                importlib.import_module(module_name)

    def test_app_is_thin_runtime_entrypoint(self):
        app_text = (ROOT / "src/mikroclear/app.py").read_text(encoding="utf-8")

        self.assertLessEqual(len(app_text.splitlines()), 80)
        self.assertNotIn("class RuntimeProviders", app_text)
        self.assertNotIn("def handle_unblock_action", app_text)
        self.assertNotIn("def build_status_snapshot", app_text)

    def test_runtime_wiring_modules_are_importable(self):
        import mikroclear.runtime.providers
        import mikroclear.runtime.status_snapshot
        import mikroclear.runtime.wiring
        import mikroclear.telegram.unblock_handler
        import mikroclear.telegram.mangle_handler

        self.assertTrue(hasattr(mikroclear.runtime.providers, "RuntimeProviders"))
        self.assertTrue(hasattr(mikroclear.runtime.wiring, "build_runtime_service"))
        self.assertTrue(hasattr(mikroclear.runtime.status_snapshot, "build_status_snapshot"))
        self.assertTrue(hasattr(mikroclear.telegram.unblock_handler, "TelegramUnblockHandler"))
        self.assertTrue(hasattr(mikroclear.telegram.mangle_handler, "TelegramMangleHandler"))
