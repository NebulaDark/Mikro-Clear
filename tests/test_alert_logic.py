import unittest

from mikrocata.alert_logic import (
    legacy_decide_alert_target,
    legacy_deduplicate_by_src_ip,
    target_aware_deduplicate,
)


WHITELIST = ("192.168.0.0/16", "127.0.0.1")


def event(src_ip, dest_ip, src_port=1111, dest_port=2222):
    return {
        "src_ip": src_ip,
        "dest_ip": dest_ip,
        "src_port": src_port,
        "dest_port": dest_port,
    }


class AlertTargetDecisionTests(unittest.TestCase):
    def test_external_source_is_block_target_and_uses_dest_port(self):
        decision = legacy_decide_alert_target(
            event("8.8.8.8", "192.168.10.15", src_port=53123, dest_port=443),
            WHITELIST,
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.wanted_ip, "8.8.8.8")
        self.assertEqual(decision.peer_ip, "192.168.10.15")
        self.assertEqual(decision.wanted_port, 443)

    def test_whitelisted_source_to_external_dest_blocks_dest_current_behavior(self):
        decision = legacy_decide_alert_target(
            event("192.168.10.15", "9.9.9.9", src_port=53123, dest_port=443),
            WHITELIST,
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.wanted_ip, "9.9.9.9")
        self.assertEqual(decision.peer_ip, "192.168.10.15")
        self.assertEqual(decision.wanted_port, 53123)

    @unittest.expectedFailure
    def test_whitelisted_source_to_external_dest_should_use_dest_port(self):
        decision = legacy_decide_alert_target(
            event("192.168.10.15", "9.9.9.9", src_port=53123, dest_port=443),
            WHITELIST,
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.wanted_port, 443)

    def test_whitelisted_source_to_whitelisted_dest_is_skipped(self):
        decision = legacy_decide_alert_target(
            event("192.168.10.15", "192.168.10.20"),
            WHITELIST,
        )

        self.assertIsNone(decision)


class DeduplicationTests(unittest.TestCase):
    def test_legacy_deduplicates_by_source_ip(self):
        events = [
            event("192.168.10.15", "9.9.9.9"),
            event("192.168.10.15", "8.8.8.8"),
        ]

        deduped = legacy_deduplicate_by_src_ip(events)

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["dest_ip"], "8.8.8.8")

    def test_target_aware_dedup_keeps_different_targets(self):
        events = [
            event("192.168.10.15", "9.9.9.9"),
            event("192.168.10.15", "8.8.8.8"),
        ]

        deduped = target_aware_deduplicate(events, WHITELIST)

        self.assertEqual(len(deduped), 2)
        self.assertEqual([item["dest_ip"] for item in deduped], ["9.9.9.9", "8.8.8.8"])


if __name__ == "__main__":
    unittest.main()
