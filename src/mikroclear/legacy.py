"""Compatibility wrapper for legacy ``mikroclear.legacy`` imports."""

from __future__ import annotations


def main() -> int:
    from mikroclear import app

    return app.main()


__all__ = ["main"]
