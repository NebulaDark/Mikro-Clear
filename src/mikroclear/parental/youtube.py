"""YouTube policy with RouterOS inventory and Pi-hole group as sources of truth."""

from __future__ import annotations

from typing import Any, Callable

from mikroclear.parental.models import ParentalDevice, YouTubePolicyState


class YouTubePolicyError(RuntimeError):
    pass


class YouTubePolicyService:
    def __init__(
        self,
        inventory: Any,
        pihole: Any,
        *,
        group_name: str,
        audit: Callable[..., Any] | None = None,
    ) -> None:
        self.inventory = inventory
        self.pihole = pihole
        self.group_name = str(group_name)
        self.audit = audit

    def list_devices(self) -> list[ParentalDevice]:
        return list(self.inventory.list_devices())

    def _checked(self, device: ParentalDevice) -> None:
        if not self.inventory.is_parental_device(device.ip):
            raise YouTubePolicyError("Device is not in the managed parental list")

    def get_state(self, device: ParentalDevice) -> YouTubePolicyState:
        self._checked(device)
        group = self.pihole.find_group(self.group_name)
        record = self.pihole.find_client(device.ip)
        blocked = bool(group and record and group.id in set(record.groups))
        return YouTubePolicyState(device, blocked, record is not None, group is not None, bool(group), "" if group else "YouTube group is missing")

    def _set(self, device: ParentalDevice, blocked: bool) -> YouTubePolicyState:
        self._checked(device)
        group = self.pihole.find_group(self.group_name)
        if group is None:
            raise YouTubePolicyError("YouTube policy group is missing")
        record = self.pihole.find_client(device.ip)
        if record is None:
            try:
                record = self.pihole.add_client(device.ip)
            except Exception as exc:
                if not getattr(exc, "ambiguous", False):
                    raise
                record = self.pihole.find_client(device.ip)
                if record is None:
                    raise YouTubePolicyError("Pi-hole client creation could not be confirmed") from exc
        already = group.id in set(record.groups)
        if already != blocked:
            try:
                self.pihole.set_group_membership(record, group, blocked)
            except Exception as exc:
                if not getattr(exc, "ambiguous", False):
                    raise
                record = self.pihole.find_client(device.ip)
                if record is None or ((group.id in set(record.groups)) != blocked):
                    raise YouTubePolicyError("Pi-hole membership update could not be confirmed") from exc
        state = self.get_state(device)
        if not state.healthy or state.blocked != blocked:
            raise YouTubePolicyError("Pi-hole did not confirm the requested YouTube state")
        return state

    def block(self, device: ParentalDevice) -> YouTubePolicyState:
        return self._set(device, True)

    def allow(self, device: ParentalDevice) -> YouTubePolicyState:
        return self._set(device, False)


__all__ = ["YouTubePolicyError", "YouTubePolicyService"]
