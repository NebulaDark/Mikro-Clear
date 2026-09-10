from pathlib import Path
from unittest import TestCase


SUDOERS_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "sudoers.d"
    / "mikroclear-mcp-selks"
)


class SudoersPolicyTests(TestCase):
    def test_policy_is_limited_to_mikroclear_paths(self):
        text = SUDOERS_PATH.read_text(encoding="utf-8")

        self.assertIn("mcp-selks ALL=(root) NOPASSWD:", text)
        self.assertIn("/usr/bin/systemctl enable mikroclear.service", text)
        self.assertIn("/usr/bin/systemctl start mikroclear.service", text)
        self.assertIn("/usr/bin/systemctl stop mikroclear.service", text)
        self.assertIn("/usr/bin/systemctl restart mikroclear.service", text)
        self.assertIn("/usr/bin/systemctl status mikroclear.service --no-pager --lines=30", text)
        self.assertIn(
            "/opt/mikroclear-venv/bin/python -m pip install --no-deps --force-reinstall /var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl",
            text,
        )
        self.assertNotIn("mikrocataTZSP0.service", text)
        self.assertIn(
            "/usr/bin/install -o root -g root -m 755 /var/tmp/mikroclear-deploy/mikroclear.py.codex-candidate /usr/local/bin/mikroclear.py",
            text,
        )
        self.assertIn(
            "/usr/bin/install -o root -g root -m 644 /var/tmp/mikroclear-deploy/mikroclear-codex.service /etc/systemd/system/mikroclear.service",
            text,
        )
        self.assertNotIn("/bin/sh", text)
        self.assertNotIn("/bin/bash", text)
        self.assertNotIn(" ALL", text.replace("mcp-selks ALL", "mcp-selks"))

    def test_policy_has_no_dangerous_argument_wildcards(self):
        text = SUDOERS_PATH.read_text(encoding="utf-8")

        self.assertNotIn("/tmp/mikroclear.py.codex-candidate", text)
        self.assertNotIn("/tmp/mikroclear-codex.service", text)
        self.assertNotIn("/tmp/mikrocataTZSP0.py.codex-candidate", text)
        self.assertNotIn("/tmp/mikrocataTZSP0-codex.service", text)
        self.assertNotIn("/usr/bin/sed -E s/*", text)
        self.assertNotIn("/usr/bin/tail -n *", text)
        self.assertNotIn("/usr/bin/journalctl -u mikroclear.service -n *", text)
        self.assertNotIn("/usr/bin/journalctl -u mikrocataTZSP0.service -n *", text)
        self.assertIn("/usr/local/sbin/mikroclear-mask-env /etc/mikroclear/mikroclear.env", text)
        self.assertIn("/usr/local/sbin/mikroclear-service-env", text)
        self.assertIn("/usr/local/sbin/mikroclear-telegram-getupdates-probe", text)
        self.assertIn(
            "/usr/local/sbin/mikroclear-telegram-getupdates-probe --reset-allowed-updates",
            text,
        )
        self.assertIn("/usr/bin/journalctl -u mikroclear.service -n 100 --no-pager", text)
        self.assertIn("/usr/bin/journalctl -u mikroclear.service -n 300 --no-pager", text)
        self.assertIn("/usr/bin/journalctl -u mikroclear.service -n 500 --no-pager", text)
        self.assertIn(
            "/usr/bin/tail -n 100 /opt/SELKS/docker/containers-data/suricata/logs/eve.json",
            text,
        )
