from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "superpowers" / "plans" / "2026-07-05-package-importability-plan.md"
PREFLIGHT = ROOT / "docs" / "superpowers" / "preflight" / "2026-07-05-selks-readonly-preflight.md"
PYPROJECT = ROOT / "pyproject.toml"


class PackageImportabilityPlanTests(TestCase):
    def test_plan_selects_wheel_install_into_existing_selks_venv(self):
        text = PLAN.read_text(encoding="utf-8")

        self.assertIn("Selected strategy: wheel install into `/opt/mikrocata-venv`", text)
        self.assertIn("/opt/mikrocata-venv/bin/python -m pip install", text)
        self.assertIn("/opt/mikrocata-venv/bin/python -m mikroclear", text)
        self.assertIn("editable install as the first production switch", text)
        self.assertIn("`PYTHONPATH` in systemd", text)

    def test_plan_keeps_non_deploy_guardrails(self):
        text = PLAN.read_text(encoding="utf-8")

        self.assertIn("No push, no deploy, no SELKS file changes", text)
        self.assertIn("Do not run `systemctl`", text)
        self.assertIn("Do not start the real runtime loop", text)
        self.assertIn("No RouterOS connection", text)

    def test_plan_documents_package_artifact_checks(self):
        text = PLAN.read_text(encoding="utf-8")

        self.assertIn("python -m pip wheel --no-deps .", text)
        self.assertIn("python -m zipfile -l", text)
        self.assertIn("mikroclear/__main__.py", text)
        self.assertIn("mikroclear/cli.py", text)

    def test_plan_documents_read_only_importability_preflight(self):
        text = PLAN.read_text(encoding="utf-8")

        self.assertIn("read-only importability check", text)
        self.assertIn("import mikroclear; print(mikroclear.__file__)", text)
        self.assertIn("This command must not call `app.main()`", text)

    def test_plan_documents_rollback_constraints(self):
        text = PLAN.read_text(encoding="utf-8")

        self.assertIn("Rollback", text)
        self.assertIn("/usr/local/bin/mikroclear.py", text)
        self.assertIn("/etc/systemd/system/mikroclear.service", text)
        self.assertIn("pip uninstall mikro-clear", text)

    def test_existing_preflight_points_to_this_next_step(self):
        text = PREFLIGHT.read_text(encoding="utf-8")

        self.assertIn("Prepare a separate non-deploy package install/importability plan", text)

    def test_pyproject_has_build_backend_and_console_script(self):
        text = PYPROJECT.read_text(encoding="utf-8")

        self.assertIn('build-backend = "setuptools.build_meta"', text)
        self.assertIn('mikroclear = "mikroclear.cli:main"', text)
