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

    def test_template_layout_has_secure_modes(self):
        with tempfile.TemporaryDirectory() as root:
            result = run_bash(
                "init_paths; install_layout; write_template_config",
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )
            env_file = Path(root) / "etc/mikroclear/mikroclear.env"
            config_dir = env_file.parent
            cert_dir = config_dir / "certs"
            state_dir = Path(root) / "var/lib/mikroclear"
            backup_dir = Path(root) / "var/backups/mikroclear"

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(config_dir.stat().st_mode & 0o777, 0o750)
            self.assertEqual(cert_dir.stat().st_mode & 0o777, 0o750)
            self.assertEqual(env_file.stat().st_mode & 0o777, 0o640)
            self.assertEqual(state_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(backup_dir.stat().st_mode & 0o777, 0o700)
            self.assertIn(
                "MIKROCLEAR_ROUTER_PASSWORD=",
                env_file.read_text(encoding="utf-8"),
            )

    def test_existing_template_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            env_file = Path(root) / "etc/mikroclear/mikroclear.env"
            env_file.parent.mkdir(parents=True)
            env_file.write_text("KEEP=1\n", encoding="utf-8")

            result = run_bash(
                "init_paths; write_template_config",
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("configuration already exists", result.stderr)
            self.assertEqual(env_file.read_text(encoding="utf-8"), "KEEP=1\n")

    def test_service_identity_is_not_mutated_in_test_mode(self):
        with tempfile.TemporaryDirectory() as root:
            result = run_bash(
                'groupadd(){ printf "MUTATION groupadd\\n"; }; '
                'useradd(){ printf "MUTATION useradd\\n"; }; '
                "init_paths; ensure_service_identity",
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("MUTATION", result.stdout)

    def test_eve_failure_does_not_run_permission_mutations(self):
        result = run_bash(
            'chmod(){ printf "MUTATION chmod\\n"; }; '
            'chown(){ printf "MUTATION chown\\n"; }; '
            'setfacl(){ printf "MUTATION setfacl\\n"; }; '
            "run_as_service_user(){ return 1; }; "
            "namei(){ :; }; stat(){ printf 'suricata\\n'; }; "
            "verify_eve_access"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("eve.json is not readable by mikroclear", result.stderr)
        self.assertNotIn("MUTATION", result.stdout)
        self.assertTrue(
            "usermod -a -G" in result.stderr or "setfacl -m" in result.stderr
        )

    def test_eve_success_uses_service_user_check(self):
        result = run_bash(
            'run_as_service_user(){ printf "%s\\n" "$*"; return 0; }; '
            "verify_eve_access"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("test -r", result.stdout)
        self.assertIn("eve.json", result.stdout)

    def test_unexpected_symlink_target_is_rejected_before_layout_changes(self):
        with tempfile.TemporaryDirectory() as root:
            etc = Path(root) / "etc"
            etc.mkdir()
            (etc / "mikroclear").symlink_to("/tmp")

            result = run_bash(
                "init_paths; validate_target_paths",
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected symlink", result.stderr)

    def test_rendered_config_uses_safe_defaults(self):
        result = run_bash(
            "ROUTER_USERNAME=api; ROUTER_PASSWORD=secret; "
            "ROUTER_IP=192.0.2.1; USE_SSL=true; ROUTER_PORT=8729; "
            "TLS_SERVER_NAME=router.example; ALLOW_SELF_SIGNED=false; "
            "TELEGRAM_ENABLE=false; TELEGRAM_TOKEN=; TELEGRAM_CHATID=; "
            "render_config"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "MIKROCLEAR_CA_FILE=/etc/mikroclear/certs/mikrotik-ca.crt",
            result.stdout,
        )
        self.assertIn("MIKROCLEAR_MANGLE_CONTROL_ENABLE=false", result.stdout)
        self.assertIn("MIKROCLEAR_BOT_DRY_RUN=true", result.stdout)

    def test_env_renderer_quotes_special_characters_and_rejects_newlines(self):
        quoted = run_bash("env_line SECRET 'space # quote\" backslash\\'")
        rejected = run_bash("env_line SECRET $'first\\nsecond'")

        self.assertEqual(quoted.returncode, 0, quoted.stderr)
        self.assertEqual(
            quoted.stdout,
            r'SECRET="space # quote\" backslash\\"' + "\n",
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(
            "newline is not allowed in environment value",
            rejected.stderr,
        )

    def test_summary_masks_all_secrets(self):
        result = run_bash(
            "ROUTER_USERNAME=api; ROUTER_PASSWORD=router-secret; "
            "ROUTER_IP=192.0.2.1; ROUTER_PORT=8729; USE_SSL=true; "
            "TELEGRAM_ENABLE=true; TELEGRAM_TOKEN=telegram-secret; "
            "TELEGRAM_CHATID=42; print_masked_summary"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("router-secret", result.stdout)
        self.assertNotIn("telegram-secret", result.stdout)
        self.assertGreaterEqual(result.stdout.count("***"), 2)

    def test_atomic_writer_preserves_existing_file_on_failure(self):
        with tempfile.TemporaryDirectory() as root:
            env_file = Path(root) / "etc/mikroclear/mikroclear.env"
            env_file.parent.mkdir(parents=True)
            env_file.write_text("OLD=1\n", encoding="utf-8")
            result = run_bash(
                "init_paths; validate_config_text(){ return 1; }; "
                'write_config_atomic "NEW=1"',
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("configuration validation failed", result.stderr)
            self.assertEqual(env_file.read_text(encoding="utf-8"), "OLD=1\n")

    def test_valid_ca_is_copied_to_canonical_secure_path(self):
        with tempfile.TemporaryDirectory() as root:
            source_ca = Path(root) / "source-ca.crt"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-days",
                    "1",
                    "-subj",
                    "/CN=mikroclear-installer-test",
                    "-keyout",
                    str(Path(root) / "source-ca.key"),
                    "-out",
                    str(source_ca),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            result = run_bash(
                f'init_paths; install_layout; install_ca "{source_ca}"',
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )
            installed = (
                Path(root)
                / "etc/mikroclear/certs/mikrotik-ca.crt"
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(installed.read_bytes(), source_ca.read_bytes())
            self.assertEqual(installed.stat().st_mode & 0o777, 0o640)

    def test_invalid_ca_does_not_replace_existing_ca(self):
        with tempfile.TemporaryDirectory() as root:
            cert_dir = Path(root) / "etc/mikroclear/certs"
            cert_dir.mkdir(parents=True)
            installed = cert_dir / "mikrotik-ca.crt"
            installed.write_text("OLD CERT\n", encoding="utf-8")
            invalid = Path(root) / "invalid.crt"
            invalid.write_text("not a certificate\n", encoding="utf-8")

            result = run_bash(
                f'init_paths; install_ca "{invalid}"',
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid CA certificate", result.stderr)
            self.assertEqual(
                installed.read_text(encoding="utf-8"),
                "OLD CERT\n",
            )

    def test_interactive_collector_reads_secrets_without_echo(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("read -r -s ROUTER_PASSWORD", source)
        self.assertIn("read -r -s TELEGRAM_TOKEN", source)
