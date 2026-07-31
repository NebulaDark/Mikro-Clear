#!/usr/bin/env python3
"""One-time migration of an existing SELKS Mikro-Clear configuration."""

from __future__ import annotations

import argparse
import datetime as dt
import errno
import fcntl
import grp
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


ENV_FILE = Path("/etc/mikroclear/mikroclear.env")
CANONICAL_CERT = Path("/etc/mikroclear/certs/mikrotik-ca.crt")
LEGACY_CERT = Path("/etc/mikrocata/certs/mikrotik-ca.crt")
BACKUP_ROOT = Path("/var/backups/mikroclear")
LOCK_FILE = Path("/run/lock/mikroclear-config-migration.lock")
OPENSSL = Path("/usr/bin/openssl")
EVE_JSON = Path(
    "/opt/SELKS/docker/containers-data/suricata/logs/eve.json"
)
SERVICE_GROUP = "mikroclear"
TARGET_VALUES = {
    "MIKROCLEAR_EVE_JSON": str(EVE_JSON),
    "MIKROCLEAR_CA_FILE": str(CANONICAL_CERT),
    "MIKROCLEAR_BOT_ENABLE": "true",
    "MIKROCLEAR_BOT_DRY_RUN": "true",
    "MIKROCLEAR_BOT_MODULES": (
        "status,asset_resolver,mangle_control,parental_control,"
        "whitelist_control"
    ),
    "MIKROCLEAR_TELEGRAM_UNBLOCK_ENABLE": "true",
    "MIKROCLEAR_TELEGRAM_WHITELIST_CONTROL_ENABLE": "true",
}
REQUIRED_EXISTING = (
    "MIKROCLEAR_ROUTER_USERNAME",
    "MIKROCLEAR_ROUTER_PASSWORD",
    "MIKROCLEAR_ROUTER_IP",
    "MIKROCLEAR_ROUTER_PORT",
    "MIKROCLEAR_STATE_DIR",
    "MIKROCLEAR_TELEGRAM_ENABLE",
    "MIKROCLEAR_TELEGRAM_TOKEN",
    "MIKROCLEAR_TELEGRAM_CHATID",
)
ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
CHAT_ID = re.compile(r"-?[0-9]+")
TRUE_VALUES = frozenset(("1", "true", "yes", "on"))
OPEN_REGULAR_FLAGS = (
    os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
)


class MigrationError(RuntimeError):
    pass


def test_root() -> Path | None:
    if os.environ.get("MIKROCLEAR_MIGRATION_TEST_MODE") != "1":
        return None
    raw_root = os.environ.get("MIKROCLEAR_MIGRATION_TEST_ROOT", "")
    requested_root = Path(raw_root)
    if not requested_root.is_absolute():
        raise MigrationError("test root must be an existing directory below /tmp")
    try:
        metadata = requested_root.lstat()
    except FileNotFoundError as error:
        raise MigrationError("test root does not exist") from error
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise MigrationError("test root must be a real directory")
    root = requested_root.resolve(strict=True)
    temporary_root = Path("/tmp").resolve(strict=True)
    try:
        relative = root.relative_to(temporary_root)
    except ValueError as error:
        raise MigrationError(
            "test root must be an existing directory below /tmp"
        ) from error
    if not relative.parts:
        raise MigrationError("test root must be an existing directory below /tmp")
    return root


def target(path: Path, root: Path | None) -> Path:
    if root is None:
        return path
    resolved_root = root.resolve(strict=True)
    candidate = resolved_root / path.relative_to("/")
    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as error:
        raise MigrationError(f"path is outside test root: {path}") from error
    return candidate


def require_root(root: Path | None) -> None:
    if root is None and os.geteuid() != 0:
        raise MigrationError("run this migration as root")


def runtime_file_owner(root: Path | None) -> tuple[int, int]:
    if root is not None:
        return os.getuid(), os.getgid()
    try:
        service_gid = grp.getgrnam(SERVICE_GROUP).gr_gid
    except KeyError as error:
        raise MigrationError(
            f"required service group does not exist: {SERVICE_GROUP}"
        ) from error
    return 0, service_gid


