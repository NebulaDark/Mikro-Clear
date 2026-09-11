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

    def test_readme_documents_git_github_install_source(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for required in (
            "https://github.com/NebulaDark/Mikro-Clear.git",
            "git switch --detach <tag-or-commit>",
            "sudo ./scripts/install-selks.sh",
            "git archive HEAD",
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

    def test_docs_distinguish_runtime_whitelist_from_telegram_control(self):
        env_text = (ROOT / "docs/ru/env-reference.md").read_text(encoding="utf-8")
        guide = GUIDE.read_text(encoding="utf-8")
        combined = env_text + guide
        for required in (
            "ограничивают только Telegram-операции управления исключениями",
            "загружается независимо от Telegram-управления",
            "подавлении alert и восстановлении RouterOS",
            "не изменяет RouterOS и `dynamic-whitelist.json`",
            "`telegram-whitelist-actions.json` сохраняет обычный жизненный цикл",
            "append-only audit log",
        ):
            with self.subTest(required=required):
                self.assertIn(required, combined)

    def test_live_reproduction_pins_empty_baseline_privacy_and_mangle_fixture(self):
        text = REPRO.read_text(encoding="utf-8")
        for required in (
            "## STOP: отдельно одобряемая live-проверка",
            "192.168.250.250",
            "`managed whitelist: 0`",
            '{"version": 1, "addresses": []}',
            "не должен содержать `192.168.250.250`",
            "MIKROCLEAR_MANGLE_CONTROL_ENABLE=true",
            "MIKROCLEAR_BOT_MODULES=status,mangle_control,whitelist_control",
            "MC:STAND-MANGLE",
            "chain=`prerouting`",
            "action=`mark-routing`",
            "TEST-NET",
            "192.0.2.1/32",
            "198.51.100.1/32",
            '/ip/address/print where address~"192.0.2.1"',
            '/ip/address/print where address~"198.51.100.1"',
            '/ip/dhcp-server/lease/print where address="192.0.2.1"',
            '/ip/dhcp-server/lease/print where address="198.51.100.1"',
            '/ip/arp/print where address="192.0.2.1"',
            '/ip/arp/print where address="198.51.100.1"',
            '/routing/route/print where dst-address="192.0.2.1/32"',
            '/routing/route/print where dst-address="198.51.100.1/32"',
            '/routing/table/print where name="MC-STAND-TEST"',
            '/ip/firewall/mangle/print where comment="MC:STAND-MANGLE"',
            "/routing/table/add fib name=MC-STAND-TEST",
            "new-routing-mark=MC-STAND-TEST",
            "src-address=192.0.2.1/32",
            "dst-address=198.51.100.1/32",
            "disabled=yes",
            "`🛡 Mikro-Clear` → `🔀 Mangle` → `❌ STAND-MANGLE`",
            "`❌ STAND-MANGLE` → `✅ STAND-MANGLE` → `❌ STAND-MANGLE`",
            "`🛡 Mikro-Clear` → `📊 Статус` → `🔀 Mangle`",
            "`Packets:` и `Bytes:`",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)
