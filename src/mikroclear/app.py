"""Top-level Mikro-Clear service entrypoint."""

from __future__ import annotations

from mikroclear.runtime import MikroClearService
from mikroclear.runtime.wiring import build_runtime_service
from mikroclear.settings import load_settings


def build_service() -> MikroClearService:
    settings = load_settings()
    return build_runtime_service(settings)


def main() -> int:
    return build_service().run()


__all__ = ["build_service", "main"]
