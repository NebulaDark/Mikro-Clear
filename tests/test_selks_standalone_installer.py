from pathlib import Path
import importlib.util
import os
import shlex
import subprocess
import tempfile
from unittest import TestCase
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/install-selks.sh"
PERMISSIONS_HELPER = ROOT / "scripts/normalize_runtime_permissions.py"


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


def load_permissions_helper():
    spec = importlib.util.spec_from_file_location(
        "normalize_runtime_permissions",
        PERMISSIONS_HELPER,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load runtime permissions helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    def test_find_dependency_maps_to_findutils(self):
        result = run_bash("package_for_command find")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "findutils\n")

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

    def test_existing_runtime_permissions_are_normalized_for_service_user(self):
        self.assertTrue(PERMISSIONS_HELPER.is_file())
        helper = load_permissions_helper()
        with tempfile.TemporaryDirectory() as root:
            config_dir = Path(root) / "etc/mikroclear"
            cert_dir = config_dir / "certs"
            state_dir = Path(root) / "var/lib/mikroclear"
            nested_dir = state_dir / "nested"
            cert_dir.mkdir(parents=True)
            nested_dir.mkdir(parents=True)
            env_file = config_dir / "mikroclear.env"
            ca_file = cert_dir / "mikrotik-ca.crt"
            state_file = state_dir / "dynamic-whitelist.json"
            nested_file = nested_dir / "telegram-actions.json"
            for path in (env_file, ca_file, state_file, nested_file):
                path.write_text("fixture\n", encoding="utf-8")
                path.chmod(0o644)
            state_dir.chmod(0o755)
            nested_dir.chmod(0o755)

            helper.normalize_permissions(
                env_file=env_file,
                ca_file=ca_file,
                state_dir=state_dir,
                config_uid=os.getuid(),
                service_uid=os.getuid(),
                service_gid=os.getgid(),
            )

            self.assertEqual(env_file.stat().st_mode & 0o777, 0o640)
            self.assertEqual(ca_file.stat().st_mode & 0o777, 0o640)
            self.assertEqual(state_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(nested_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(state_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(nested_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(env_file.stat().st_uid, os.getuid())
            self.assertEqual(state_file.stat().st_uid, os.getuid())

    def test_existing_runtime_permission_migration_rejects_state_symlinks(self):
        self.assertTrue(PERMISSIONS_HELPER.is_file())
        helper = load_permissions_helper()
        with tempfile.TemporaryDirectory() as root:
            config_dir = Path(root) / "etc/mikroclear"
            state_dir = Path(root) / "var/lib/mikroclear"
            config_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            env_file = config_dir / "mikroclear.env"
            env_file.write_text("fixture\n", encoding="utf-8")
            (state_dir / "unexpected-link").symlink_to("/tmp")

            with self.assertRaisesRegex(OSError, "unexpected state entry"):
                helper.normalize_permissions(
                    env_file=env_file,
                    ca_file=config_dir / "missing.crt",
                    state_dir=state_dir,
                    config_uid=os.getuid(),
                    service_uid=os.getuid(),
                    service_gid=os.getgid(),
                )

    def test_runtime_permission_helper_propagates_mutation_failure(self):
        self.assertTrue(PERMISSIONS_HELPER.is_file())
        helper = load_permissions_helper()
        with tempfile.TemporaryDirectory() as root:
            config_dir = Path(root) / "etc/mikroclear"
            state_dir = Path(root) / "var/lib/mikroclear"
            config_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            env_file = config_dir / "mikroclear.env"
            env_file.write_text("fixture\n", encoding="utf-8")

            with patch.object(
                helper.os,
                "fchmod",
                side_effect=PermissionError("denied"),
            ):
                with self.assertRaises(PermissionError):
                    helper.normalize_permissions(
                        env_file=env_file,
                        ca_file=config_dir / "missing.crt",
                        state_dir=state_dir,
                        config_uid=os.getuid(),
                        service_uid=os.getuid(),
                        service_gid=os.getgid(),
                    )

    def test_runtime_permission_helper_rejects_swap_to_symlink(self):
        self.assertTrue(PERMISSIONS_HELPER.is_file())
        helper = load_permissions_helper()
        with tempfile.TemporaryDirectory() as root:
            config_dir = Path(root) / "etc/mikroclear"
            state_dir = Path(root) / "var/lib/mikroclear"
            config_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            env_file = config_dir / "mikroclear.env"
            env_file.write_text("fixture\n", encoding="utf-8")
            state_file = state_dir / "state.json"
            original_state = state_dir / "state.original"
            state_file.write_text("{}\n", encoding="utf-8")
            external = Path(root) / "external"
            external.write_text("external\n", encoding="utf-8")
            external.chmod(0o644)
            original_open = helper.os.open
            swapped = False

            def racing_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if (
                    path == "state.json"
                    and dir_fd is not None
                    and not swapped
                ):
                    swapped = True
                    state_file.replace(original_state)
                    state_file.symlink_to(external)
                if dir_fd is None:
                    return original_open(path, flags, mode)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with patch.object(helper.os, "open", side_effect=racing_open):
                with self.assertRaises(OSError):
                    helper.normalize_permissions(
                        env_file=env_file,
                        ca_file=config_dir / "missing.crt",
                        state_dir=state_dir,
                        config_uid=os.getuid(),
                        service_uid=os.getuid(),
                        service_gid=os.getgid(),
                    )

            self.assertTrue(swapped)
            self.assertEqual(external.stat().st_mode & 0o777, 0o644)

    def test_runtime_permission_helper_rejects_swap_to_fifo_without_blocking(self):
        self.assertTrue(PERMISSIONS_HELPER.is_file())
        helper = load_permissions_helper()
        with tempfile.TemporaryDirectory() as root:
            config_dir = Path(root) / "etc/mikroclear"
            state_dir = Path(root) / "var/lib/mikroclear"
            config_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            env_file = config_dir / "mikroclear.env"
            env_file.write_text("fixture\n", encoding="utf-8")
            state_file = state_dir / "state.json"
            original_state = state_dir / "state.original"
            state_file.write_text("{}\n", encoding="utf-8")
            original_open = helper.os.open
            swapped = False

            def racing_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal swapped
                if (
                    path == "state.json"
                    and dir_fd is not None
                    and not swapped
                ):
                    self.assertTrue(flags & os.O_NONBLOCK)
                    swapped = True
                    state_file.replace(original_state)
                    os.mkfifo(state_file)
                if dir_fd is None:
                    return original_open(path, flags, mode)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with patch.object(helper.os, "open", side_effect=racing_open):
                with self.assertRaises(OSError):
                    helper.normalize_permissions(
                        env_file=env_file,
                        ca_file=config_dir / "missing.crt",
                        state_dir=state_dir,
                        config_uid=os.getuid(),
                        service_uid=os.getuid(),
                        service_gid=os.getgid(),
                    )

            self.assertTrue(swapped)

    def test_runtime_permission_helper_rejects_cross_device_state_entry(self):
        self.assertTrue(PERMISSIONS_HELPER.is_file())
        helper = load_permissions_helper()
        with tempfile.TemporaryDirectory() as root:
            config_dir = Path(root) / "etc/mikroclear"
            state_dir = Path(root) / "var/lib/mikroclear"
            config_dir.mkdir(parents=True)
            state_dir.mkdir(parents=True)
            env_file = config_dir / "mikroclear.env"
            env_file.write_text("fixture\n", encoding="utf-8")
            state_file = state_dir / "state.json"
            state_file.write_text("{}\n", encoding="utf-8")
            state_file.chmod(0o644)
            original_stat = helper.os.stat

            def cross_device_stat(
                path,
                *,
                dir_fd=None,
                follow_symlinks=True,
            ):
                current = original_stat(
                    path,
                    dir_fd=dir_fd,
                    follow_symlinks=follow_symlinks,
                )
                if path == "state.json" and dir_fd is not None:
                    values = list(current)
                    values[2] = current.st_dev + 1
                    return os.stat_result(values)
                return current

            with patch.object(
                helper.os,
                "stat",
                side_effect=cross_device_stat,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "cross-device state entry",
                ):
                    helper.normalize_permissions(
                        env_file=env_file,
                        ca_file=config_dir / "missing.crt",
                        state_dir=state_dir,
                        config_uid=os.getuid(),
                        service_uid=os.getuid(),
                        service_gid=os.getgid(),
                    )

            self.assertEqual(state_file.stat().st_mode & 0o777, 0o644)

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

    def test_candidate_switch_and_restore_are_exact(self):
        with tempfile.TemporaryDirectory() as root:
            opt = Path(root) / "opt"
            current = opt / "mikroclear-venv"
            candidate = opt / ".mikroclear-venv.candidate"
            current.mkdir(parents=True)
            candidate.mkdir()
            (current / "version").write_text("old\n", encoding="utf-8")
            (candidate / "version").write_text("new\n", encoding="utf-8")

            result = run_bash(
                "init_paths; "
                'CANDIDATE_VENV="$(target_path /opt/.mikroclear-venv.candidate)"; '
                'ROLLBACK_VENV="$(target_path /opt/.mikroclear-venv.rollback)"; '
                "switch_candidate_venv; restore_previous_venv",
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (current / "version").read_text(encoding="utf-8"),
                "old\n",
            )

    def test_clean_candidate_switch_has_no_rollback_venv(self):
        with tempfile.TemporaryDirectory() as root:
            opt = Path(root) / "opt"
            candidate = opt / ".mikroclear-venv.candidate"
            candidate.mkdir(parents=True)
            (candidate / "version").write_text("new\n", encoding="utf-8")

            result = run_bash(
                "init_paths; "
                'CANDIDATE_VENV="$(target_path /opt/.mikroclear-venv.candidate)"; '
                'ROLLBACK_VENV="$(target_path /opt/.mikroclear-venv.rollback)"; '
                'switch_candidate_venv; printf "%s\\n" "$HAD_PREVIOUS_INSTALL"',
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "false\n")
            self.assertEqual(
                (opt / "mikroclear-venv/version").read_text(encoding="utf-8"),
                "new\n",
            )
            self.assertFalse((opt / ".mikroclear-venv.rollback").exists())

    def test_backup_preserves_unit_env_ca_and_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            fixtures = {
                "etc/systemd/system/mikroclear.service": b"unit\n",
                "etc/mikroclear/mikroclear.env": b"SECRET=value\n",
                "etc/mikroclear/certs/mikrotik-ca.crt": b"certificate\n",
                "var/lib/mikroclear/install-manifest": b"commit=old\n",
            }
            for relative, content in fixtures.items():
                source = Path(root) / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(content)

            result = run_bash(
                "init_paths; "
                'BACKUP_DIR="$(target_path /var/backups/mikroclear/test-backup)"; '
                "create_backup",
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            backup = Path(root) / "var/backups/mikroclear/test-backup"
            expected = {
                "mikroclear.service": b"unit\n",
                "mikroclear.env": b"SECRET=value\n",
                "mikrotik-ca.crt": b"certificate\n",
                "install-manifest": b"commit=old\n",
            }
            for name, content in expected.items():
                with self.subTest(name=name):
                    self.assertEqual((backup / name).read_bytes(), content)

    def test_successful_update_archives_exact_previous_venv(self):
        with tempfile.TemporaryDirectory() as root:
            opt = Path(root) / "opt"
            rollback = opt / ".mikroclear-venv.rollback"
            rollback.mkdir(parents=True)
            (rollback / "version").write_text("old\n", encoding="utf-8")
            backup = Path(root) / "var/backups/mikroclear/test-backup"
            backup.mkdir(parents=True)

            result = run_bash(
                "init_paths; "
                'ROLLBACK_VENV="$(target_path /opt/.mikroclear-venv.rollback)"; '
                'BACKUP_DIR="$(target_path /var/backups/mikroclear/test-backup)"; '
                "finalize_successful_update",
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (backup / "venv/version").read_text(encoding="utf-8"),
                "old\n",
            )
            self.assertFalse(rollback.exists())

    def test_second_installer_cannot_take_held_lock(self):
        with tempfile.TemporaryDirectory() as root:
            result = run_bash(
                "init_paths; "
                'LOCK_FILE="$(target_path /run/lock/mikroclear-install.lock)"; '
                'mkdir -p "$(dirname "$LOCK_FILE")"; '
                'exec 8>"$LOCK_FILE"; flock -n 8; acquire_install_lock',
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("another installer is running", result.stderr)

    def test_candidate_runtime_explicitly_rejects_mcp(self):
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("-m pip show mcp", source)
        self.assertIn("candidate runtime unexpectedly contains mcp", source)

    def test_candidate_preparation_stops_when_venv_creation_fails(self):
        with tempfile.TemporaryDirectory() as root:
            candidate = Path(root) / "candidate"
            result = run_bash(
                "prepare_candidate_paths(){ "
                f"CANDIDATE_VENV={shlex.quote(str(candidate))}; "
                "}; "
                "python3(){ return 1; }; "
                "if prepare_candidate_venv fixture.whl; then exit 0; "
                "else exit 1; fi"
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(f"{candidate}/bin/python", result.stderr)

    def test_candidate_switch_stops_when_candidate_is_missing(self):
        with tempfile.TemporaryDirectory() as root:
            current = Path(root) / "current"
            current.mkdir()
            result = run_bash(
                f"CANDIDATE_VENV={shlex.quote(str(Path(root) / 'missing'))}; "
                f"VENV_DIR={shlex.quote(str(current))}; "
                f"ROLLBACK_VENV={shlex.quote(str(Path(root) / 'rollback'))}; "
                'events=""; mv(){ events+=" mv"; return 0; }; '
                'if switch_candidate_venv; then rc=0; else rc=$?; fi; '
                'printf "%s|%s\\n" "$rc" "$events"'
            )

        self.assertEqual(result.stdout, "1|\n")

    def test_failed_update_runs_rollback_and_returns_nonzero(self):
        result = run_bash(
            'events=""; '
            'create_backup(){ events+=" backup"; }; '
            'prepare_candidate_venv(){ events+=" prepare"; }; '
            'stop_service(){ events+=" stop"; }; '
            'normalize_existing_runtime_permissions(){ events+=" permissions"; }; '
            'switch_candidate_venv(){ events+=" switch"; }; '
            'install_unit_candidate(){ events+=" unit"; }; '
            'reload_service_manager(){ events+=" reload"; }; '
            'accept_install(){ events+=" accept"; return 1; }; '
            'rollback_update(){ events+=" rollback"; return 0; }; '
            "HAD_PREVIOUS_INSTALL=true; WHEEL_PATH=fixture.whl; "
            'install_or_update || rc=$?; printf "%s|%s\\n" "${rc:-0}" "$events"'
        )

        self.assertEqual(
            result.stdout,
            "1| backup prepare stop permissions switch unit reload accept rollback\n",
        )

    def test_permission_migration_failure_restores_old_service_before_switch(self):
        result = run_bash(
            'events=""; '
            'create_backup(){ events+=" backup"; }; '
            'prepare_candidate_venv(){ events+=" prepare"; }; '
            'stop_service(){ events+=" stop"; }; '
            'normalize_existing_runtime_permissions(){ '
            'events+=" permissions"; return 1; }; '
            'restore_backup_files(){ events+=" restore"; }; '
            'start_service(){ events+=" start"; }; '
            'switch_candidate_venv(){ events+=" switch"; }; '
            "HAD_PREVIOUS_INSTALL=true; WHEEL_PATH=fixture.whl; "
            'install_or_update || rc=$?; printf "%s|%s\\n" "${rc:-0}" "$events"'
        )

        self.assertEqual(
            result.stdout,
            "1| backup prepare stop permissions restore start\n",
        )

    def test_clean_failure_stops_without_rollback(self):
        result = run_bash(
            'events=""; '
            'create_backup(){ events+=" backup"; }; '
            'prepare_candidate_venv(){ events+=" prepare"; }; '
            'stop_service(){ events+=" stop"; }; '
            'normalize_existing_runtime_permissions(){ events+=" permissions"; }; '
            'switch_candidate_venv(){ events+=" switch"; }; '
            'install_unit_candidate(){ events+=" unit"; }; '
            'reload_service_manager(){ events+=" reload"; }; '
            'accept_install(){ events+=" accept"; return 1; }; '
            'rollback_update(){ events+=" rollback"; return 0; }; '
            "HAD_PREVIOUS_INSTALL=false; WHEEL_PATH=fixture.whl; "
            'install_or_update || rc=$?; printf "%s|%s\\n" "${rc:-0}" "$events"'
        )

        self.assertEqual(
            result.stdout,
            "1| prepare permissions switch unit reload accept stop\n",
        )

    def test_rollback_restores_previous_files_and_venv(self):
        with tempfile.TemporaryDirectory() as root:
            active_venv = Path(root) / "opt/mikroclear-venv"
            rollback_venv = Path(root) / "opt/.mikroclear-venv.rollback"
            active_venv.mkdir(parents=True)
            rollback_venv.mkdir()
            (active_venv / "version").write_text("new\n", encoding="utf-8")
            (rollback_venv / "version").write_text("old\n", encoding="utf-8")

            active_files = {
                "etc/systemd/system/mikroclear.service": b"new unit\n",
                "etc/mikroclear/mikroclear.env": b"NEW=1\n",
                "etc/mikroclear/certs/mikrotik-ca.crt": b"new cert\n",
                "var/lib/mikroclear/install-manifest": b"commit=new\n",
            }
            for relative, content in active_files.items():
                path = Path(root) / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

            backup = Path(root) / "var/backups/mikroclear/test-backup"
            backup.mkdir(parents=True)
            backup_files = {
                "mikroclear.service": b"old unit\n",
                "mikroclear.env": b"OLD=1\n",
                "mikrotik-ca.crt": b"old cert\n",
                "install-manifest": b"commit=old\n",
            }
            for name, content in backup_files.items():
                (backup / name).write_bytes(content)

            result = run_bash(
                "init_paths; "
                'BACKUP_DIR="$(target_path /var/backups/mikroclear/test-backup)"; '
                'ROLLBACK_VENV="$(target_path /opt/.mikroclear-venv.rollback)"; '
                "stop_service(){ :; }; reload_service_manager(){ :; }; "
                "start_service(){ :; }; verify_rollback_health(){ return 0; }; "
                "rollback_update",
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (active_venv / "version").read_text(encoding="utf-8"),
                "old\n",
            )
            expected_active = {
                "etc/systemd/system/mikroclear.service": b"old unit\n",
                "etc/mikroclear/mikroclear.env": b"OLD=1\n",
                "etc/mikroclear/certs/mikrotik-ca.crt": b"old cert\n",
                "var/lib/mikroclear/install-manifest": b"commit=old\n",
            }
            for relative, content in expected_active.items():
                with self.subTest(relative=relative):
                    self.assertEqual((Path(root) / relative).read_bytes(), content)

    def test_env_reader_does_not_execute_file_contents(self):
        with tempfile.TemporaryDirectory() as root:
            env_file = Path(root) / "etc/mikroclear/mikroclear.env"
            marker = Path(root) / "executed"
            env_file.parent.mkdir(parents=True)
            env_file.write_text(
                "MIKROCLEAR_TELEGRAM_ENABLE=true\n"
                f"EVIL=$(touch {marker})\n",
                encoding="utf-8",
            )

            result = run_bash(
                "init_paths; read_env_value MIKROCLEAR_TELEGRAM_ENABLE",
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "true\n")
            self.assertFalse(marker.exists())

    def test_incomplete_existing_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            env_file = Path(root) / "etc/mikroclear/mikroclear.env"
            env_file.parent.mkdir(parents=True)
            env_file.write_text(
                'MIKROCLEAR_ROUTER_USERNAME="api"\n'
                'MIKROCLEAR_ROUTER_PASSWORD=""\n',
                encoding="utf-8",
            )

            result = run_bash(
                "init_paths; validate_existing_config",
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("existing configuration is incomplete", result.stderr)

    def test_template_mode_preserves_existing_running_install(self):
        result = run_bash(
            'events=""; existing_install(){ return 0; }; '
            'stop_service(){ events+=" stop"; }; '
            'write_template_config(){ events+=" write"; }; '
            'install_template_mode || rc=$?; '
            'printf "%s|%s\\n" "${rc:-0}" "$events"'
        )

        self.assertEqual(result.stdout, "1|\n")
        self.assertIn("existing installation", result.stderr)

    def test_acceptance_checks_required_markers_conditionally(self):
        source = SCRIPT.read_text(encoding="utf-8")

        for required in (
            "Connected to MikroTik",
            "Telegram polling worker started",
            "NRestarts",
            "TasksCurrent",
            "User",
            "Group",
            "WorkingDirectory",
            "Traceback",
            "Fatal Telegram polling worker error",
        ):
            self.assertIn(required, source)

    def test_rollback_health_requires_every_status_property(self):
        result = run_bash(
            "service_properties(){ printf '%s\\n' "
            "'ActiveState=inactive' 'SubState=dead' 'NRestarts=0'; }; "
            "if verify_rollback_health; then exit 0; else exit 1; fi"
        )

        self.assertNotEqual(result.returncode, 0)

    def test_interactive_failure_restores_backup_before_switch(self):
        result = run_bash(
            'events=""; existing_install(){ return 0; }; '
            'install_layout(){ events+=" layout"; }; '
            'prepare_install_artifact(){ events+=" artifact"; }; '
            'create_backup(){ events+=" backup"; }; '
            'configure_interactively(){ events+=" configure"; return 1; }; '
            'restore_backup_files(){ events+=" restore"; }; '
            'validate_existing_config(){ events+=" validate"; }; '
            'verify_eve_access(){ events+=" eve"; }; '
            'install_or_update(){ events+=" install"; }; '
            'install_interactive_mode || rc=$?; '
            'printf "%s|%s\\n" "${rc:-0}" "$events"'
        )

        self.assertEqual(
            result.stdout,
            "1| layout artifact backup configure restore\n",
        )

    def test_start_failure_stops_service_and_does_not_write_manifest(self):
        result = run_bash(
            'events=""; existing_install(){ return 0; }; '
            'validate_existing_config(){ events+=" validate"; }; '
            'verify_eve_access(){ events+=" eve"; }; '
            'reload_service_manager(){ events+=" reload"; }; '
            'accept_install(){ events+=" accept"; return 1; }; '
            'stop_service(){ events+=" stop"; }; '
            'write_manifest(){ events+=" manifest"; }; '
            'start_existing_install || rc=$?; '
            'printf "%s|%s\\n" "${rc:-0}" "$events"'
        )

        self.assertEqual(
            result.stdout,
            "1| validate eve reload accept stop\n",
        )

    def test_diagnostics_mask_telegram_bot_token(self):
        result = run_bash(
            "systemctl(){ printf '%s\\n' "
            "'request https://api.telegram.org/bot123456:SECRET/getUpdates'; }; "
            "journalctl(){ printf '%s\\n' "
            "'request https://api.telegram.org/bot123456:SECRET/getUpdates'; }; "
            "show_diagnostics"
        )
        combined = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("123456:SECRET", combined)
        self.assertIn("bot***MASKED***", combined)

    def test_configure_interactively_stops_after_collection_failure(self):
        result = run_bash(
            'events=""; '
            'collect_interactive_config(){ events+=" collect"; '
            "USE_SSL=false; ALLOW_SELF_SIGNED=false; return 1; }; "
            'render_config(){ events+=" render"; }; '
            'write_config_atomic(){ events+=" write"; }; '
            'if configure_interactively; then rc=0; else rc=$?; fi; '
            'printf "%s|%s\\n" "$rc" "$events"'
        )

        self.assertEqual(result.stdout, "1| collect\n")

    def test_unit_install_propagates_copy_failure_in_conditional_context(self):
        with tempfile.TemporaryDirectory() as root:
            unit_dir = Path(root) / "etc/systemd/system"
            unit_dir.mkdir(parents=True)
            result = run_bash(
                "init_paths; install(){ return 1; }; mv(){ return 0; }; "
                "if install_unit_candidate; then exit 0; else exit 1; fi",
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

        self.assertNotEqual(result.returncode, 0)

    def test_acceptance_stops_when_service_start_fails(self):
        result = run_bash(
            "start_service(){ return 1; }; "
            "acceptance_probe(){ return 0; }; "
            "if accept_install 1; then exit 0; else exit 1; fi"
        )

        self.assertNotEqual(result.returncode, 0)

    def test_rollback_stops_when_venv_restore_fails(self):
        result = run_bash(
            'events=""; stop_service(){ events+=" stop"; }; '
            'restore_previous_venv(){ events+=" venv"; return 1; }; '
            'restore_backup_files(){ events+=" files"; }; '
            'reload_service_manager(){ events+=" reload"; }; '
            'start_service(){ events+=" start"; }; '
            'verify_rollback_health(){ events+=" health"; }; '
            'if rollback_update; then rc=0; else rc=$?; fi; '
            'printf "%s|%s\\n" "$rc" "$events"'
        )

        self.assertEqual(result.stdout, "2| stop venv\n")

    def test_manifest_fails_when_runtime_python_is_missing(self):
        with tempfile.TemporaryDirectory() as root:
            state_dir = Path(root) / "var/lib/mikroclear"
            state_dir.mkdir(parents=True)
            result = run_bash(
                "init_paths; repo_commit(){ printf 'abc123\\n'; }; "
                "if write_manifest active; then exit 0; else exit 1; fi",
                env={
                    "MIKROCLEAR_INSTALLER_TEST_MODE": "1",
                    "MIKROCLEAR_INSTALLER_TEST_ROOT": root,
                },
            )

        self.assertNotEqual(result.returncode, 0)
