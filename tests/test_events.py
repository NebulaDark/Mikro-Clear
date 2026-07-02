import unittest

from mikroclear.events import (
    should_process_event,
    validate_event,
)


def event(**overrides):
    data = {
        "src_ip": "8.8.8.8",
        "dest_ip": "192.168.10.15",
        "in_iface": "tzsp0",
        "alert": {
            "signature_id": 2402000,
            "severity": 2,
            "signature": "ET DROP test",
        },
    }
    data.update(overrides)
    return data


class EventValidationTests(unittest.TestCase):
    def test_validate_event_accepts_alert_with_signature_and_valid_ips(self):
        raw = event()

        self.assertIs(validate_event(raw), raw)

    def test_validate_event_rejects_invalid_shapes(self):
        self.assertIsNone(validate_event("not an event"))
        self.assertIsNone(validate_event({"src_ip": "8.8.8.8", "dest_ip": "1.1.1.1"}))
        self.assertIsNone(validate_event(event(alert={"severity": 2})))
        self.assertIsNone(validate_event(event(src_ip="not-ip")))
        self.assertIsNone(validate_event(event(dest_ip="not-ip")))


class EventFilteringTests(unittest.TestCase):
    def test_should_process_valid_event(self):
        decision = should_process_event(
            event(),
            severities=("1", "2"),
            listen_interfaces=("tzsp0",),
            ignore_predicate=lambda item: False,
            enable_ipv6=False,
        )

        self.assertTrue(decision.should_process)

    def test_should_skip_unwanted_severity(self):
        decision = should_process_event(
            event(alert={"signature_id": 2402000, "severity": 3}),
            severities=("1", "2"),
            listen_interfaces=("tzsp0",),
            ignore_predicate=lambda item: False,
            enable_ipv6=False,
        )

        self.assertFalse(decision.should_process)
        self.assertEqual(decision.log_method, "debug")
        self.assertIn("severity=3", decision.message)

    def test_should_skip_unwanted_interface(self):
        decision = should_process_event(
            event(in_iface="eth0"),
            severities=("1", "2"),
            listen_interfaces=("tzsp0",),
            ignore_predicate=lambda item: False,
            enable_ipv6=False,
        )

        self.assertFalse(decision.should_process)
        self.assertIn("interface=eth0", decision.message)

    def test_should_skip_ignored_event(self):
        decision = should_process_event(
            event(),
            severities=("1", "2"),
            listen_interfaces=("tzsp0",),
            ignore_predicate=lambda item: True,
            enable_ipv6=False,
        )

        self.assertFalse(decision.should_process)
        self.assertEqual(decision.log_method, "log")
        self.assertIn("in ignore list", decision.message)

    def test_should_skip_ipv6_when_disabled(self):
        decision = should_process_event(
            event(src_ip="2001:db8::1", dest_ip="2001:db8::2"),
            severities=("1", "2"),
            listen_interfaces=("tzsp0",),
            ignore_predicate=lambda item: False,
            enable_ipv6=False,
        )

        self.assertFalse(decision.should_process)
        self.assertIn("IPv6 disabled", decision.message)


if __name__ == "__main__":
    unittest.main()
