from unittest import TestCase

from mikroclear.settings import Settings
from mikroclear.routeros.mangle import (
    MangleRule,
    get_managed_mangle_rule,
    list_managed_mangle_rules,
    set_mangle_rule_disabled,
)


class FakeWhere:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def where(self, *args):
        return self.rows


class FakeMangleResource:
    def __init__(self, rows):
        self.rows = rows
        self.updated = []

    def select(self, *keys):
        return FakeWhere(self.rows)

    def update(self, rule_id, **kwargs):
        self.updated.append((rule_id, kwargs))


class FakeApi:
    def __init__(self, rows):
        self.mangle = FakeMangleResource(rows)
        self.paths = []

    def path(self, name):
        self.paths.append(name)
        if name != "/ip/firewall/mangle":
            raise AssertionError(f"unexpected path {name}")
        return self.mangle


def settings(**overrides):
    return Settings(
        mangle_control_enable=True,
        mangle_comment_prefix="MC:",
        **overrides,
    )


class RouterOsMangleTests(TestCase):
    def test_list_managed_rules_filters_only_by_comment_prefix(self):
        api = FakeApi(
            [
                {
                    ".id": "*1",
                    "comment": "MC:AI-Tunnel",
                    "chain": "prerouting",
                    "action": "mark-routing",
                    "disabled": "false",
                    "packets": "4516",
                    "bytes": "3615163",
                },
                {".id": "*2", "comment": "manual", "chain": "prerouting", "action": "mark-routing"},
                {".id": "*3", "comment": "MC:Postrouting", "chain": "postrouting", "action": "mark-routing"},
                {".id": "*4", "comment": "MC:Masquerade", "chain": "forward", "action": "masquerade"},
            ]
        )

        rules = list_managed_mangle_rules(api, settings())

        self.assertEqual(
            rules,
            [
                MangleRule(
                    rule_id="*1",
                    name="AI-Tunnel",
                    comment="MC:AI-Tunnel",
                    chain="prerouting",
                    action="mark-routing",
                    disabled=False,
                    packets=4516,
                    bytes=3615163,
                ),
                MangleRule(
                    rule_id="*3",
                    name="Postrouting",
                    comment="MC:Postrouting",
                    chain="postrouting",
                    action="mark-routing",
                    disabled=False,
                ),
                MangleRule(
                    rule_id="*4",
                    name="Masquerade",
                    comment="MC:Masquerade",
                    chain="forward",
                    action="masquerade",
                    disabled=False,
                ),
            ],
        )

    def test_set_disabled_updates_only_disabled_yes_no(self):
        api = FakeApi(
            [
                {
                    ".id": "*1",
                    "comment": "MC:AI-Tunnel",
                    "chain": "prerouting",
                    "action": "mark-routing",
                    "disabled": "false",
                }
            ]
        )

        set_mangle_rule_disabled(api, "*1", True, settings())
        set_mangle_rule_disabled(api, "*1", False, settings())

        self.assertEqual(api.mangle.updated, [("*1", {"disabled": "yes"}), ("*1", {"disabled": "no"})])

    def test_unmanaged_rule_is_rejected_before_update(self):
        api = FakeApi([{".id": "*1", "comment": "manual", "chain": "prerouting", "action": "mark-routing"}])

        with self.assertRaises(PermissionError):
            set_mangle_rule_disabled(api, "*1", True, settings())

        self.assertEqual(api.mangle.updated, [])

    def test_changed_comment_is_rejected(self):
        api = FakeApi([{".id": "*1", "comment": "manual", "chain": "prerouting", "action": "mark-routing"}])

        with self.assertRaises(PermissionError):
            set_mangle_rule_disabled(api, "*1", False, settings())

        self.assertEqual(api.mangle.updated, [])

    def test_any_chain_or_action_is_managed_when_comment_has_prefix(self):
        api = FakeApi([{".id": "*1", "comment": "MC:Any", "chain": "custom-chain", "action": "custom-action"}])

        set_mangle_rule_disabled(api, "*1", True, settings())

        self.assertEqual(api.mangle.updated, [("*1", {"disabled": "yes"})])

    def test_get_managed_rule_returns_none_for_missing_or_unmanaged(self):
        api = FakeApi([{".id": "*1", "comment": "manual", "chain": "prerouting", "action": "mark-routing"}])

        self.assertIsNone(get_managed_mangle_rule(api, "*1", settings()))
        self.assertIsNone(get_managed_mangle_rule(api, "*missing", settings()))
