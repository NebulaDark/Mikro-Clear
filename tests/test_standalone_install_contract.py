from pathlib import Path
import re
import tomllib
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
INSTALL_GUIDE = ROOT / "docs/ru/install-from-github.md"
INSTALL_REPRODUCTION = ROOT / "docs/ru/install-test-reproduction.md"


class StandaloneInstallContractTests(TestCase):
    def test_mcp_is_tooling_only_not_package_metadata_dependency(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        runtime = data["project"]["dependencies"]
        optional_groups = data["project"].get("optional-dependencies", {})
        tooling = data.get("dependency-groups", {}).get("mcp-tools", [])

        self.assertFalse(
            any(item.split("=", 1)[0].lower() == "mcp" for item in runtime)
        )
        self.assertFalse(
            any(
                item.split("=", 1)[0].lower() == "mcp"
                for dependencies in optional_groups.values()
                for item in dependencies
            )
        )
        self.assertIn("mcp==1.28.1", tooling)

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

    def test_operator_installation_remains_git_and_repository_script_only(self):
        for path in (INSTALL_GUIDE, INSTALL_REPRODUCTION):
            with self.subTest(path=str(path)):
                text = path.read_text(encoding="utf-8")
                self.assertIn("git clone", text)
                self.assertIn("git rev-parse HEAD", text)
                self.assertIn("scripts/install-selks.sh", text)
                self.assertNotIn("/usr/local/bin/mikroclear.py", text)
                self.assertNotIn("services/mcp-server", text)
                self.assertNotIn("mcp-selks", text.lower())
                self.assertNotIn("MCP", text)
                self.assertNotIn("api.telegram.org", text)
                self.assertNotRegex(
                    text,
                    re.compile(r"\b[0-9]{8,10}:[A-Za-z0-9_-]{30,}\b"),
                )