def ensure_real_directory(path: Path, mode: int) -> None:
    if path.exists():
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise MigrationError(f"unsafe directory path: {path}")
        return
    path.mkdir(mode=mode, parents=True)
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise MigrationError(f"unsafe directory path: {path}")


def decode_env_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == '"':
        inner = value[1:-1]
        return inner.replace(r"\\", "\\").replace(r"\"", '"')
    return value


def parse_values(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in content.splitlines():
        match = ASSIGNMENT.match(line)
        if match:
            values[match.group(1)] = decode_env_value(match.group(2))
    return values


def decode_environment(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MigrationError("environment file is not valid UTF-8") from error


def validate_existing_values(values: dict[str, str]) -> None:
    missing = [key for key in REQUIRED_EXISTING if not values.get(key)]
    if missing:
        raise MigrationError(
            "existing configuration is incomplete; missing: "
            + ", ".join(missing)
        )
    if values["MIKROCLEAR_TELEGRAM_ENABLE"].strip().lower() not in TRUE_VALUES:
        raise MigrationError(
            "existing configuration must set MIKROCLEAR_TELEGRAM_ENABLE=true"
        )
    try:
        router_port = int(values["MIKROCLEAR_ROUTER_PORT"])
    except ValueError as error:
        raise MigrationError(
            "MIKROCLEAR_ROUTER_PORT must be an integer from 1 to 65535"
        ) from error
    if not 1 <= router_port <= 65535:
        raise MigrationError(
            "MIKROCLEAR_ROUTER_PORT must be an integer from 1 to 65535"
        )
    if not Path(values["MIKROCLEAR_STATE_DIR"]).is_absolute():
        raise MigrationError("MIKROCLEAR_STATE_DIR must contain an absolute path")
    validate_chat_ids(
        "MIKROCLEAR_TELEGRAM_CHATID",
        values["MIKROCLEAR_TELEGRAM_CHATID"],
        allow_empty=False,
    )
    for key in (
        "MIKROCLEAR_BOT_ADMIN_CHAT_IDS",
        "MIKROCLEAR_BOT_ALLOWED_CHAT_IDS",
    ):
        if key in values:
            validate_chat_ids(key, values[key], allow_empty=True)


def validate_chat_ids(name: str, value: str, *, allow_empty: bool) -> None:
    entries = tuple(item.strip() for item in value.split(","))
    if allow_empty and entries == ("",):
        return
    if not entries or any(not CHAT_ID.fullmatch(item) for item in entries):
        raise MigrationError(f"{name} must contain comma-separated numeric chat IDs")


def open_regular_file(
    path: Path,
    description: str,
    *,
    optional: bool = False,
) -> tuple[int, os.stat_result] | None:
    try:
        descriptor = os.open(path, OPEN_REGULAR_FLAGS)
    except FileNotFoundError:
        if optional:
            return None
        raise MigrationError(f"{description} is missing: {path}") from None
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise MigrationError(
                f"{description} must be a regular file: {path}"
            ) from error
        raise
    try:
        metadata = os.fstat(descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    if not stat.S_ISREG(metadata.st_mode):
        os.close(descriptor)
        raise MigrationError(f"{description} must be a regular file: {path}")
    return descriptor, metadata


def read_regular_file(
    path: Path,
    description: str,
    *,
    optional: bool = False,
) -> tuple[bytes, os.stat_result] | None:
    opened = open_regular_file(path, description, optional=optional)
    if opened is None:
        return None
    descriptor, metadata = opened
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                return b"".join(chunks), metadata
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def validate_certificate(path: Path) -> bytes:
    opened = open_regular_file(path, "CA certificate")
    if opened is None:
        raise AssertionError("required certificate unexpectedly missing")
    descriptor, _metadata = opened
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                certificate_content = b"".join(chunks)
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)

    result = subprocess.run(
        [
            str(OPENSSL),
            "x509",
            "-noout",
            "-checkend",
            "0",
        ],
        input=certificate_content,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise MigrationError(
            f"CA certificate is invalid or expired: {path}"
        )
    return certificate_content


def desired_values(existing: dict[str, str]) -> dict[str, str]:
    values = dict(TARGET_VALUES)
    legacy_chat_id = existing["MIKROCLEAR_TELEGRAM_CHATID"]
    values["MIKROCLEAR_BOT_ADMIN_CHAT_IDS"] = existing.get(
        "MIKROCLEAR_BOT_ADMIN_CHAT_IDS",
        legacy_chat_id,
    )
    values["MIKROCLEAR_BOT_ALLOWED_CHAT_IDS"] = existing.get(
        "MIKROCLEAR_BOT_ALLOWED_CHAT_IDS",
        legacy_chat_id,
    )
    return values


def render_config(content: str, replacements: dict[str, str]) -> str:
    retained: list[str] = []
    for line in content.splitlines():
        match = ASSIGNMENT.match(line)
        if match and match.group(1) in replacements:
            continue
        retained.append(line)
    while retained and not retained[-1]:
        retained.pop()
    if retained:
        retained.append("")
    retained.extend(f"{key}={value}" for key, value in replacements.items())
    return "\n".join(retained) + "\n"


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def stage_file(
    directory: Path,
    prefix: str,
    content: bytes,
    mode: int,
    *,
    production: bool,
    owner: tuple[int, int] | None = None,
) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=prefix, dir=directory)
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), mode)
            if production:
                os.fchown(stream.fileno(), *(owner or (0, 0)))
            stream.flush()
            os.fsync(stream.fileno())
        return staged
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def write_backup_file(
    path: Path,
    content: bytes,
    *,
    production: bool,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), 0o600)
            if production:
                os.fchown(stream.fileno(), 0, 0)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def prepare_backup_root(path: Path, *, production: bool) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        path.mkdir(mode=0o700, parents=True)
        fsync_directory(path.parent)
        metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise MigrationError(f"unsafe backup root: {path}")
    expected_uid = 0 if production else os.getuid()
    if metadata.st_uid != expected_uid:
        raise MigrationError(f"backup root has unexpected owner: {path}")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise MigrationError(f"backup root must not be group/world-writable: {path}")


