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

    def test_docs_cover_menu_and_managed_exception_reproduction(self):
        env_text = (ROOT / "docs/ru/env-reference.md").read_text(encoding="utf-8")
        repro = REPRO.read_text(encoding="utf-8")
        example = (ROOT / "config/mikroclear.env.example").read_text(
            encoding="utf-8"
        )
        for required in (
            "MIKROCLEAR_TELEGRAM_WHITELIST_CONTROL_ENABLE=false",
            "dynamic-whitelist.json",
            "whitelist_control",
        ):
            with self.subTest(required=required):
                self.assertIn(required, example + env_text)
        for required in (
            "🛡 Mikro-Clear",
            "🛡 Добавить в исключения",
            "🔄 Повторить разблокировку",
            "удаление исключения",
            "повторно подать",
        ):
            with self.subTest(required=required):
                self.assertIn(required, repro)
