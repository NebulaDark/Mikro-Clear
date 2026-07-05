"""RouterOS API-SSL context helpers."""

from __future__ import annotations

import ssl
from typing import Any, Callable


def build_routeros_ssl_context(
    *,
    cafile: str,
    allow_self_signed: bool,
    context_factory: Callable[[], ssl.SSLContext] | None = None,
) -> ssl.SSLContext:
    context_factory = context_factory or (lambda: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    ctx = context_factory()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2

    if allow_self_signed:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    else:
        ctx.load_verify_locations(cafile=cafile)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED

    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except Exception:
        pass

    ctx.options |= ssl.OP_NO_COMPRESSION
    return ctx


def make_routeros_ssl_wrapper(ctx: Any, server_hostname: str) -> Callable[..., Any]:
    def ssl_wrapper(sock: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("server_hostname", server_hostname)
        return ctx.wrap_socket(sock, **kwargs)

    return ssl_wrapper


__all__ = ["build_routeros_ssl_context", "make_routeros_ssl_wrapper"]
