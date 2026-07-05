"""Compatibility alias for legacy ``mikroclear.legacy`` imports."""

from __future__ import annotations

import sys

from mikroclear import legacy_runtime as _legacy_runtime


def main() -> int:
    from mikroclear import app

    return app.main()


_legacy_runtime.main = main
sys.modules[__name__] = _legacy_runtime
