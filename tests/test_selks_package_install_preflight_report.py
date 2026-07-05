from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "superpowers" / "preflight" / "2026-07-05-selks-package-install-preflight.md"


class SelksPackageInstallPreflightReportTests(TestCase):
    def test_report_records_service_identity_and_legacy_execstart(self):
        text = REPORT.read_text(encoding="utf-8")

        self.assertIn("Production service identity is correct: `mikroclear.service`", text)
        self.assertIn("FragmentPath=/etc/systemd/system/mikroclear.service", text)
        self.assertIn("/opt/mikroclear-venv/bin/python /usr/local/bin/mikroclear.py", text)

    def test_report_records_venv_pip_and_import_blocker(self):
        text = REPORT.read_text(encoding="utf-8")

        self.assertIn("Python 3.11.2", text)
        self.assertIn("pip 26.1.2", text)
        self.assertIn("ModuleNotFoundError: No module named 'mikroclear'", text)
        self.assertIn("no-go for systemd package-entrypoint switch", text)

    def test_report_keeps_package_install_as_separate_approval(self):
        text = REPORT.read_text(encoding="utf-8")

        self.assertIn("No push from SELKS, no deploy, no package install", text)
        self.assertIn("After explicit approval", text)
        self.assertIn("Do not run `systemctl`", text)
        self.assertIn("do not change", text)

    def test_report_records_rollback_anchors(self):
        text = REPORT.read_text(encoding="utf-8")

        self.assertIn("/usr/local/bin/mikroclear.py", text)
        self.assertIn("/etc/systemd/system/mikroclear.service", text)
        self.assertIn("/etc/mikrocata/mikrocataTZSP0.env", text)
