#!/usr/bin/env python3
"""Normalize migrated Mikro-Clear runtime files without following symlinks."""

from __future__ import annotations

import argparse
import grp
import os
from pathlib import Path
import pwd
import stat


_OPEN_BASE = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK


def _same_object(expected: os.stat_result, actual: os.stat_result) -> bool:
    return (
        expected.st_dev == actual.st_dev
        and expected.st_ino == actual.st_ino
    )


def _normalize_regular_path(
    path: Path,
    *,
    mode: int,
    uid: int,
    gid: int,
    optional: bool = False,
) -> None:
    try:
        descriptor = os.open(path, _OPEN_BASE)
    except FileNotFoundError:
        if optional:
            return
        raise
    try:
        current = os.fstat(descriptor)
        if not stat.S_ISREG(current.st_mode):
            raise OSError(f"unexpected non-regular file: {path}")
        os.fchmod(descriptor, mode)
        os.fchown(descriptor, uid, gid)
    finally:
        os.close(descriptor)


def _normalize_state_directory(
    descriptor: int,
    *,
    service_uid: int,
    service_gid: int,
    root_device: int | None = None,
) -> None:
    current = os.fstat(descriptor)
    if not stat.S_ISDIR(current.st_mode):
        raise OSError("state root is not a directory")
    if root_device is None:
        root_device = current.st_dev
    elif current.st_dev != root_device:
        raise OSError("cross-device state directory")
    os.fchmod(descriptor, 0o700)
    os.fchown(descriptor, service_uid, service_gid)

    for name in os.listdir(descriptor):
        expected = os.stat(
            name,
            dir_fd=descriptor,
            follow_symlinks=False,
        )
        if expected.st_dev != root_device:
            raise OSError(f"cross-device state entry: {name}")
        if stat.S_ISDIR(expected.st_mode):
            child = os.open(
                name,
                _OPEN_BASE | os.O_DIRECTORY,
                dir_fd=descriptor,
            )
            try:
                actual = os.fstat(child)
                if not _same_object(expected, actual):
                    raise OSError(f"state directory changed during migration: {name}")
                _normalize_state_directory(
                    child,
                    service_uid=service_uid,
                    service_gid=service_gid,
                    root_device=root_device,
                )
            finally:
                os.close(child)
            continue
        if stat.S_ISREG(expected.st_mode):
            child = os.open(
                name,
                _OPEN_BASE,
                dir_fd=descriptor,
            )
            try:
                actual = os.fstat(child)
                if (
                    not stat.S_ISREG(actual.st_mode)
                    or not _same_object(expected, actual)
                ):
                    raise OSError(f"state file changed during migration: {name}")
                os.fchmod(child, 0o600)
                os.fchown(child, service_uid, service_gid)
            finally:
                os.close(child)
            continue
        raise OSError(f"unexpected state entry: {name}")


def normalize_permissions(
    *,
    env_file: Path,
    ca_file: Path,
    state_dir: Path,
    config_uid: int,
    service_uid: int,
    service_gid: int,
) -> None:
    _normalize_regular_path(
        env_file,
        mode=0o640,
        uid=config_uid,
        gid=service_gid,
    )
    _normalize_regular_path(
        ca_file,
        mode=0o640,
        uid=config_uid,
        gid=service_gid,
        optional=True,
    )
    descriptor = os.open(
        state_dir,
        _OPEN_BASE | os.O_DIRECTORY,
    )
    try:
        _normalize_state_directory(
            descriptor,
            service_uid=service_uid,
            service_gid=service_gid,
        )
    finally:
        os.close(descriptor)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--config-user", required=True)
    parser.add_argument("--service-user", required=True)
    parser.add_argument("--service-group", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config_uid = pwd.getpwnam(args.config_user).pw_uid
    service = pwd.getpwnam(args.service_user)
    service_gid = grp.getgrnam(args.service_group).gr_gid
    normalize_permissions(
        env_file=args.env_file,
        ca_file=args.ca_file,
        state_dir=args.state_dir,
        config_uid=config_uid,
        service_uid=service.pw_uid,
        service_gid=service_gid,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
