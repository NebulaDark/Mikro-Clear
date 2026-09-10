"""Deprecated compatibility shim for runtime state helpers."""

from mikroclear.state import (
    StateStoreConfig,
    add_saved_lists,
    check_tik_uptime,
    ensure_private_runtime_file,
    parse_routeros_uptime,
    save_lists,
)

__all__ = [
    "StateStoreConfig",
    "add_saved_lists",
    "check_tik_uptime",
    "ensure_private_runtime_file",
    "parse_routeros_uptime",
    "save_lists",
]
