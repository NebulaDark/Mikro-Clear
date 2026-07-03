import os
from pathlib import Path
import tempfile
import unittest

from mikroclear.telegram_unblock import create_unblock_token, ensure_private_state_path


class RuntimePermissionTests(unittest.TestCase):
    def test_ensure_private_state_path_sets_private_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "telegram-unblock-actions.json"

            ensure_private_state_path(path)

            self.assertEqual(oct(path.parent.stat().st_mode & 0o777), "0o700")
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")

    def test_create_unblock_token_keeps_private_modes_under_public_umask(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "telegram-unblock-actions.json"
            old_umask = os.umask(0o022)
            try:
                create_unblock_token(
                    path,
                    wanted_ip="9.9.9.9",
                    list_name="Suricata",
                    sid="2402000",
                    now=100,
                    ttl_seconds=3600,
                    token_factory=lambda: "tok123",
                )
            finally:
                os.umask(old_umask)

            self.assertEqual(oct(path.parent.stat().st_mode & 0o777), "0o700")
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()
