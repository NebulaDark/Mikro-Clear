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

    def test_service_uses_package_entrypoint(self):
        service_lines = section_lines("Service")

        self.assertIn("ExecStart=/opt/mikroclear-venv/bin/python -m mikroclear", service_lines)
        self.assertNotIn("ExecStart=/opt/mikroclear-venv/bin/python /usr/local/bin/mikroclear.py", service_lines)

    def test_service_has_incremental_sandbox_hardening(self):
        service_lines = section_lines("Service")

        for directive in (
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "ProtectHome=true",
            "ProtectSystem=strict",
            "RestrictSUIDSGID=true",
            "LockPersonality=true",
            "MemoryDenyWriteExecute=true",
            "ReadWritePaths=/var/lib/mikroclear /var/lib/mikrocata",
            "ReadOnlyPaths=/opt/SELKS/docker/containers-data/suricata/logs /etc/mikroclear /etc/mikrocata",
        ):
            self.assertIn(directive, service_lines)

        self.assertIn("User=root", service_lines)
        self.assertIn("Group=root", service_lines)
