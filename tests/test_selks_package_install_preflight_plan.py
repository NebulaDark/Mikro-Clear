from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "superpowers" / "plans" / "2026-07-05-selks-package-install-preflight-plan.md"
CHECKLIST = ROOT / "docs" / "superpowers" / "plans" / "2026-07-05-selks-package-install-checklist.md"
WHEEL_PLAN = ROOT / "docs" / "superpowers" / "plans" / "2026-07-05-wheel-artifact-validation.md"


class SelksPackageInstallPreflightPlanTests(TestCase):
    def test_plan_is_non_deploy_and_read_only(self):
        text = PLAN.read_text(encoding="utf-8")

        self.assertIn("No push, no deploy, no SELKS file changes", text)
        self.assertIn("read-only SELKS checks only", text)
        self.assertIn("Do not install the wheel", text)
        self.assertIn("Do not run `systemctl` mutation commands", text)
        self.assertIn("No RouterOS connection", text)

    def test_plan_checks_current_service_without_mutation(self):
        text = PLAN.read_text(encoding="utf-8")

        self.assertIn("systemctl cat mikroclear.service", text)
        self.assertIn("systemctl show mikroclear.service --property=ExecStart,EnvironmentFiles,FragmentPath,DropInPaths", text)
        self.assertIn("ExecStart=/opt/mikrocata-venv/bin/python /usr/local/bin/mikroclear.py", text)
        self.assertIn("FragmentPath=/etc/systemd/system/mikroclear.service", text)

    def test_plan_checks_python_pip_and_import_state(self):
        text = PLAN.read_text(encoding="utf-8")

        self.assertIn("/opt/mikrocata-venv/bin/python --version", text)
        self.assertIn("/opt/mikrocata-venv/bin/python -m pip --version", text)
        self.assertIn("import mikroclear; print(mikroclear.__file__)", text)
        self.assertIn("ModuleNotFoundError is acceptable before install", text)

    def test_plan_requires_validated_wheel_before_any_install_approval(self):
        text = PLAN.read_text(encoding="utf-8")

        self.assertIn("scripts/validate_wheel_artifact.py", text)
        self.assertIn("wheel ok:", text)
        self.assertIn("SELKS package install checklist", text)
        self.assertIn("requires separate explicit deploy approval", text)

    def test_plan_documents_blockers_and_next_gate(self):
        text = PLAN.read_text(encoding="utf-8")

        self.assertIn("Blockers", text)
        self.assertIn("pip is unavailable in `/opt/mikrocata-venv`", text)
        self.assertIn("current ExecStart is not the legacy script", text)
        self.assertIn("Next Gate", text)
        self.assertIn("approve SELKS wheel upload/install", text)

    def test_related_documents_exist(self):
        self.assertTrue(CHECKLIST.exists())
        self.assertTrue(WHEEL_PLAN.exists())
