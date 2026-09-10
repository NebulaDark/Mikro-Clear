"""Deprecated compatibility shim for RouterOS TLS helpers."""

from mikroclear.routeros.ssl_context import build_routeros_ssl_context, make_routeros_ssl_wrapper

__all__ = ["build_routeros_ssl_context", "make_routeros_ssl_wrapper"]
