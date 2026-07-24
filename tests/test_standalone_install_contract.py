from pathlib import Path
import tomllib
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]


class StandaloneInstallContractTests(TestCase):
    def test_mcp_is_optional_not_runtime_dependency(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        runtime = data["project"]["dependencies"]
        optional = data["project"].get("optional-dependencies", {}).get("mcp-tools", [])

        self.assertFalse(
            any(item.split("=", 1)[0].lower() == "mcp" for item in runtime)
        )
        self.assertIn("mcp==1.28.1", optional)

    def test_new_runtime_files_use_canonical_ca_path(self):
        paths = (
            ROOT / "src/mikroclear/settings.py",
            ROOT / "config/mikroclear.env.example",
        )
        for path in paths:
            with self.subTest(path=str(path)):
                text = path.read_text(encoding="utf-8")
                self.assertIn("/etc/mikroclear/certs/mikrotik-ca.crt", text)
                self.assertNotIn("/etc/mikrocata/certs", text)
