import json
from pathlib import Path
import tempfile
from unittest import TestCase

from mikroclear.eve_watcher import EveJsonTailer


class EveJsonTailerTests(TestCase):
    def test_seek_to_end_starts_after_existing_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eve.json"
            path.write_text(json.dumps({"event_type": "alert", "src_ip": "1.1.1.1"}) + "\n", encoding="utf-8")
            tailer = EveJsonTailer(add_on_start=False, shutdown_requested=lambda: False)

            tailer.seek_to_end(str(path))
            self.assertEqual(tailer.read_json(str(path)), [])

    def test_add_on_start_reads_existing_alerts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eve.json"
            event = {"event_type": "alert", "src_ip": "1.1.1.1"}
            path.write_text(json.dumps(event) + "\n", encoding="utf-8")
            tailer = EveJsonTailer(add_on_start=True, shutdown_requested=lambda: False)

            tailer.seek_to_end(str(path))
            self.assertEqual(tailer.read_json(str(path)), [event])

    def test_read_json_filters_non_alerts_and_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eve.json"
            alert = {"event_type": "alert", "src_ip": "1.1.1.1"}
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"event_type": "stats"}),
                        "{not-json",
                        json.dumps(alert),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            tailer = EveJsonTailer(add_on_start=True, shutdown_requested=lambda: False)

            self.assertEqual(tailer.read_json(str(path)), [alert])

    def test_read_json_resets_position_after_truncate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eve.json"
            first = {"event_type": "alert", "src_ip": "1.1.1.1"}
            second = {"event_type": "alert"}
            path.write_text(json.dumps(first) + "\n", encoding="utf-8")
            tailer = EveJsonTailer(add_on_start=True, shutdown_requested=lambda: False)
            self.assertEqual(tailer.read_json(str(path)), [first])

            path.write_text(json.dumps(second) + "\n", encoding="utf-8")

            self.assertEqual(tailer.read_json(str(path)), [second])
