from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "superpowers" / "deploy" / "2026-07-05-package-entrypoint-switch.md"


class PackageEntrypointDeployReportTests(TestCase):
    def test_report_records_successful_package_entrypoint_switch(self):
        text = REPORT.read_text(encoding="utf-8")

        self.assertIn("production `mikroclear.service` now runs from the package entrypoint", text)
        self.assertIn("/opt/mikroclear-venv/bin/python -m mikroclear", text)
        self.assertIn("ActiveState=active", text)
        self.assertIn("SubState=running", text)
        self.assertIn("NRestarts=0", text)

    def test_report_records_initial_namespace_failure_and_fix(self):
        text = REPORT.read_text(encoding="utf-8")

        self.assertIn("status=226/NAMESPACE", text)
        self.assertIn("/var/lib/mikroclear", text)
        self.assertIn("/etc/mikroclear", text)
        self.assertIn("created by the root operator", text)

    def test_report_records_rollback_context(self):
        text = REPORT.read_text(encoding="utf-8")

        self.assertIn("/var/tmp/mikroclear-deploy/mikroclear.service.before-package-entrypoint", text)
        self.assertIn("/opt/mikroclear-venv/bin/python /usr/local/bin/mikroclear.py", text)
        self.assertIn("legacy rollback", text)
