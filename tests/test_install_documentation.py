from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/ru/install-from-github.md"
REPRO = ROOT / "docs/ru/install-test-reproduction.md"


class InstallDocumentationTests(TestCase):
    def test_guide_covers_both_modes_and_manual_install(self):
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "./scripts/install-selks.sh",
            "--interactive",
            "--config-template",
            "--start",
            "Ручная установка",
            "Обновление",
            "Rollback",
            "/status",
            "Debian 12",
            "Debian 13",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)

    def test_new_install_docs_have_no_external_or_legacy_install_dependency(self):
        for path in (GUIDE, REPRO):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("/etc/mikrocata/certs", text)
                self.assertNotIn("/home/mgm/.ssh", text)
                self.assertNotIn("mcp-selks", text.lower())
                self.assertNotIn("MCP", text)

    def test_reproduction_matrix_is_executable(self):
        text = REPRO.read_text(encoding="utf-8")
        for required in (
            "Debian 12",
            "Debian 13",
            "Чистая установка",
            "Повторный запуск",
            "Успешное обновление",
            "Неуспешное обновление",
            "rollback",
            "eve.json",
            "Telegram выключен",
            "Telegram включён",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)