def make_backup(
    backup_root: Path,
    env_content: bytes,
    canonical_content: bytes | None,
    *,
    production: bool,
) -> Path:
    prepare_backup_root(backup_root, production=production)
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_root / f"pre-f6ac4d2-{timestamp}-{os.getpid()}"
    backup.mkdir(mode=0o700)
    write_backup_file(
        backup / "mikroclear.env",
        env_content,
        production=production,
    )
    if canonical_content is not None:
        write_backup_file(
            backup / "mikrotik-ca.crt",
            canonical_content,
            production=production,
        )
    if production:
        os.chown(backup, 0, 0)
    fsync_directory(backup)
    fsync_directory(backup_root)
    return backup


def restore_backup(
    backup: Path,
    env_file: Path,
    canonical_cert: Path,
    env_metadata: os.stat_result,
    canonical_metadata: os.stat_result | None,
    *,
    production: bool,
) -> None:
    errors: list[BaseException] = []
    backup_cert = backup / "mikrotik-ca.crt"
    try:
        if canonical_metadata is None:
            canonical_cert.unlink(missing_ok=True)
            fsync_directory(canonical_cert.parent)
        else:
            backup_cert_content = backup_cert.read_bytes()
            restored_cert = stage_file(
                canonical_cert.parent,
                ".mikrotik-ca.crt.rollback.",
                backup_cert_content,
                stat.S_IMODE(canonical_metadata.st_mode),
                production=production,
                owner=(canonical_metadata.st_uid, canonical_metadata.st_gid),
            )
            try:
                os.replace(restored_cert, canonical_cert)
                restored_cert = None
                fsync_directory(canonical_cert.parent)
                verify_restored_file(
                    canonical_cert,
                    backup_cert_content,
                    canonical_metadata,
                    production=production,
                )
            finally:
                if restored_cert is not None:
                    restored_cert.unlink(missing_ok=True)
    except BaseException as error:
        errors.append(error)

    try:
        backup_env_content = (backup / "mikroclear.env").read_bytes()
        restored_env = stage_file(
            env_file.parent,
            ".mikroclear.env.rollback.",
            backup_env_content,
            stat.S_IMODE(env_metadata.st_mode),
            production=production,
            owner=(env_metadata.st_uid, env_metadata.st_gid),
        )
        try:
            os.replace(restored_env, env_file)
            restored_env = None
            fsync_directory(env_file.parent)
            verify_restored_file(
                env_file,
                backup_env_content,
                env_metadata,
                production=production,
            )
        finally:
            if restored_env is not None:
                restored_env.unlink(missing_ok=True)
    except BaseException as error:
        errors.append(error)

    if errors:
        raise MigrationError(
            f"backup restoration failed for {len(errors)} target(s)"
        ) from errors[0]


