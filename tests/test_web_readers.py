import json
from pathlib import Path
import tempfile
import unittest

from mikroclear.web.readers import recent_alerts, tail_lines, text_log


class WebReaderTests(unittest.TestCase):
    def test_tail_lines_returns_requested_tail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.log"
            path.write_text(
                "\n".join(f"line-{index}" for index in range(20)) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                tail_lines(path, limit=3),
                ["line-17", "line-18", "line-19"],
            )

    def test_recent_alerts_filters_and_searches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "eve.json"
            rows = [
                {"event_type": "flow", "src_ip": "10.0.0.1"},
                {
                    "event_type": "alert",
                    "timestamp": "2026-10-04T10:00:00.000000+0300",
                    "src_ip": "203.0.113.10",
                    "dest_ip": "192.0.2.10",
                    "proto": "TCP",
                    "alert": {
                        "severity": 1,
                        "signature_id": 1001,
                        "signature": "Test SSH alert",
                        "category": "Attempted Administrator Privilege Gain",
                    },
                },
            ]
            path.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )

            result = recent_alerts(path, limit=10, query="ssh")

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["signature_id"], 1001)

    def test_text_log_filters_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.log"
            path.write_text(
                "OK\nRouterOS ERROR\nready\n",
                encoding="utf-8",
            )
            self.assertEqual(
                text_log(path, query="error"),
                ["RouterOS ERROR"],
            )


if __name__ == "__main__":
    unittest.main()
