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

    def test_python_floor_is_311(self):
        old = run_bash('python_version_ok "3.10"')
        current = run_bash('python_version_ok "3.11"')
        newer = run_bash('python_version_ok "3.13"')

        self.assertNotEqual(old.returncode, 0)
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertEqual(newer.returncode, 0, newer.stderr)

    def test_non_root_preflight_is_rejected(self):
        result = run_bash(
            "effective_uid(){ printf '1000\\n'; }; check_root"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("run installer as root", result.stderr)

    def test_snapshot_uses_committed_head_only(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            snapshot = Path(temp) / "snapshot"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", repo], check=True)
            (repo / "tracked.txt").write_text("committed\n", encoding="utf-8")
            subprocess.run(["git", "-C", repo, "add", "tracked.txt"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    repo,
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.invalid",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                check=True,
            )
            (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
            (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")

            result = run_bash(
                f'REPO_ROOT="{repo}"; create_source_snapshot "{snapshot}"'
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (snapshot / "tracked.txt").read_text(encoding="utf-8"),
                "committed\n",
            )
            self.assertFalse((snapshot / "untracked.txt").exists())

    def test_installer_source_has_no_git_network_mutation(self):
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("git pull", text)
        self.assertNotIn("git fetch", text)
        self.assertNotIn("git checkout", text)

    def test_dependency_install_uses_only_apt_after_confirmation(self):
        declined = run_bash(
            'apt-get(){ printf "APT_CALLED\\n"; }; '
            'printf "no\\n" | offer_apt_install git'
        )
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("APT_CALLED", declined.stdout)
        self.assertNotIn("dnf ", source)
        self.assertNotIn("yum ", source)
        self.assertNotIn("apk ", source)

    def test_missing_apt_is_reported_without_fallback_package_manager(self):
        result = run_bash(
            'has_command(){ return 1; }; offer_apt_install git'
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("apt-get is unavailable", result.stderr)

    def test_disk_space_check_fails_below_required_kib(self):
        result = run_bash(
            'available_kib(){ printf "100\\n"; }; '
            'check_available_space /opt 101'
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("insufficient free space", result.stderr)

    def test_production_build_does_not_install_requirements_file(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("pip install -r", source)
        self.assertNotIn("pip install --requirement", source)