def verify_restored_file(
    path: Path,
    expected_content: bytes,
    expected_metadata: os.stat_result,
    *,
    production: bool,
) -> None:
    restored = read_regular_file(path, "restored file")
    if restored is None:
        raise AssertionError("restored file unexpectedly missing")
    content, metadata = restored
    if content != expected_content:
        raise MigrationError(f"restored file content mismatch: {path}")
    if stat.S_IMODE(metadata.st_mode) != stat.S_IMODE(expected_metadata.st_mode):
        raise MigrationError(f"restored file mode mismatch: {path}")
    if production and (
        metadata.st_uid != expected_metadata.st_uid
        or metadata.st_gid != expected_metadata.st_gid
    ):
        raise MigrationError(f"restored file ownership mismatch: {path}")


def restore_directory(
    path: Path,
    metadata: os.stat_result | None,
    *,
    production: bool,
) -> None:
    if metadata is None:
        path.rmdir()
    else:
        if production:
            os.chown(path, metadata.st_uid, metadata.st_gid)
        os.chmod(path, stat.S_IMODE(metadata.st_mode))
        restored = path.lstat()
        if (
            restored.st_dev != metadata.st_dev
            or restored.st_ino != metadata.st_ino
            or stat.S_IMODE(restored.st_mode) != stat.S_IMODE(metadata.st_mode)
            or (
                production
                and (
                    restored.st_uid != metadata.st_uid
                    or restored.st_gid != metadata.st_gid
                )
            )
        ):
            raise MigrationError(f"restored directory metadata mismatch: {path}")
        fsync_directory(path)
    fsync_directory(path.parent)


