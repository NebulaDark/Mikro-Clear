import json
import os
import stat
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from mikroclear.bot.audit import BotAuditLog


class BotAuditLogTests(TestCase):
    def test_audit_appends_private_json_without_secret_fields(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "bot-audit.log")
            audit = BotAuditLog(path)

            audit.record(
                action="whitelist.add",
                outcome="success",
                chat_id="chat-1",
                user_id="user-1",
                target="192.168.98.200",
                detail="removed=1",
            )

            row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["action"], "whitelist.add")
            self.assertNotIn("token", row)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_audit_appends_rows_and_uses_exact_schema(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "nested", "bot-audit.log")
            audit = BotAuditLog(path)

            audit.record("whitelist.add", "success", "chat-1", "user-1", "10.0.0.1")
            audit.record("whitelist.remove", "denied", "chat-2", "user-2", "10.0.0.2", "dry-run")

            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            expected_keys = {
                "timestamp",
                "action",
                "outcome",
                "chat_id",
                "user_id",
                "target",
                "detail",
            }
            self.assertEqual(len(rows), 2)
            self.assertEqual(set(rows[0]), expected_keys)
            self.assertEqual(rows[0]["detail"], "")
            self.assertEqual(rows[1]["action"], "whitelist.remove")
            self.assertEqual(rows[1]["detail"], "dry-run")
            self.assertIsNotNone(datetime.fromisoformat(rows[0]["timestamp"]).tzinfo)

    def test_audit_sanitizes_fields_and_repairs_existing_file_permissions(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp, "bot-audit.log")
            path.write_text("", encoding="utf-8")
            os.chmod(path, 0o644)
            audit = BotAuditLog(path)

            audit.record(
                action=" whitelist.\nadd 🚨 ",
                outcome=" success\tqueued ",
                chat_id="chat\n1",
                user_id="user\t1",
                target="x" * 100,
                detail="d" * 250,
            )

            row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["action"], "whitelist. add")
            self.assertEqual(row["outcome"], "success queued")
            self.assertEqual(row["chat_id"], "chat 1")
            self.assertEqual(row["user_id"], "user 1")
            self.assertEqual(len(row["target"]), 80)
            self.assertTrue(row["target"].endswith("..."))
            self.assertEqual(len(row["detail"]), 240)
            self.assertTrue(row["detail"].endswith("..."))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
