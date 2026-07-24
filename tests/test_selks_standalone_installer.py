from pathlib import Path
import os
import subprocess
import tempfile
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/install-selks.sh"


def run_bash(body: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"\n{body}'],
        cwd=ROOT,
        env=process_env,
        text=True,
        capture_output=True,
        check=False,
    )


class SelksStandaloneInstallerTests(TestCase):
    def test_source_does_not_execute_main(self):
        result = run_bash('printf "sourced\\n"')

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "sourced\n")

    def test_parse_supported_modes(self):
        interactive = run_bash(
            'parse_args --interactive; printf "%s:%s\\n" "$INSTALL_MODE" "$START_ONLY"'
        )
        template = run_bash(
            'parse_args --config-template; printf "%s:%s\\n" "$INSTALL_MODE" "$START_ONLY"'
        )
        start = run_bash(
            'parse_args --start; printf "%s:%s\\n" "$INSTALL_MODE" "$START_ONLY"'
        )

        self.assertEqual(interactive.stdout, "interactive:false\n")
        self.assertEqual(template.stdout, "template:false\n")
        self.assertEqual(start.stdout, "existing:true\n")

    def test_unknown_argument_fails(self):
        result = run_bash("parse_args --unknown")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown argument: --unknown", result.stderr)

    def test_modes_are_mutually_exclusive(self):
        result = run_bash("parse_args --interactive --config-template")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("choose exactly one install mode", result.stderr)

    def test_menu_selects_one_of_two_install_modes(self):
        interactive = run_bash("choose_install_mode", env={"REPLY": "1"})
        template = run_bash("choose_install_mode", env={"REPLY": "2"})

        self.assertEqual(interactive.returncode, 0, interactive.stderr)
        self.assertEqual(interactive.stdout, "interactive\n")
        self.assertEqual(template.returncode, 0, template.stderr)
        self.assertEqual(template.stdout, "template\n")

    def test_test_root_requires_explicit_test_mode_and_tmp_path(self):
        with tempfile.TemporaryDirectory() as root:
            accepted = run_bash(
                'init_paths; target_path "/etc/mikroclear"',
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )
        rejected = run_bash(
            "init_paths",
            env={"MIKROCLEAR_INSTALLER_TEST_ROOT": "/tmp/not-authorized"},
        )

        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertTrue(accepted.stdout.endswith("/etc/mikroclear"))
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("test root requires test mode", rejected.stderr)
