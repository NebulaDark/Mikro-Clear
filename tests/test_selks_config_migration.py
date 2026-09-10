import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "migrate-selks-config-f6ac4d2.py"


def load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "mikroclear_selks_config_migration",
        SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load migration script: {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SelksConfigMigrationTests(unittest.TestCase):
    def make_root(self, temporary: str) -> Path:
        root = Path(temporary)
        env_file = root / "etc/mikroclear/mikroclear.env"
        legacy_cert = root / "etc/mikrocata/certs/mikrotik-ca.crt"
        env_file.parent.mkdir(parents=True)
        legacy_cert.parent.mkdir(parents=True)
        env_file.write_text(
            "\n".join(
                (
                    'MIKROCLEAR_ROUTER_USERNAME="router-user"',
                    'MIKROCLEAR_ROUTER_PASSWORD="router-secret"',
                    'MIKROCLEAR_ROUTER_IP="192.0.2.1"',
                    "MIKROCLEAR_ROUTER_PORT=8729",
                    "MIKROCLEAR_USE_SSL=true",
                    "MIKROCLEAR_ALLOW_SELF_SIGNED_CERTS=false",
                    'MIKROCLEAR_CA_FILE="/etc/mikrocata/certs/mikrotik-ca.crt"',
                    'MIKROCLEAR_EVE_FILE="/legacy/eve.json"',
                    "MIKROCLEAR_STATE_DIR=/var/lib/mikroclear",
                    "MIKROCLEAR_TELEGRAM_ENABLE=true",
                    'MIKROCLEAR_TELEGRAM_TOKEN="telegram-secret"',
                    'MIKROCLEAR_TELEGRAM_CHATID="123456"',
                    "MIKROCLEAR_MANGLE_CONTROL_ENABLE=true",
                    "",
                )
            ),
            encoding="utf-8",
        )
        os.chmod(env_file, 0o600)
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-subj",
                "/CN=mikroclear-migration-test",
                "-days",
                "1",
                "-keyout",
                str(root / "test.key"),
                "-out",
                str(legacy_cert),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return root

    def run_script(self, root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "MIKROCLEAR_MIGRATION_TEST_MODE": "1",
                "MIKROCLEAR_MIGRATION_TEST_ROOT": str(root),
            }
        )
        return subprocess.run(
            ["python3", str(SCRIPT), *arguments],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_parser_uses_last_assignment_like_systemd_environment_file(self):
        migration = load_migration_module()

        values = migration.parse_values(
            "MIKROCLEAR_TELEGRAM_ENABLE=true\n"
            "MIKROCLEAR_TELEGRAM_ENABLE=false\n"
        )

        self.assertEqual(values["MIKROCLEAR_TELEGRAM_ENABLE"], "false")

    def test_regular_file_open_closes_descriptor_when_fstat_fails(self):
        migration = load_migration_module()
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            path = Path(temporary) / "fixture"
            path.write_text("fixture\n", encoding="utf-8")
            original_close = migration.os.close
            closed: list[int] = []

            def record_close(descriptor):
                closed.append(descriptor)
                return original_close(descriptor)

            with (
                patch.object(
                    migration.os,
                    "fstat",
                    side_effect=OSError("injected fstat failure"),
                ),
                patch.object(
                    migration.os,
                    "close",
                    side_effect=record_close,
                ),
            ):
                with self.assertRaises(OSError):
                    migration.open_regular_file(path, "fixture")

            self.assertEqual(len(closed), 1)

    def test_apply_migrates_config_and_certificate_without_printing_secrets(self):
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)

            result = self.run_script(root, "--apply")

            self.assertEqual(result.returncode, 0, result.stderr)
            env_file = root / "etc/mikroclear/mikroclear.env"
            content = env_file.read_text(encoding="utf-8")
            expected = {
                "MIKROCLEAR_EVE_JSON": (
                    "/opt/SELKS/docker/containers-data/suricata/logs/eve.json"
                ),
                "MIKROCLEAR_CA_FILE": "/etc/mikroclear/certs/mikrotik-ca.crt",
                "MIKROCLEAR_BOT_ENABLE": "true",
                "MIKROCLEAR_BOT_DRY_RUN": "true",
                "MIKROCLEAR_BOT_MODULES": (
                    "status,asset_resolver,mangle_control,parental_control,"
                    "whitelist_control"
                ),
                "MIKROCLEAR_BOT_ADMIN_CHAT_IDS": "123456",
                "MIKROCLEAR_BOT_ALLOWED_CHAT_IDS": "123456",
                "MIKROCLEAR_TELEGRAM_UNBLOCK_ENABLE": "true",
                "MIKROCLEAR_TELEGRAM_WHITELIST_CONTROL_ENABLE": "true",
            }
            for key, value in expected.items():
                self.assertEqual(content.count(f"{key}="), 1)
                self.assertIn(f"{key}={value}\n", content)
            self.assertIn('MIKROCLEAR_ROUTER_PASSWORD="router-secret"', content)
            self.assertIn('MIKROCLEAR_TELEGRAM_TOKEN="telegram-secret"', content)
            self.assertNotIn("router-secret", result.stdout + result.stderr)
            self.assertNotIn("telegram-secret", result.stdout + result.stderr)
            self.assertEqual(env_file.stat().st_mode & 0o777, 0o640)
            canonical_cert = root / "etc/mikroclear/certs/mikrotik-ca.crt"
            self.assertTrue(canonical_cert.is_file())
            self.assertEqual(canonical_cert.stat().st_mode & 0o777, 0o640)
            self.assertEqual(canonical_cert.parent.stat().st_mode & 0o777, 0o750)
            backups = list(
                (root / "var/backups/mikroclear").glob(
                    "pre-f6ac4d2-*/mikroclear.env"
                )
            )
            self.assertEqual(len(backups), 1)

            repeated = self.run_script(root, "--apply")

            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            repeated_content = env_file.read_text(encoding="utf-8")
            self.assertEqual(repeated_content, content)
            for key in expected:
                self.assertEqual(repeated_content.count(f"{key}="), 1)

    def test_apply_preserves_existing_bot_authorization_lists(self):
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            env_file = root / "etc/mikroclear/mikroclear.env"
            with env_file.open("a", encoding="utf-8") as stream:
                stream.write(
                    "MIKROCLEAR_BOT_ADMIN_CHAT_IDS=111,222\n"
                    "MIKROCLEAR_BOT_ALLOWED_CHAT_IDS=333\n"
                )

            result = self.run_script(root, "--apply")

            self.assertEqual(result.returncode, 0, result.stderr)
            content = env_file.read_text(encoding="utf-8")
            self.assertEqual(content.count("MIKROCLEAR_BOT_ADMIN_CHAT_IDS="), 1)
            self.assertIn("MIKROCLEAR_BOT_ADMIN_CHAT_IDS=111,222\n", content)
            self.assertEqual(content.count("MIKROCLEAR_BOT_ALLOWED_CHAT_IDS="), 1)
            self.assertIn("MIKROCLEAR_BOT_ALLOWED_CHAT_IDS=333\n", content)

    def test_apply_preserves_explicit_empty_bot_authorization_lists(self):
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            env_file = root / "etc/mikroclear/mikroclear.env"
            with env_file.open("a", encoding="utf-8") as stream:
                stream.write(
                    "MIKROCLEAR_BOT_ADMIN_CHAT_IDS=\n"
                    "MIKROCLEAR_BOT_ALLOWED_CHAT_IDS=\n"
                )

            result = self.run_script(root, "--apply")

            self.assertEqual(result.returncode, 0, result.stderr)
            content = env_file.read_text(encoding="utf-8")
            self.assertIn("MIKROCLEAR_BOT_ADMIN_CHAT_IDS=\n", content)
            self.assertIn("MIKROCLEAR_BOT_ALLOWED_CHAT_IDS=\n", content)
            self.assertNotIn("MIKROCLEAR_BOT_ADMIN_CHAT_IDS=123456", content)
            self.assertNotIn("MIKROCLEAR_BOT_ALLOWED_CHAT_IDS=123456", content)

    def test_requires_enabled_telegram_credentials_before_creating_backup(self):
        cases = (
            (
                'MIKROCLEAR_TELEGRAM_TOKEN="telegram-secret"\n',
                "",
                "MIKROCLEAR_TELEGRAM_TOKEN",
            ),
            (
                'MIKROCLEAR_TELEGRAM_CHATID="123456"\n',
                "",
                "MIKROCLEAR_TELEGRAM_CHATID",
            ),
            (
                "MIKROCLEAR_TELEGRAM_ENABLE=true\n",
                "MIKROCLEAR_TELEGRAM_ENABLE=false\n",
                "MIKROCLEAR_TELEGRAM_ENABLE",
            ),
        )
        for old, new, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                with tempfile.TemporaryDirectory(
                    prefix="mikroclear-migration-test-"
                ) as temporary:
                    root = self.make_root(temporary)
                    env_file = root / "etc/mikroclear/mikroclear.env"
                    content = env_file.read_text(encoding="utf-8").replace(old, new)
                    env_file.write_text(content, encoding="utf-8")
                    original = env_file.read_bytes()

                    result = self.run_script(root, "--apply")

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected_error, result.stderr)
                    self.assertEqual(env_file.read_bytes(), original)
                    self.assertFalse((root / "var/backups/mikroclear").exists())
                    self.assertFalse(
                        (root / "etc/mikroclear/certs/mikrotik-ca.crt").exists()
                    )

    def test_invalid_runtime_values_fail_before_creating_backup(self):
        cases = (
            (
                "MIKROCLEAR_ROUTER_PORT=8729\n",
                "MIKROCLEAR_ROUTER_PORT=70000\n",
                "MIKROCLEAR_ROUTER_PORT",
            ),
            (
                "MIKROCLEAR_STATE_DIR=/var/lib/mikroclear\n",
                "MIKROCLEAR_STATE_DIR=relative/state\n",
                "MIKROCLEAR_STATE_DIR",
            ),
            (
                'MIKROCLEAR_TELEGRAM_CHATID="123456"\n',
                'MIKROCLEAR_TELEGRAM_CHATID="not-a-chat"\n',
                "MIKROCLEAR_TELEGRAM_CHATID",
            ),
        )
        for old, new, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                with tempfile.TemporaryDirectory(
                    prefix="mikroclear-migration-test-"
                ) as temporary:
                    root = self.make_root(temporary)
                    env_file = root / "etc/mikroclear/mikroclear.env"
                    content = env_file.read_text(encoding="utf-8").replace(old, new)
                    env_file.write_text(content, encoding="utf-8")
                    original = env_file.read_bytes()

                    result = self.run_script(root, "--apply")

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected_error, result.stderr)
                    self.assertEqual(env_file.read_bytes(), original)
                    self.assertFalse((root / "var/backups/mikroclear").exists())

    def test_test_root_rejects_parent_directory_escape(self):
        migration = load_migration_module()

        with patch.dict(
            os.environ,
            {
                "MIKROCLEAR_MIGRATION_TEST_MODE": "1",
                "MIKROCLEAR_MIGRATION_TEST_ROOT": "/tmp/../etc",
            },
            clear=True,
        ):
            with self.assertRaises(migration.MigrationError):
                migration.test_root()

    def test_configured_ca_path_cannot_escape_test_root(self):
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            sandbox = Path(temporary)
            root = sandbox / "root"
            root.mkdir()
            self.make_root(str(root))
            legacy_cert = root / "etc/mikrocata/certs/mikrotik-ca.crt"
            external_cert = sandbox / "outside.crt"
            shutil.copyfile(legacy_cert, external_cert)
            env_file = root / "etc/mikroclear/mikroclear.env"
            content = env_file.read_text(encoding="utf-8").replace(
                'MIKROCLEAR_CA_FILE="/etc/mikrocata/certs/mikrotik-ca.crt"',
                'MIKROCLEAR_CA_FILE="/../outside.crt"',
            )
            env_file.write_text(content, encoding="utf-8")
            original = env_file.read_bytes()

            result = self.run_script(root, "--apply")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside test root", result.stderr)
            self.assertEqual(env_file.read_bytes(), original)
            self.assertFalse(
                (root / "etc/mikroclear/certs/mikrotik-ca.crt").exists()
            )

    def test_explicit_missing_ca_path_does_not_fall_back_to_legacy(self):
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            env_file = root / "etc/mikroclear/mikroclear.env"
            content = env_file.read_text(encoding="utf-8").replace(
                'MIKROCLEAR_CA_FILE="/etc/mikrocata/certs/mikrotik-ca.crt"',
                'MIKROCLEAR_CA_FILE="/custom/missing-ca.crt"',
            )
            env_file.write_text(content, encoding="utf-8")
            original = env_file.read_bytes()

            result = self.run_script(root, "--apply")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing-ca.crt", result.stderr)
            self.assertEqual(env_file.read_bytes(), original)
            self.assertFalse((root / "var/backups/mikroclear").exists())

    def test_dangling_canonical_certificate_symlink_fails_before_backup(self):
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            canonical_cert = root / "etc/mikroclear/certs/mikrotik-ca.crt"
            canonical_cert.parent.mkdir(parents=True)
            canonical_cert.symlink_to(canonical_cert.parent / "missing.crt")

            result = self.run_script(root, "--apply")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("regular file", result.stderr)
            self.assertTrue(canonical_cert.is_symlink())
            self.assertFalse((root / "var/backups/mikroclear").exists())

    def test_certificate_validation_returns_the_exact_bytes_it_validated(self):
        migration = load_migration_module()
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            certificate = root / "etc/mikrocata/certs/mikrotik-ca.crt"
            original_content = certificate.read_bytes()
            replacement = root / "replacement.crt"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-subj",
                    "/CN=mikroclear-replacement-test",
                    "-days",
                    "1",
                    "-keyout",
                    str(root / "replacement.key"),
                    "-out",
                    str(replacement),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            replacement_content = replacement.read_bytes()
            original_run = migration.subprocess.run

            def replace_inode_content_then_validate(*arguments, **keywords):
                certificate.write_bytes(replacement_content)
                return original_run(*arguments, **keywords)

            with patch.object(
                migration.subprocess,
                "run",
                side_effect=replace_inode_content_then_validate,
            ):
                validated_content = migration.validate_certificate(certificate)

            self.assertEqual(validated_content, original_content)

    def test_partial_write_failure_restores_existing_config_and_certificate(self):
        migration = load_migration_module()
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            env_file = root / "etc/mikroclear/mikroclear.env"
            canonical_cert = root / "etc/mikroclear/certs/mikrotik-ca.crt"
            canonical_cert.parent.mkdir(parents=True)
            os.chmod(canonical_cert.parent, 0o711)
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-subj",
                    "/CN=mikroclear-existing-canonical-test",
                    "-days",
                    "1",
                    "-keyout",
                    str(root / "canonical-test.key"),
                    "-out",
                    str(canonical_cert),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            original_env = env_file.read_bytes()
            original_cert = canonical_cert.read_bytes()
            original_replace = migration.os.replace
            replace_calls = 0

            def fail_second_replace(source, destination):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 2:
                    raise OSError("injected environment replacement failure")
                return original_replace(source, destination)

            with patch.object(
                migration.os,
                "replace",
                side_effect=fail_second_replace,
            ):
                with self.assertRaises(OSError):
                    migration.migrate(root)

            self.assertEqual(env_file.read_bytes(), original_env)
            self.assertEqual(canonical_cert.read_bytes(), original_cert)
            self.assertEqual(canonical_cert.parent.stat().st_mode & 0o777, 0o711)

    def test_partial_write_failure_removes_new_certificate_directory(self):
        migration = load_migration_module()
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            env_file = root / "etc/mikroclear/mikroclear.env"
            canonical_dir = root / "etc/mikroclear/certs"
            original_env = env_file.read_bytes()
            original_replace = migration.os.replace
            replace_calls = 0

            def fail_second_replace(source, destination):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 2:
                    raise OSError("injected environment replacement failure")
                return original_replace(source, destination)

            with patch.object(
                migration.os,
                "replace",
                side_effect=fail_second_replace,
            ):
                with self.assertRaises(OSError):
                    migration.migrate(root)

            self.assertEqual(env_file.read_bytes(), original_env)
            self.assertFalse(canonical_dir.exists())

    def test_post_write_validation_failure_restores_absent_certificate_state(self):
        migration = load_migration_module()
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            env_file = root / "etc/mikroclear/mikroclear.env"
            canonical_dir = root / "etc/mikroclear/certs"
            original_env = env_file.read_bytes()
            original_validate = migration.validate_certificate
            validation_calls = 0

            def fail_final_validation(path):
                nonlocal validation_calls
                validation_calls += 1
                if validation_calls == 3:
                    raise migration.MigrationError(
                        "injected post-write validation failure"
                    )
                return original_validate(path)

            with patch.object(
                migration,
                "validate_certificate",
                side_effect=fail_final_validation,
            ):
                with self.assertRaises(migration.MigrationError):
                    migration.migrate(root)

            self.assertEqual(env_file.read_bytes(), original_env)
            self.assertFalse(canonical_dir.exists())

    def test_post_write_invalid_utf8_is_normalized_and_rolled_back(self):
        migration = load_migration_module()
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            env_file = root / "etc/mikroclear/mikroclear.env"
            original_env = env_file.read_bytes()
            original_replace = migration.os.replace
            corrupted = False

            def corrupt_replaced_environment(source, destination):
                nonlocal corrupted
                result = original_replace(source, destination)
                if Path(destination) == env_file and not corrupted:
                    corrupted = True
                    env_file.write_bytes(b"\xff\n")
                return result

            with patch.object(
                migration.os,
                "replace",
                side_effect=corrupt_replaced_environment,
            ):
                with self.assertRaises(migration.MigrationError):
                    migration.migrate(root)

            self.assertEqual(env_file.read_bytes(), original_env)

    def test_certificate_restore_failure_does_not_skip_environment_restore(self):
        migration = load_migration_module()
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            env_file = root / "etc/mikroclear/mikroclear.env"
            canonical_cert = root / "etc/mikroclear/certs/mikrotik-ca.crt"
            canonical_cert.parent.mkdir(parents=True)
            shutil.copyfile(
                root / "etc/mikrocata/certs/mikrotik-ca.crt",
                canonical_cert,
            )
            original_env = env_file.read_bytes()
            original_validate = migration.validate_certificate
            original_replace = migration.os.replace
            validation_calls = 0

            def fail_final_validation(path):
                nonlocal validation_calls
                validation_calls += 1
                if validation_calls == 3:
                    raise migration.MigrationError(
                        "injected post-write validation failure"
                    )
                return original_validate(path)

            def fail_certificate_restore(source, destination):
                if (
                    ".rollback." in Path(source).name
                    and Path(destination) == canonical_cert
                ):
                    raise OSError("injected certificate restore failure")
                return original_replace(source, destination)

            with (
                patch.object(
                    migration,
                    "validate_certificate",
                    side_effect=fail_final_validation,
                ),
                patch.object(
                    migration.os,
                    "replace",
                    side_effect=fail_certificate_restore,
                ),
            ):
                with self.assertRaises(migration.MigrationError):
                    migration.migrate(root)

            self.assertEqual(env_file.read_bytes(), original_env)

    def test_backup_and_staged_metadata_are_fsynced_before_mutation(self):
        migration = load_migration_module()
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            original_fsync = migration.os.fsync
            fsynced: dict[str, int] = {}

            def record_fsync(descriptor):
                try:
                    path = os.readlink(f"/proc/self/fd/{descriptor}")
                except OSError:
                    path = ""
                if str(root) in path:
                    fsynced[path] = os.fstat(descriptor).st_mode & 0o777
                return original_fsync(descriptor)

            with patch.object(
                migration.os,
                "fsync",
                side_effect=record_fsync,
            ):
                migration.migrate(root)

            backup_env = [
                mode
                for path, mode in fsynced.items()
                if "pre-f6ac4d2-" in path and path.endswith("/mikroclear.env")
            ]
            staged_env = [
                mode
                for path, mode in fsynced.items()
                if "/.mikroclear.env." in path
                and ".rollback." not in path
            ]
            staged_cert = [
                mode
                for path, mode in fsynced.items()
                if "/.mikrotik-ca.crt." in path
                and ".rollback." not in path
            ]
            self.assertEqual(backup_env, [0o600])
            self.assertEqual(staged_env, [0o640])
            self.assertEqual(staged_cert, [0o640])
            self.assertIn(str(root / "var/backups"), fsynced)

    def test_writable_backup_root_fails_before_configuration_mutation(self):
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            env_file = root / "etc/mikroclear/mikroclear.env"
            backup_root = root / "var/backups/mikroclear"
            backup_root.mkdir(parents=True)
            os.chmod(backup_root, 0o777)
            original_env = env_file.read_bytes()

            result = self.run_script(root, "--apply")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("backup root", result.stderr)
            self.assertEqual(env_file.read_bytes(), original_env)
            self.assertEqual(list(backup_root.iterdir()), [])

    def test_backup_failure_does_not_change_certificate_directory(self):
        migration = load_migration_module()
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            canonical_dir = root / "etc/mikroclear/certs"
            canonical_dir.mkdir(parents=True)
            os.chmod(canonical_dir, 0o711)

            with patch.object(
                migration,
                "make_backup",
                side_effect=OSError("injected backup failure"),
            ):
                with self.assertRaises(OSError):
                    migration.migrate(root)

            self.assertEqual(canonical_dir.stat().st_mode & 0o777, 0o711)

    def test_invalid_certificate_leaves_configuration_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            env_file = root / "etc/mikroclear/mikroclear.env"
            original = env_file.read_bytes()
            (root / "etc/mikrocata/certs/mikrotik-ca.crt").write_text(
                "not a certificate\n",
                encoding="utf-8",
            )

            result = self.run_script(root, "--apply")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("certificate", result.stderr.lower())
            self.assertEqual(env_file.read_bytes(), original)
            self.assertFalse(
                (root / "etc/mikroclear/certs/mikrotik-ca.crt").exists()
            )

    def test_apply_flag_is_required(self):
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)
            env_file = root / "etc/mikroclear/mikroclear.env"
            original = env_file.read_bytes()

            result = self.run_script(root)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--apply", result.stderr)
            self.assertEqual(env_file.read_bytes(), original)

    def test_test_mode_success_reports_test_paths(self):
        with tempfile.TemporaryDirectory(prefix="mikroclear-migration-test-") as temporary:
            root = self.make_root(temporary)

            result = self.run_script(root, "--apply")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                f"Configuration: {root}/etc/mikroclear/mikroclear.env",
                result.stdout,
            )
            self.assertIn(
                f"CA certificate: {root}/etc/mikroclear/certs/mikrotik-ca.crt",
                result.stdout,
            )


if __name__ == "__main__":
    unittest.main()
