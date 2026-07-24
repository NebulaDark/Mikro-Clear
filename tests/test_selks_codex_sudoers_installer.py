from pathlib import Path
from unittest import TestCase


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "install-selks-codex-sudoers.sh"
)


class SelksCodexSudoersInstallerTests(TestCase):
    def test_installer_exists_and_targets_expected_paths(self):
        text = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn("deploy/sudoers.d/mikroclear-mcp-selks", text)
        self.assertIn("/etc/sudoers.d/mikroclear-mcp-selks", text)
        self.assertIn("/usr/local/sbin/mikroclear-mask-env", text)
        self.assertIn("/usr/local/sbin/mikroclear-service-env", text)
        self.assertIn("/usr/local/sbin/mikroclear-telegram-getupdates-probe", text)
        self.assertIn("visudo -cf", text)
        self.assertIn('EXPECTED_USER="${1:-mcp-selks}"', text)

    def test_exit_cleanup_does_not_reference_main_local_after_return(self):
        text = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertNotIn("local tmp_sudoers", text)
        self.assertIn('tmp_sudoers=""', text)
        self.assertIn('if [[ -n "${tmp_sudoers:-}" ]]', text)
        self.assertIn("trap cleanup EXIT", text)
