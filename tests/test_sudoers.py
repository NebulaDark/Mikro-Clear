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
        self.assertIn("/usr/bin/systemctl restart mikroclear.service", text)
        self.assertIn("/usr/bin/systemctl stop mikrocataTZSP0.service", text)
        self.assertIn("/usr/bin/systemctl disable mikrocataTZSP0.service", text)
        self.assertIn("/usr/bin/install -o root -g root -m 755 /tmp/mikroclear.py.codex-candidate /usr/local/bin/mikroclear.py", text)
        self.assertIn("/usr/bin/install -o root -g root -m 644 /tmp/mikroclear-codex.service /etc/systemd/system/mikroclear.service", text)
        self.assertNotIn("/bin/sh", text)
        self.assertNotIn("/bin/bash", text)
        self.assertNotIn(" ALL", text.replace("mcp-selks ALL", "mcp-selks"))
