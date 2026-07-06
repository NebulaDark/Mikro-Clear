"""RouterOS firewall mangle rule helpers."""

from dataclasses import dataclass
from typing import Any

try:
    from librouteros.query import Key  # type: ignore
except Exception:  # pragma: no cover
    class Key:  # type: ignore
        def __init__(self, name: str) -> None:
            self.name = name

        def __eq__(self, other: Any) -> tuple[str, Any]:
            return (self.name, other)


@dataclass(frozen=True)
class MangleRule:
    rule_id: str
    name: str
    comment: str
    chain: str
    action: str
    disabled: bool
    packets: int = 0
    bytes: int = 0


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _is_disabled(value: Any) -> bool:
    return str(value).strip().lower() in {"yes", "true", "1"}


def _mangle_resource(api: Any) -> Any:
    return api.path("/ip/firewall/mangle")


def _row_to_rule(row: dict[str, Any], settings: Any) -> MangleRule | None:
    prefix = str(settings.mangle_comment_prefix)
    comment = str(row.get("comment", ""))
    chain = str(row.get("chain", ""))
    action = str(row.get("action", ""))
    rule_id = str(row.get(".id", ""))

    if not rule_id or not comment.startswith(prefix):
        return None

    return MangleRule(
        rule_id=rule_id,
        name=comment[len(prefix) :].strip() or rule_id,
        comment=comment,
        chain=chain,
        action=action,
        disabled=_is_disabled(row.get("disabled", "no")),
        packets=_to_int(row.get("packets", 0)),
        bytes=_to_int(row.get("bytes", 0)),
    )


def _select_rows(resource: Any) -> list[dict[str, Any]]:
    return list(
        resource.select(
            ".id",
            "comment",
            "chain",
            "action",
            "disabled",
            "packets",
            "bytes",
        )
    )


def list_managed_mangle_rules(api: Any, settings: Any) -> list[MangleRule]:
    rules: list[MangleRule] = []
    for row in _select_rows(_mangle_resource(api)):
        rule = _row_to_rule(row, settings)
        if rule is not None:
            rules.append(rule)
    return rules


def get_managed_mangle_rule(api: Any, rule_id: str, settings: Any) -> MangleRule | None:
    wanted_id = str(rule_id)
    _id = Key(".id")
    resource = _mangle_resource(api)
    try:
        rows = list(
            resource.select(
                ".id",
                "comment",
                "chain",
                "action",
                "disabled",
                "packets",
                "bytes",
            ).where(_id == wanted_id)
        )
    except AttributeError:
        rows = [row for row in _select_rows(resource) if str(row.get(".id", "")) == wanted_id]

    for row in rows:
        if str(row.get(".id", "")) == wanted_id:
            return _row_to_rule(row, settings)
    return None


def set_mangle_rule_disabled(api: Any, rule_id: str, disabled: bool, settings: Any) -> None:
    rule = get_managed_mangle_rule(api, rule_id, settings)
    if rule is None:
        raise PermissionError("Mangle rule is not managed by Mikro-Clear")
    _mangle_resource(api).update(rule.rule_id, disabled="yes" if disabled else "no")


__all__ = [
    "MangleRule",
    "get_managed_mangle_rule",
    "list_managed_mangle_rules",
    "set_mangle_rule_disabled",
]
