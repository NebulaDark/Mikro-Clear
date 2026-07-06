"""Asset resolution helpers."""

from dataclasses import dataclass
import ipaddress
import re
import socket
from time import time
from typing import Any, Callable

try:
    from librouteros.query import Key  # type: ignore
except Exception:  # pragma: no cover
    class Key:  # type: ignore
        def __init__(self, name: str) -> None:
            self.name = name

        def __eq__(self, other: Any) -> tuple[str, Any]:
            return (self.name, other)


EMPTY_ASSET = {
    "source": "",
    "name": "",
    "hostname": "",
    "comment": "",
    "mac": "",
    "server": "",
    "status": "",
    "dynamic": "",
}


@dataclass(frozen=True)
class AssetResolverConfig:
    enable: bool = True
    private_only: bool = True
    dhcp_enable: bool = True
    ptr_enable: bool = True
    cache_ttl: int = 3600


def is_private_ip_text(ip_text: str | None) -> bool:
    if not ip_text:
        return False

    try:
        return ipaddress.ip_address(ip_text).is_private
    except ValueError:
        return False


def is_valid_ip(ip_text: Any) -> bool:
    if not isinstance(ip_text, str) or not ip_text:
        return False
    try:
        ipaddress.ip_address(ip_text)
        return True
    except ValueError:
        return False


def sanitize_asset_value(value: Any, max_len: int = 80) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)

    if len(text) > max_len:
        text = text[: max_len - 3] + "..."

    return text


class AssetResolver:
    def __init__(
        self,
        config: AssetResolverConfig,
        *,
        get_router_client: Callable[[], Any],
        ptr_lookup: Callable[[str], str] | None = None,
        debug_log: Callable[[str], None] | None = None,
        now: Callable[[], float] = time,
    ) -> None:
        self.config = config
        self.get_router_client = get_router_client
        self.ptr_lookup = ptr_lookup or (lambda ip: socket.gethostbyaddr(ip)[0])
        self.debug_log = debug_log or (lambda message: None)
        self.now = now
        self.cache: dict[str, tuple[float, dict[str, str]]] = {}

    def cache_get(self, ip_text: str) -> dict[str, str] | None:
        cached = self.cache.get(ip_text)

        if not cached:
            return None

        cached_time, cached_value = cached

        if self.now() - cached_time > self.config.cache_ttl:
            self.cache.pop(ip_text, None)
            return None

        return cached_value

    def cache_set(self, ip_text: str, value: dict[str, str]) -> dict[str, str]:
        self.cache[ip_text] = (self.now(), value)
        return value

    def resolve_from_dhcp(self, ip_text: str) -> dict[str, str]:
        if not self.config.dhcp_enable:
            return {}

        try:
            client = self.get_router_client()
            api = client.ensure_connected()
            leases = api.path("/ip/dhcp-server/lease")

            _address = Key("address")
            rows = list(
                leases.select(
                    ".id",
                    "address",
                    "host-name",
                    "comment",
                    "mac-address",
                    "server",
                    "status",
                    "dynamic",
                ).where(_address == ip_text)
            )

            if not rows:
                return {}

            row = rows[0]
            hostname = sanitize_asset_value(row.get("host-name"))
            comment = sanitize_asset_value(row.get("comment"))
            mac = sanitize_asset_value(row.get("mac-address"))
            server = sanitize_asset_value(row.get("server"))
            status = sanitize_asset_value(row.get("status"))
            dynamic = sanitize_asset_value(row.get("dynamic"))
            display_name = hostname or comment or mac

            return {
                "source": "dhcp",
                "name": display_name,
                "hostname": hostname,
                "comment": comment,
                "mac": mac,
                "server": server,
                "status": status,
                "dynamic": dynamic,
            }

        except Exception as exc:
            self.debug_log(f"Asset DHCP resolver failed for {ip_text}: {type(exc).__name__}: {exc}")
            return {}

    def resolve_from_ptr(self, ip_text: str) -> dict[str, str]:
        if not self.config.ptr_enable:
            return {}

        try:
            hostname = sanitize_asset_value(self.ptr_lookup(ip_text))

            if not hostname:
                return {}

            return {
                "source": "ptr",
                "name": hostname,
                "hostname": hostname,
                "comment": "",
                "mac": "",
                "server": "",
                "status": "",
                "dynamic": "",
            }

        except Exception:
            return {}

    def resolve(self, ip_text: str | None) -> dict[str, str]:
        if not self.config.enable:
            return {}

        if not ip_text or not is_valid_ip(ip_text):
            return {}

        if self.config.private_only and not is_private_ip_text(ip_text):
            return {}

        cached = self.cache_get(ip_text)
        if cached is not None:
            return cached

        asset = self.resolve_from_dhcp(ip_text)

        if not asset:
            asset = self.resolve_from_ptr(ip_text)

        if not asset:
            asset = dict(EMPTY_ASSET)

        return self.cache_set(ip_text, asset)


__all__ = [
    "AssetResolver",
    "AssetResolverConfig",
    "EMPTY_ASSET",
    "is_private_ip_text",
    "is_valid_ip",
    "sanitize_asset_value",
]
