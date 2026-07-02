import os
from typing import Sequence


def env_name_candidates(name: str) -> tuple[str, ...]:
    if name.startswith("MIKROCATA_"):
        return ("MIKROCLEAR_" + name.removeprefix("MIKROCATA_"), name)
    return (name,)


def env_str(name: str, default: str = "") -> str:
    for candidate in env_name_candidates(name):
        value = os.getenv(candidate)
        if value is not None:
            return value.strip()
    return default.strip()


def env_bool(name: str, default: bool = False) -> bool:
    for candidate in env_name_candidates(name):
        value = os.getenv(candidate)
        if value is not None:
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def env_int(name: str, default: int) -> int:
    for candidate in env_name_candidates(name):
        value = os.getenv(candidate)
        if value is None:
            continue
        if value.strip() == "":
            return default
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def env_csv(name: str, default: Sequence[str]) -> tuple[str, ...]:
    value = None
    for candidate in env_name_candidates(name):
        value = os.getenv(candidate)
        if value is not None:
            break
    if value is None or value.strip() == "":
        return tuple(default)

    normalized = value.replace("\n", ",").replace(";", ",")
    return tuple(
        item.strip().strip('"').strip("'")
        for item in normalized.split(",")
        if item.strip().strip('"').strip("'")
    )
