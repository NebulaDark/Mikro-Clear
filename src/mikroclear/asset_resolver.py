"""Compatibility shim for asset resolver imports."""

from mikroclear.assets.resolver import (
    EMPTY_ASSET,
    AssetResolver,
    AssetResolverConfig,
    is_private_ip_text,
    is_valid_ip,
    sanitize_asset_value,
)

__all__ = [
    "AssetResolver",
    "AssetResolverConfig",
    "EMPTY_ASSET",
    "is_private_ip_text",
    "is_valid_ip",
    "sanitize_asset_value",
]
