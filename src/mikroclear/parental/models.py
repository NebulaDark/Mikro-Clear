"""Parental-control domain models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ParentalDevice:
    ip: str
    name: str = ""
    comment: str = ""
    mac: str = ""


@dataclass(frozen=True)
class YouTubePolicyState:
    device: ParentalDevice
    blocked: bool
    pihole_client_found: bool
    group_found: bool
    healthy: bool
    error: str = ""


__all__ = ["ParentalDevice", "YouTubePolicyState"]
