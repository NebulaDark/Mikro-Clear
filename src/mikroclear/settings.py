"""Typed runtime settings."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Placeholder settings boundary for the legacy migration."""


__all__ = ["Settings"]