def migrate(root: Path | None) -> Path:
    production = root is None
    runtime_owner = runtime_file_owner(root)
    env_file = target(ENV_FILE, root)
    canonical_cert = target(CANONICAL_CERT, root)
    backup_root = target(BACKUP_ROOT, root)

    env_read = read_regular_file(env_file, "Mikro-Clear environment file")
    if env_read is None:
        raise AssertionError("required environment file unexpectedly missing")
    env_content, env_metadata = env_read
    content = decode_environment(env_content)
    values = parse_values(content)
    validate_existing_values(values)
    replacements = desired_values(values)

    configured_source = values.get("MIKROCLEAR_CA_FILE", "")
    if not configured_source:
        configured_source = str(LEGACY_CERT)
    if not Path(configured_source).is_absolute():
        raise MigrationError("MIKROCLEAR_CA_FILE must contain an absolute path")
    source_cert = target(Path(configured_source), root)
    certificate_content = validate_certificate(source_cert)
    migrated_content = render_config(content, replacements)
    validate_existing_values(parse_values(migrated_content))

    canonical_directory = canonical_cert.parent
    try:
        canonical_directory_metadata = canonical_directory.lstat()
    except FileNotFoundError:
        canonical_directory_metadata = None
    else:
        if (
            stat.S_ISLNK(canonical_directory_metadata.st_mode)
            or not stat.S_ISDIR(canonical_directory_metadata.st_mode)
        ):
            raise MigrationError(
                f"unsafe directory path: {canonical_directory}"
            )
    canonical_read = read_regular_file(
        canonical_cert,
        "canonical CA certificate",
        optional=True,
    )
    if canonical_read is None:
        canonical_content = None
        canonical_metadata = None
    else:
        canonical_content, canonical_metadata = canonical_read
    backup = make_backup(
        backup_root,
        env_content,
        canonical_content,
        production=production,
    )

    canonical_directory_ready = False
    try:
        ensure_real_directory(canonical_directory, 0o750)
        canonical_directory_ready = True
        os.chmod(canonical_directory, 0o750)
        if production:
            os.chown(canonical_directory, *runtime_owner)

        staged_cert: Path | None = None
        staged_env: Path | None = None
        try:
            staged_cert = stage_file(
                canonical_cert.parent,
                ".mikrotik-ca.crt.",
                certificate_content,
                0o640,
                production=production,
                owner=runtime_owner,
            )
            if validate_certificate(staged_cert) != certificate_content:
                raise MigrationError("staged CA certificate content mismatch")
            staged_env = stage_file(
                env_file.parent,
                ".mikroclear.env.",
                migrated_content.encode("utf-8"),
                0o640,
                production=production,
                owner=runtime_owner,
            )
            os.replace(staged_cert, canonical_cert)
            staged_cert = None
            fsync_directory(canonical_cert.parent)
            os.replace(staged_env, env_file)
            staged_env = None
            fsync_directory(env_file.parent)
        finally:
            if staged_cert is not None:
                staged_cert.unlink(missing_ok=True)
            if staged_env is not None:
                staged_env.unlink(missing_ok=True)

        if validate_certificate(canonical_cert) != certificate_content:
            raise MigrationError("post-write CA certificate content mismatch")
        final_env = read_regular_file(
            env_file,
            "Mikro-Clear environment file",
        )
        if final_env is None:
            raise AssertionError("required environment file unexpectedly missing")
        final_values = parse_values(decode_environment(final_env[0]))
        for key, expected in replacements.items():
            if final_values.get(key) != expected:
                raise MigrationError(f"post-write validation failed for {key}")
    except BaseException:
        rollback_error: BaseException | None = None
        try:
            if canonical_directory_ready:
                restore_backup(
                    backup,
                    env_file,
                    canonical_cert,
                    env_metadata,
                    canonical_metadata,
                    production=production,
                )
        except BaseException as error:
            rollback_error = error
        try:
            if canonical_directory_ready:
                restore_directory(
                    canonical_directory,
                    canonical_directory_metadata,
                    production=production,
                )
        except BaseException as error:
            if rollback_error is None:
                rollback_error = error
        if rollback_error is not None:
            raise MigrationError(
                "migration failed and backup restoration also failed"
            ) from rollback_error
        raise
    return backup


def acquire_lock(root: Path | None):
    lock_file = target(LOCK_FILE, root)
    ensure_real_directory(lock_file.parent, 0o755)
    stream = lock_file.open("a+", encoding="utf-8")
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        stream.close()
        raise MigrationError("another configuration migration is running") from error
    return stream


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate an existing Mikro-Clear SELKS configuration."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="create a backup and apply the migration",
    )
    arguments = parser.parse_args()
    if not arguments.apply:
        print("ERROR: pass --apply to perform the migration", file=sys.stderr)
        return 2
    try:
        root = test_root()
        require_root(root)
        with acquire_lock(root):
            backup = migrate(root)
    except (MigrationError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Mikro-Clear configuration migration completed.")
    print(f"Backup: {backup}")
    print(f"Configuration: {target(ENV_FILE, root)}")
    print(f"CA certificate: {target(CANONICAL_CERT, root)}")
    print("Bot control: enabled; write operations remain in dry-run mode.")
    print("Service and installer were not started or restarted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
