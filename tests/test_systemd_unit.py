from pathlib import Path
from unittest import TestCase


UNIT_PATH = Path(__file__).resolve().parents[1] / "systemd" / "mikroclear.service"


def section_lines(section_name: str) -> list[str]:
    current = None
    lines: list[str] = []
    for raw_line in UNIT_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line.strip("[]")
            continue
        if current == section_name and line and not line.startswith("#"):
            lines.append(line)
    return lines


class SystemdUnitTests(TestCase):
    def test_start_limit_settings_are_in_unit_section(self):
        unit_lines = section_lines("Unit")
        service_lines = section_lines("Service")

        self.assertIn("StartLimitIntervalSec=300", unit_lines)
        self.assertIn("StartLimitBurst=5", unit_lines)
        self.assertNotIn("StartLimitIntervalSec=300", service_lines)
        self.assertNotIn("StartLimitBurst=5", service_lines)

    def test_mikroclear_env_overrides_legacy_env_temporarily(self):
        service_lines = section_lines("Service")
        legacy = "EnvironmentFile=-/etc/mikrocata/mikrocataTZSP0.env"
        current = "EnvironmentFile=-/etc/mikroclear/mikroclear.env"

        self.assertIn(legacy, service_lines)
        self.assertIn(current, service_lines)
        self.assertLess(service_lines.index(legacy), service_lines.index(current))
