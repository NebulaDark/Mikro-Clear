from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_UNIT = ROOT / "deploy" / "systemd" / "mikroclear.service.candidate"
PRODUCTION_UNIT = ROOT / "systemd" / "mikroclear.service"
PLAN = ROOT / "docs" / "superpowers" / "plans" / "2026-07-05-systemd-package-entrypoint-plan.md"


def section_lines(path: Path, section_name: str) -> list[str]:
    current = None
    lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line.strip("[]")
            continue
        if current == section_name and line and not line.startswith("#"):
            lines.append(line)
    return lines


class SystemdCandidateUnitTests(TestCase):
    def test_current_production_unit_keeps_legacy_execstart(self):
        service_lines = section_lines(PRODUCTION_UNIT, "Service")

        self.assertIn("ExecStart=/opt/mikrocata-venv/bin/python /usr/local/bin/mikroclear.py", service_lines)

    def test_candidate_execstart_uses_package_entrypoint(self):
        service_lines = section_lines(CANDIDATE_UNIT, "Service")

        self.assertIn("ExecStart=/opt/mikrocata-venv/bin/python -m mikroclear", service_lines)
        self.assertNotIn("ExecStart=/opt/mikrocata-venv/bin/python /usr/local/bin/mikroclear.py", service_lines)

    def test_candidate_keeps_legacy_env_fallback_order(self):
        service_lines = section_lines(CANDIDATE_UNIT, "Service")
        legacy = "EnvironmentFile=-/etc/mikrocata/mikrocataTZSP0.env"
        current = "EnvironmentFile=-/etc/mikroclear/mikroclear.env"

        self.assertIn(legacy, service_lines)
        self.assertIn(current, service_lines)
        self.assertLess(service_lines.index(legacy), service_lines.index(current))

    def test_candidate_preserves_legacy_state_paths_during_transition(self):
        service_lines = section_lines(CANDIDATE_UNIT, "Service")

        self.assertIn("ReadWritePaths=/var/lib/mikroclear /var/lib/mikrocata", service_lines)
        self.assertIn(
            "ReadOnlyPaths=/opt/SELKS/docker/containers-data/suricata/logs /etc/mikroclear /etc/mikrocata",
            service_lines,
        )

    def test_plan_documents_rollback_and_safety_notes(self):
        text = PLAN.read_text(encoding="utf-8")

        self.assertIn("Rollback", text)
        self.assertIn("/usr/local/bin/mikroclear.py", text)
        self.assertIn("systemd-analyze verify", text)
        self.assertIn("Do not run systemctl in this stage", text)
