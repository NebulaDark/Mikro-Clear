#!/usr/bin/env python3
"""Validate the Mikro-Clear wheel before any SELKS install stage."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys
import zipfile


REQUIRED_MEMBERS = (
    "mikroclear/__main__.py",
    "mikroclear/cli.py",
    "mikroclear/app.py",
    "mikroclear/runtime/__init__.py",
)

REQUIRED_CONSOLE_SCRIPT = "mikroclear = mikroclear.cli:main"


@dataclass(frozen=True)
class WheelValidationResult:
    wheel: Path
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_wheel(wheel_path: str | Path) -> WheelValidationResult:
    path = Path(wheel_path)
    errors: list[str] = []

    if path.suffix != ".whl":
        errors.append(f"expected .whl artifact: {path}")
        return WheelValidationResult(path, tuple(errors))

    if not path.exists():
        errors.append(f"wheel does not exist: {path}")
        return WheelValidationResult(path, tuple(errors))

    try:
        with zipfile.ZipFile(path) as wheel:
            names = set(wheel.namelist())
            for member in REQUIRED_MEMBERS:
                if member not in names:
                    errors.append(f"missing required member: {member}")

            entry_points_members = [
                name for name in names if name.endswith(".dist-info/entry_points.txt")
            ]
            if not entry_points_members:
                errors.append("missing wheel entry_points.txt")
            elif not _has_required_console_script(wheel, entry_points_members):
                errors.append(f"missing console script: {REQUIRED_CONSOLE_SCRIPT}")

            metadata_members = [
                name for name in names if name.endswith(".dist-info/METADATA")
            ]
            for member in sorted(metadata_members):
                metadata = wheel.read(member).decode("utf-8")
                for line in metadata.splitlines():
                    if not line.lower().startswith("requires-dist:"):
                        continue
                    dependency = line.split(":", 1)[1].strip()
                    normalized = re.split(
                        r"[\s(<=>!~;\[]",
                        dependency,
                        maxsplit=1,
                    )[0].lower()
                    if normalized == "mcp":
                        errors.append("forbidden runtime dependency: mcp")
    except zipfile.BadZipFile:
        errors.append(f"not a valid wheel zip archive: {path}")

    return WheelValidationResult(path, tuple(errors))


def _has_required_console_script(wheel: zipfile.ZipFile, members: list[str]) -> bool:
    for member in sorted(members):
        text = wheel.read(member).decode("utf-8")
        if REQUIRED_CONSOLE_SCRIPT in text:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", help="Path to mikro_clear-*.whl")
    args = parser.parse_args(argv)

    result = validate_wheel(args.wheel)
    if result.ok:
        print(f"wheel ok: {result.wheel}")
        return 0

    for error in result.errors:
        print(f"wheel error: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
